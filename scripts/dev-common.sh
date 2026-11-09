#!/usr/bin/env bash
# Shared helpers for the local TraceMap development scripts.
#
# Source this file (do not execute it directly):
#     source "$(dirname "$0")/dev-common.sh"
#
# Design rules:
#   * Paths are derived from the repository location, so every script works from
#     any current working directory.
#   * Runtime state (PID / log / SQLite) lives OUTSIDE the repository, under
#     $TRACEMAP_RUNTIME_DIR (default: $HOME/tracemap-runtime), so a checkout,
#     `git clean` or branch switch can never destroy research data.
#   * All services bind to loopback only and use an ABSOLUTE SQLite path. Never
#     rely on the relative `sqlite:///./tracemap-dev.db` default (see
#     docs/gotchas.md GT-0002): it depends on the process working directory.
#   * The scripts refuse to kill a PID whose command line does not match the
#     expected component, so they cannot terminate an unrelated process.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
WEB_DIR="$REPO_ROOT/apps/web"

RUNTIME_DIR="${TRACEMAP_RUNTIME_DIR:-$HOME/tracemap-runtime}"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"
DATA_DIR="$RUNTIME_DIR/data"

API_HOST="${TRACEMAP_API_HOST:-127.0.0.1}"
API_PORT="${TRACEMAP_API_PORT:-8000}"
WEB_HOST="${TRACEMAP_WEB_HOST:-127.0.0.1}"
WEB_PORT="${TRACEMAP_WEB_PORT:-5173}"

API_DB_PATH="$DATA_DIR/tracemap-dev.db"
# Explicit absolute URL; overridable for throwaway/isolated runs.
API_DB_URL="${TRACEMAP_DATABASE_URL:-sqlite:///$API_DB_PATH}"

API_PID_FILE="$PID_DIR/api.pid"
WEB_PID_FILE="$PID_DIR/web.pid"
API_LOG="$LOG_DIR/api.log"
WEB_LOG="$LOG_DIR/web.log"

API_PY="$API_DIR/.venv/bin/python"
WEB_VITE="$WEB_DIR/node_modules/.bin/vite"

TS() { date '+%Y-%m-%d %H:%M:%S%z'; }
info() { printf '%s [tracemap] %s\n' "$(TS)" "$*"; }
warn() { printf '%s [tracemap] WARN %s\n' "$(TS)" "$*" >&2; }
fail() { printf '%s [tracemap] ERROR %s\n' "$(TS)" "$*" >&2; exit 1; }

ensure_dirs() { mkdir -p "$PID_DIR" "$LOG_DIR" "$DATA_DIR"; }

pid_alive() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

read_pid() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  tr -dc '0-9' < "$file" 2>/dev/null || true
}

cmdline_of() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null || true; }

# PID currently LISTENing on a TCP port (empty if none).
port_listener_pid() {
  local port="$1"
  ss -H -tlnp "sport = :$port" 2>/dev/null \
    | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2 || true
}

# "free" | "self" | "other" for a port given the PID we recorded for it.
port_state() {
  local port="$1" expected_pid="${2:-}" actual
  actual="$(port_listener_pid "$port")"
  if [[ -z "$actual" ]]; then echo free; return; fi
  if [[ -n "$expected_pid" && "$actual" == "$expected_pid" ]]; then echo self; else echo other; fi
}

# wait_for_http URL PID TIMEOUT_SECONDS -> 0 ok, 1 timeout, 2 process died
wait_for_http() {
  local url="$1" pid="$2" timeout="${3:-30}" i
  for ((i = 0; i < timeout * 10; i++)); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
    if ! pid_alive "$pid"; then return 2; fi
    sleep 0.1
  done
  return 1
}

# start_service NAME PID_FILE LOG_FILE PORT CMD...
start_service() {
  local name="$1" pid_file="$2" log_file="$3" port="$4"; shift 4
  ensure_dirs
  {
    printf '\n===== %s | start %s | port %s =====\n' "$(TS)" "$name" "$port"
  } >> "$log_file"
  nohup "$@" >> "$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"
  echo "$pid"
}

# stop_service NAME PID_FILE LOG_FILE PORT CMD_MATCH [GRACE_SECONDS]
# Returns 0 if stopped or already stopped, 1 on refusal (unrelated process).
stop_service() {
  local name="$1" pid_file="$2" port="$3" match="$4" grace="${5:-10}"
  local pid cmd i
  pid="$(read_pid "$pid_file")"

  if [[ -z "$pid" ]]; then
    local other; other="$(port_listener_pid "$port")"
    [[ -n "$other" ]] && warn "$name: no PID file but port $port held by PID $other ($(cmdline_of "$other"))"
    return 0
  fi
  if ! pid_alive "$pid"; then
    warn "$name: stale PID file (PID $pid not running); removing"
    rm -f "$pid_file"
    return 1
  fi
  cmd="$(cmdline_of "$pid")"
  if [[ "$cmd" != *"$match"* ]]; then
    warn "$name: refusing to stop PID $pid — command line does not contain '$match': $cmd"
    return 1
  fi

  info "$name: stopping PID $pid"
  kill "$pid" 2>/dev/null || true
  for ((i = 0; i < grace * 10; i++)); do
    pid_alive "$pid" || break
    sleep 0.1
  done
  if pid_alive "$pid"; then
    warn "$name: PID $pid did not exit gracefully; sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$pid_file"

  local other; other="$(port_listener_pid "$port")"
  if [[ -n "$other" ]]; then
    warn "$name: port $port still held by PID $other ($(cmdline_of "$other"))"
    return 1
  fi
  info "$name: stopped, port $port released"
  return 0
}

print_health() {
  local label="$1" url="$2" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null)"
  printf '  %-8s %-42s HTTP %s\n' "$label" "$url" "${code:-000}"
}
