#!/usr/bin/env bash
# Stop the local TraceMap development stack. Only processes whose recorded PID
# still matches the expected command line are terminated; anything else is
# reported and left running.
#
# Usage: scripts/dev-stop.sh
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/dev-common.sh"

overall=0

stop_service web "$WEB_PID_FILE" "$WEB_PORT" "vite" || overall=1
stop_service api "$API_PID_FILE" "$API_PORT" "uvicorn" || overall=1

if [[ "$overall" -eq 0 ]]; then
  info "all TraceMap dev services stopped"
else
  warn "one or more services could not be stopped cleanly (see WARN lines above)"
fi
exit "$overall"
