#!/usr/bin/env bash
# Report the state of the local TraceMap development stack.
#
# Usage: scripts/dev-status.sh
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev-common.sh"

echo "TraceMap dev status  ($(TS))"
echo "  repo      : $REPO_ROOT"
echo "  runtime   : $RUNTIME_DIR"
echo "  sqlite    : $API_DB_URL"

component() {
  local name="$1" pid_file="$2" port="$3" host="$4"
  local pid state cmd
  pid="$(read_pid "$pid_file")"
  state="$(port_state "$port" "$pid")"
  printf '\n[%s] port %s:%s  listener=%s  ' "$name" "$host" "$port" "$state"
  if [[ -n "$pid" ]] && pid_alive "$pid"; then
    cmd="$(cmdline_of "$pid")"
    printf 'PID=%s alive\n      cmd: %s\n' "$pid" "${cmd:0:160}"
  else
    printf 'PID=%s (not running)\n' "${pid:-none}"
  fi
}

component api "$API_PID_FILE" "$API_PORT" "$API_HOST"
component web "$WEB_PID_FILE" "$WEB_PORT" "$WEB_HOST"

echo
echo "health:"
print_health api "http://$API_HOST:$API_PORT/health"
print_health docs "http://$API_HOST:$API_PORT/docs"
print_health web "http://$WEB_HOST:$WEB_PORT/"

if [[ -f "$API_DB_PATH" ]]; then
  printf '\nsqlite: %s (%s bytes)\n' "$API_DB_PATH" "$(stat -c '%s' "$API_DB_PATH")"
else
  printf '\nsqlite: %s (not created yet)\n' "$API_DB_PATH"
fi

echo
echo "recent api log:"; tail -n 8 "$API_LOG" 2>/dev/null || echo "  (none)"
echo "recent web log:"; tail -n 8 "$WEB_LOG" 2>/dev/null || echo "  (none)"
