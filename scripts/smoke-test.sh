#!/usr/bin/env bash
# TraceMap local smoke tests.
#
# Default mode (no arguments):
#   * read-only checks against the running dev stack (loopback binding, /health,
#     /docs, /openapi.json, unauthenticated 401, Vite /api proxy);
#   * a full API workflow against a THROWAWAY API instance with its own SQLite
#     file, so the developer database is never written to.
#
# --restart mode:
#   * exercises `dev-start.sh` / `dev-stop.sh` end to end in an isolated runtime
#     directory: start -> health -> stop (port released) -> start -> data still
#     readable -> stop. Does not touch the normal dev data.
#
# Usage: scripts/smoke-test.sh [--restart]
set -uo pipefail   # no -e: we count individual failures

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/dev-common.sh"
set +e   # dev-common.sh enables errexit; this harness needs to keep going
validate_dev_configuration

# Cleanup even on failed assertions, SIGTERM, or a failed startup.
WORKFLOW_TMP=""
WORKFLOW_PID=""
RESTART_TMP=""
cleanup_smoke() {
  if [[ -n "$WORKFLOW_PID" ]] && pid_alive "$WORKFLOW_PID"; then
    kill "$WORKFLOW_PID" 2>/dev/null || true
    wait "$WORKFLOW_PID" 2>/dev/null || true
  fi
  [[ -n "$WORKFLOW_TMP" && -d "$WORKFLOW_TMP" ]] && rm -rf -- "$WORKFLOW_TMP"
  if [[ -n "$RESTART_TMP" && -d "$RESTART_TMP" ]]; then
    TRACEMAP_RUNTIME_DIR="$RESTART_TMP/run" \
      TRACEMAP_API_PORT="${RESTART_API_PORT:-8030}" \
      TRACEMAP_WEB_PORT="${RESTART_WEB_PORT:-5183}" \
      env -u TRACEMAP_DATABASE_URL "$SCRIPT_DIR/dev-stop.sh" >/dev/null 2>&1 || true
    rm -rf -- "$RESTART_TMP"
  fi
}
trap cleanup_smoke EXIT

pick_port() {
  "$API_PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}


PASS=0; FAIL=0; SKIP=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; SKIP=$((SKIP+1)); }
section() { printf '\n== %s ==\n' "$1"; }

expect_eq() { # label actual expected
  if [[ "$2" == "$3" ]]; then ok "$1 ($2)"; else bad "$1: got '$2' want '$3'"; fi
}

# ---------------------------------------------------------------------------
# restart cycle
# ---------------------------------------------------------------------------
run_restart_cycle() {
  section "start / stop / restart / persistence cycle (isolated runtime)"
  local tmp runtime pids ports
  tmp="$(mktemp -d /tmp/tracemap-restart.XXXXXX)"
  RESTART_TMP="$tmp"
  export TRACEMAP_RUNTIME_DIR="$tmp/run"
  # Never allow an inherited URL to point a restart test at user data.
  unset TRACEMAP_DATABASE_URL
  # Keep the isolated restart offline/hermetic (no repository .env, no real model).
  export TRACEMAP_DOTENV=0
  export TRACEMAP_GENERATION_MODE=extractive
  RESTART_API_PORT="$(pick_port)"
  RESTART_WEB_PORT="$(pick_port)"
  while [[ "$RESTART_API_PORT" == "$RESTART_WEB_PORT" ]]; do RESTART_WEB_PORT="$(pick_port)"; done
  export TRACEMAP_API_PORT="$RESTART_API_PORT"
  export TRACEMAP_WEB_PORT="$RESTART_WEB_PORT"
  # re-source so derived paths pick up the overrides
  source "$SCRIPT_DIR/dev-common.sh"
  set +e

  "$SCRIPT_DIR/dev-start.sh" >"$tmp/start1.log" 2>&1 || { bad "first dev-start.sh"; tail -n 20 "$tmp/start1.log"; return; }
  ok "first start"

  local health; health="$(curl -fsS "http://$API_HOST:$API_PORT/health" 2>/dev/null)"
  [[ "$health" == *'"status":"ok"'* || "$health" == *'"status": "ok"'* ]] && ok "health after first start" || bad "health after first start: $health"

  local create; create="$(curl -fsS -X POST "http://$API_HOST:$API_PORT/api/v1/projects" \
    -H "Authorization: Bearer dev-alice" -H "Content-Type: application/json" -H "Idempotency-Key: restart-create-0001" \
    -d '{"title":"重启持久化验证","goal":"persist"}' 2>/dev/null)"
  local pid_; pid_="$(printf '%s' "$create" | jq -r '.id // empty')"
  [[ -n "$pid_" ]] && ok "created project before restart" || bad "create project: $create"

  "$SCRIPT_DIR/dev-stop.sh" >"$tmp/stop1.log" 2>&1 || bad "first dev-stop.sh (see $tmp/stop1.log)"
  local api_l; api_l="$(port_listener_pid "$API_PORT")"
  [[ -z "$api_l" ]] && ok "api port $API_PORT released after stop" || bad "api port still held by $api_l"
  local web_l; web_l="$(port_listener_pid "$WEB_PORT")"
  [[ -z "$web_l" ]] && ok "web port $WEB_PORT released after stop" || bad "web port still held by $web_l"

  "$SCRIPT_DIR/dev-start.sh" >"$tmp/start2.log" 2>&1 || { bad "second dev-start.sh"; tail -n 20 "$tmp/start2.log"; return; }
  ok "second start"

  local read_back; read_back="$(curl -fsS "http://$API_HOST:$API_PORT/api/v1/projects/$pid_" \
    -H "Authorization: Bearer dev-alice" 2>/dev/null | jq -r '.id // empty')"
  expect_eq "project persisted across restart" "$read_back" "$pid_"

  if "$SCRIPT_DIR/dev-stop.sh" >"$tmp/stop2.log" 2>&1; then
    ok "final stop"
  else
    bad "final dev-stop.sh (see $tmp/stop2.log)"
    tail -n 30 "$tmp/stop2.log"
  fi

  # restore the caller's environment so later sections use normal ports
  unset TRACEMAP_RUNTIME_DIR TRACEMAP_API_PORT TRACEMAP_WEB_PORT
  source "$SCRIPT_DIR/dev-common.sh"
  set +e
  rm -rf -- "$tmp"
  RESTART_TMP=""
}

# ---------------------------------------------------------------------------
# live read-only checks against the dev stack
# ---------------------------------------------------------------------------
run_live_checks() {
  section "live dev stack: loopback binding and reachability"
  local pid state
  pid="$(read_pid "$API_PID_FILE")"; state="$(port_state "$API_PORT" "$pid")"
  if [[ "$state" != self ]] || ! pid_owned "$API_PID_FILE" "$pid" "tracemap.main:app"; then
    bad "api not owned on port $API_PORT (state=$state; run scripts/dev-start.sh)"
  else
    # Reject 0.0.0.0 exposure: only a 127.0.0.1 listener is acceptable.
    local bind; bind="$(ss -H -tlnp "sport = :$API_PORT" 2>/dev/null | awk '{print $4}')"
    if [[ "$bind" == 127.0.0.1:* ]]; then ok "api listening on loopback only ($bind)"; else bad "api bound to non-loopback address: '$bind'"; fi
    expect_eq "api /health" "$(curl -s -o /dev/null -w '%{http_code}' "http://$API_HOST:$API_PORT/health")" "200"
    expect_eq "api /docs" "$(curl -s -o /dev/null -w '%{http_code}' "http://$API_HOST:$API_PORT/docs")" "200"
    expect_eq "api /openapi.json" "$(curl -s -o /dev/null -w '%{http_code}' "http://$API_HOST:$API_PORT/openapi.json")" "200"
    expect_eq "unauthenticated 401" "$(curl -s -o /dev/null -w '%{http_code}' "http://$API_HOST:$API_PORT/api/v1/projects")" "401"
  fi

  pid="$(read_pid "$WEB_PID_FILE")"; state="$(port_state "$WEB_PORT" "$pid")"
  if [[ "$state" != self ]] || ! pid_owned "$WEB_PID_FILE" "$pid" "vite"; then
    bad "web not owned on port $WEB_PORT (state=$state; run scripts/dev-start.sh)"
  else
    local bind; bind="$(ss -H -tlnp "sport = :$WEB_PORT" 2>/dev/null | awk '{print $4}')"
    if [[ "$bind" == 127.0.0.1:* ]]; then ok "vite listening on loopback only ($bind)"; else bad "vite bound to non-loopback address: '$bind'"; fi
    expect_eq "vite index" "$(curl -s -o /dev/null -w '%{http_code}' "http://$WEB_HOST:$WEB_PORT/")" "200"
    expect_eq "vite /health proxy" "$(curl -s -o /dev/null -w '%{http_code}' "http://$WEB_HOST:$WEB_PORT/health")" "200"
    expect_eq "vite /api proxy (auth 200)" \
      "$(curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer dev-alice' "http://$WEB_HOST:$WEB_PORT/api/v1/projects")" "200"
  fi
}

# ---------------------------------------------------------------------------
# full workflow on a throwaway API (never touches the dev database)
# ---------------------------------------------------------------------------
run_workflow() {
  section "full API workflow on throwaway SQLite (isolated)"
  local tmp port pid base
  tmp="$(mktemp -d /tmp/tracemap-smoke.XXXXXX)"
  WORKFLOW_TMP="$tmp"
  port="$(pick_port)"
  [[ "$(port_state "$port")" == free ]] || { bad "throwaway port $port unexpectedly occupied"; return; }
  base="http://127.0.0.1:$port"
  TRACEMAP_ENV=development TRACEMAP_DOTENV=0 TRACEMAP_GENERATION_MODE=extractive \
  TRACEMAP_DATABASE_URL="sqlite:///$tmp/smoke.db" \
    "$API_PY" -m uvicorn tracemap.main:app --host 127.0.0.1 --port "$port" >>"$tmp/api.log" 2>&1 &
  pid=$!
  WORKFLOW_PID="$pid"
  if ! wait_for_http "$base/health" "$pid" 30; then
    bad "throwaway api failed to start"; tail -n 20 "$tmp/api.log"; kill "$pid" 2>/dev/null; rm -rf "$tmp"; return
  fi
  ok "throwaway api started on port $port (db $tmp/smoke.db)"

  local AUTH=(-H "Authorization: Bearer dev-alice")
  local code body pid_ rev sid para q
  json() { jq -r "$1"; }

  # unauthenticated
  code="$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/projects")"
  expect_eq "unauthenticated returns 401" "$code" "401"

  # create
  body="$(curl -s -X POST "$base/api/v1/projects" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: smoke-create-0001' -d '{"title":"冒烟研究","goal":"验证闭环"}')"
  pid_="$(printf '%s' "$body" | json '.id')"
  [[ -n "$pid_" && "$pid_" != null ]] && ok "created project" || bad "create project: $body"

  # idempotent replay of create
  body="$(curl -s -X POST "$base/api/v1/projects" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: smoke-create-0001' -d '{"title":"冒烟研究","goal":"验证闭环"}')"
  local replay_id; replay_id="$(printf '%s' "$body" | json '.id')"
  expect_eq "idempotent create returns same id" "$replay_id" "$pid_"
  local count; count="$(curl -s "$base/api/v1/projects" "${AUTH[@]}" | json '.items | length')"
  expect_eq "no duplicate project from idempotent replay" "$count" "1"

  # cross-user isolation
  code="$(curl -s -o /dev/null -w '%{http_code}' "$base/api/v1/projects/$pid_" -H 'Authorization: Bearer dev-bob')"
  expect_eq "cross-user project read returns 404" "$code" "404"

  # add text source
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/sources/text" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'If-Match: "rev-0"' -H 'Idempotency-Key: smoke-source-0001' \
    -d '{"title":"资料甲","text":"😀结论需要核验。\n\n第二段资料。","format":"text"}')"
  sid="$(printf '%s' "$body" | json '.sourceId')"; rev="$(printf '%s' "$body" | json '.revision')"
  [[ -n "$sid" && "$sid" != null ]] && ok "imported text source" || bad "add source: $body"
  expect_eq "revision after source" "$rev" "1"

  para="$(curl -s "$base/api/v1/projects/$pid_/sources/$sid/paragraphs" "${AUTH[@]}" | json '.items[0].id')"
  [[ -n "$para" && "$para" != null ]] && ok "read paragraphs" || bad "read paragraphs"

  # forged citation must be rejected and must not bump revision
  local root; root="$(curl -s "$base/api/v1/projects/$pid_/map" "${AUTH[@]}" | json '.rootId')"
  local fcode; fcode="$(curl -s -o "$tmp/forged.json" -w '%{http_code}' -X POST "$base/api/v1/projects/$pid_/nodes/ops" "${AUTH[@]}" \
    -H 'Content-Type: application/json' -H 'If-Match: "rev-1"' -H 'Idempotency-Key: smoke-forged-0002' \
    -d "{\"operations\":[{\"op\":\"add\",\"parentId\":\"$root\",\"node\":{\"type\":\"claim\",\"title\":\"伪造\",\"evidenceRefs\":[{\"sourceId\":\"$sid\",\"paragraphId\":\"$para\",\"start\":1,\"end\":3,\"exactQuote\":\"假话\"}]}}]}")"
  expect_eq "forged citation returns 422" "$fcode" "422"
  expect_eq "forged citation error code" "$(jq -r '.error.code' "$tmp/forged.json")" "QUOTE_ANCHOR_INVALID"

  # stale revision must conflict
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base/api/v1/projects/$pid_/nodes/ops" "${AUTH[@]}" \
    -H 'Content-Type: application/json' -H 'If-Match: "rev-0"' -H 'Idempotency-Key: smoke-stale-0001' \
    -d "{\"operations\":[{\"op\":\"rename\",\"nodeId\":\"$root\",\"title\":\"stale\"}]}")"
  expect_eq "stale revision returns 409" "$code" "409"

  # generate draft
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/generate" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'If-Match: "rev-1"' -H 'Idempotency-Key: smoke-generate-0001' \
    -d "{\"goal\":\"可信研究\",\"sourceIds\":[\"$sid\"],\"language\":\"zh-CN\"}")"
  local did mode; did="$(printf '%s' "$body" | json '.draftId')"; mode="$(printf '%s' "$body" | json '.generationMode')"
  [[ -n "$did" && "$did" != null ]] && ok "generated draft" || bad "generate: $body"
  expect_eq "generation mode is labelled demo" "$mode" "extractive_demo"

  # map must be unchanged until commit
  local nodes; nodes="$(curl -s "$base/api/v1/projects/$pid_/map" "${AUTH[@]}" | json '.nodes | length')"
  expect_eq "draft does not modify map" "$nodes" "1"

  # commit draft
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/generation-drafts/$did/commit" "${AUTH[@]}" \
    -H 'If-Match: "rev-1"' -H 'Idempotency-Key: smoke-commit-0001')"
  rev="$(printf '%s' "$body" | json '.revision')"
  expect_eq "commit advances revision" "$rev" "2"

  # rename newest node (idempotent)
  local target; target="$(curl -s "$base/api/v1/projects/$pid_/map" "${AUTH[@]}" | json '.nodes[-1].id')"
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/nodes/ops" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'If-Match: "rev-2"' -H 'Idempotency-Key: smoke-rename-0001' \
    -d "{\"operations\":[{\"op\":\"rename\",\"nodeId\":\"$target\",\"title\":\"人工重命名\"}]}")"
  rev="$(printf '%s' "$body" | json '.revision')"
  expect_eq "rename advances revision" "$rev" "3"
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/nodes/ops" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'If-Match: "rev-2"' -H 'Idempotency-Key: smoke-rename-0001' \
    -d "{\"operations\":[{\"op\":\"rename\",\"nodeId\":\"$target\",\"title\":\"人工重命名\"}]}")"
  rev="$(printf '%s' "$body" | json '.revision')"
  expect_eq "idempotent rename does not double-apply" "$rev" "3"

  # undo restores previous title, advances revision
  body="$(curl -s -X POST "$base/api/v1/projects/$pid_/undo" "${AUTH[@]}" -H 'If-Match: "rev-3"' -H 'Idempotency-Key: smoke-undo-0001')"
  rev="$(printf '%s' "$body" | json '.revision')"
  expect_eq "undo advances revision" "$rev" "4"

  # export md + json
  body="$(curl -s "$base/api/v1/projects/$pid_/export?format=md" "${AUTH[@]}")"
  # NOTE: committing a draft replaces the whole map, so the root heading is the
  # generation goal ("可信研究"), not the original project title. See gotchas GT-0007.
  if [[ "$body" == '<!-- TraceMap:'* && "$body" == *'可信研究'* ]]; then ok "markdown export contains map heading"; else bad "markdown export: ${body:0:80}"; fi
  body="$(curl -s "$base/api/v1/projects/$pid_/export?format=json" "${AUTH[@]}")"
  expect_eq "json export revision" "$(printf '%s' "$body" | json '.revision')" "4"

  # stop ephemeral api, verify port release
  kill "$pid" 2>/dev/null || true
  local i; for ((i=0;i<50;i++)); do pid_alive "$pid" || break; sleep 0.1; done
  pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
  [[ -z "$(port_listener_pid "$port")" ]] && ok "throwaway api port $port released" || bad "throwaway api port still held"
  rm -rf -- "$tmp"
  WORKFLOW_TMP=""
  WORKFLOW_PID=""
}

# ---------------------------------------------------------------------------
main() {
  echo "TraceMap smoke tests  ($(TS))"
  case "${1:-}" in
    --restart) run_restart_cycle ;;
    --live-only) run_live_checks ;;
    "") run_live_checks; run_workflow ;;
    *) echo "Usage: scripts/smoke-test.sh [--restart|--live-only]" >&2; return 2 ;;
  esac
  echo
  printf 'summary: %d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
  [[ "$FAIL" -eq 0 && "$SKIP" -eq 0 ]]
}

main "$@"
