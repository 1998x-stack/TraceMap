#!/usr/bin/env bash
# Stop the local TraceMap development stack. Only processes whose recorded PID
# still matches the expected command line are terminated; anything else is
# reported and left running.
#
# Usage: scripts/dev-stop.sh
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev-common.sh"

validate_dev_configuration
command -v ss >/dev/null || fail "ss (iproute2) is required to check listeners safely"
command -v flock >/dev/null || fail "flock is required for race-safe service lifecycle commands"
ensure_dirs
exec 9> "$PID_DIR/.lifecycle.lock"
flock -n 9 || fail "Another TraceMap lifecycle command is running"

overall=0

stop_service web "$WEB_PID_FILE" "$WEB_PORT" "vite" || overall=1
stop_service api "$API_PID_FILE" "$API_PORT" "tracemap.main:app" || overall=1

if [[ "$overall" -eq 0 ]]; then
  info "all TraceMap dev services stopped"
else
  warn "one or more services could not be stopped cleanly (see WARN lines above)"
fi
exit "$overall"
