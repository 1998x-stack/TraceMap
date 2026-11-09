#!/usr/bin/env bash
# Start the local TraceMap development stack (API on 127.0.0.1:8000,
# Vite dev server on 127.0.0.1:5173). Safe to run repeatedly: if a component is
# already running it is left untouched instead of being duplicated.
#
# Usage: scripts/dev-start.sh
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev-common.sh"

ensure_dirs

# ---- prerequisites ---------------------------------------------------------
[[ -x "$API_PY" ]] || fail "backend venv missing at $API_PY
  Create it with:  cd apps/api && uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'"
[[ -f "$WEB_VITE" ]] || fail "frontend dependencies missing at $WEB_DIR/node_modules
  Install them with:  cd apps/web && npm ci"

command -v curl >/dev/null || fail "curl is required for health checks"

info "runtime dir : $RUNTIME_DIR"
info "sqlite      : $API_DB_URL"

# ---- API -------------------------------------------------------------------
api_pid="$(read_pid "$API_PID_FILE")"
case "$(port_state "$API_PORT" "$api_pid")" in
  self)
    info "api: already running (PID $api_pid on $API_HOST:$API_PORT) — not starting a duplicate"
    ;;
  other)
    other="$(port_listener_pid "$API_PORT")"
    fail "api: port $API_PORT already in use by PID $other ($(cmdline_of "$other"))"
    ;;
  free)
    [[ -n "$api_pid" ]] && info "api: removing stale PID file ($api_pid not running)"
    api_pid="$(start_service api "$API_PID_FILE" "$API_LOG" "$API_PORT" \
      env TRACEMAP_ENV=development TRACEMAP_DATABASE_URL="$API_DB_URL" \
      "$API_PY" -m uvicorn tracemap.main:app --host "$API_HOST" --port "$API_PORT")"
    info "api: started PID $api_pid; waiting for http://$API_HOST:$API_PORT/health"
    if wait_for_http "http://$API_HOST:$API_PORT/health" "$api_pid" 30; then
      info "api: healthy"
    else
      rc=$?
      warn "api: failed to become healthy (rc=$rc). Recent log ($API_LOG):"
      tail -n 25 "$API_LOG" >&2 || true
      fail "api did not start; not starting the web server"
    fi
    ;;
esac

# ---- Web -------------------------------------------------------------------
web_pid="$(read_pid "$WEB_PID_FILE")"
case "$(port_state "$WEB_PORT" "$web_pid")" in
  self)
    info "web: already running (PID $web_pid on $WEB_HOST:$WEB_PORT) — not starting a duplicate"
    ;;
  other)
    other="$(port_listener_pid "$WEB_PORT")"
    fail "web: port $WEB_PORT already in use by PID $other ($(cmdline_of "$other"))"
    ;;
  free)
    [[ -n "$web_pid" ]] && info "web: removing stale PID file ($web_pid not running)"
    # Invoke vite directly (identical to `npm run dev`) so the recorded PID is
    # the actual server process; TRACEMAP_PROXY_TARGET keeps /api pointed at the
    # API we just verified.
    web_pid="$(start_service web "$WEB_PID_FILE" "$WEB_LOG" "$WEB_PORT" \
      env TRACEMAP_PROXY_TARGET="http://$API_HOST:$API_PORT" \
      "$WEB_VITE" "$WEB_DIR" --host "$WEB_HOST" --port "$WEB_PORT" --strictPort)"
    info "web: started PID $web_pid; waiting for http://$WEB_HOST:$WEB_PORT"
    if wait_for_http "http://$WEB_HOST:$WEB_PORT/" "$web_pid" 30; then
      info "web: ready"
    else
      rc=$?
      warn "web: failed to become ready (rc=$rc). Recent log ($WEB_LOG):"
      tail -n 25 "$WEB_LOG" >&2 || true
      fail "web did not start"
    fi
    ;;
esac

echo
info "TraceMap is up:"
printf '  frontend : http://%s:%s\n' "$WEB_HOST" "$WEB_PORT"
printf '  api docs : http://%s:%s/docs\n' "$API_HOST" "$API_PORT"
printf '  health   : '
printf '%s\n' "$(curl -fsS "http://$API_HOST:$API_PORT/health" 2>/dev/null || echo unreachable)"
printf '  logs     : %s\n' "$LOG_DIR"
printf '  stop     : %s\n' "$REPO_ROOT/scripts/dev-stop.sh"
