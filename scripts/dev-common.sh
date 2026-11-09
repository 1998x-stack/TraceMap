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
umask 077  # Keep new runtime files (SQLite, logs, PID records) private.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
WEB_DIR="$REPO_ROOT/apps/web"

# Load the repository .env (single source of truth). Real environment variables and
# explicit per-command overrides always win; TRACEMAP_DOTENV=0 ignores the file.
if [[ "${TRACEMAP_DOTENV:-1}" != "0" ]]; then
  ENV_FILE="${TRACEMAP_ENV_FILE:-$REPO_ROOT/.env}"
  if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line#"${line%%[![:space:]]*}"}"          # left-trim
      if [[ -z "$line" ]]; then continue; fi
      if [[ "$line" == \#* ]]; then continue; fi
      if [[ "$line" == export\ * ]]; then line="${line#export }"; fi
      if [[ "$line" != *=* ]]; then continue; fi
      key="${line%%=*}"
      value="${line#*=}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then continue; fi
      # Match Python's parse_env(value.strip()) and never reinterpret quotes
      # around a value while preserving an explicitly exported empty variable.
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      if [[ ${#value} -ge 2 && "$value" == \"*\" && "$value" == *\" ]]; then value="${value:1:${#value}-2}"; fi
      if [[ ${#value} -ge 2 && "$value" == \'*\' && "$value" == *\' ]]; then value="${value:1:${#value}-2}"; fi
      if [[ ! -v "$key" ]]; then export "$key=$value"; fi
    done < "$ENV_FILE"
  fi
fi

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

ensure_dirs() {
  mkdir -p -- "$PID_DIR" "$LOG_DIR" "$DATA_DIR"
  # A previous deployment may have created the directories under umask 022.
  # Protect existing local SQLite and log files from other unprivileged users.
  chmod 700 -- "$RUNTIME_DIR" "$PID_DIR" "$LOG_DIR" "$DATA_DIR" ||
    fail "Cannot make TraceMap runtime directories private (0700)"
}

# Fail closed: no host override may make the insecure development stack public.
validate_dev_configuration() {
  [[ "$API_HOST" == 127.0.0.1 && "$WEB_HOST" == 127.0.0.1 ]] ||
    fail "DEV_BIND_UNSAFE: API and web must both bind 127.0.0.1 (not 0.0.0.0 or ::)"
  local port n
  for port in "$API_PORT" "$WEB_PORT"; do
    [[ "$port" =~ ^[0-9]{1,5}$ ]] || fail "Invalid port: $port"
    n=$((10#$port))
    (( n >= 1 && n <= 65535 )) || fail "Port out of range: $port"
  done
  (( 10#$API_PORT != 10#$WEB_PORT )) || fail "API and web ports must differ"
  [[ "$RUNTIME_DIR" == /* && "$RUNTIME_DIR" != *$'\n'* ]] ||
    fail "Runtime directory must be an absolute, single-line path"
  [[ "$API_DB_URL" == sqlite:////* && "$API_DB_URL" != *$'\n'* ]] ||
    fail "Database URL must be an absolute SQLite URL (sqlite:////path/to/file.db)"
}

pid_start_ticks() {
  local pid="$1"
  [[ -r "/proc/$pid/stat" ]] || return 1
  # Fields 1+2 contain PID and a parenthesized process name. Strip them before
  # reading the 20th remaining field (Linux proc stat field 22, starttime).
  local stat
  IFS= read -r stat < "/proc/$pid/stat" || return 1
  stat="${stat##*) }"
  local -a fields
  read -r -a fields <<< "$stat"
  [[ "${fields[19]:-}" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "${fields[19]}"
}

pid_owned() {
  local pid_file="$1" pid="$2" signature="$3" saved_pid saved_ticks actual
  [[ -f "$pid_file" ]] || return 1
  read -r saved_pid saved_ticks < "$pid_file" || return 1
  [[ "$saved_pid" == "$pid" && "$saved_ticks" =~ ^[0-9]+$ ]] || return 1
  pid_alive "$pid" || return 1
  actual="$(pid_start_ticks "$pid")" || return 1
  [[ "$actual" == "$saved_ticks" ]] || return 1
  [[ "$(cmdline_of "$pid")" == *"$signature"* ]]
}


pid_alive() {
  [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null || return 1
  # Reaped-or-unreaped zombies are not running services.
  [[ "$(awk '{print $3}' "/proc/$1/stat" 2>/dev/null)" != Z ]]
}

read_pid() {
  local file="$1" pid start
  [[ -f "$file" ]] || return 0
  read -r pid start < "$file" || return 0
  [[ "$pid" =~ ^[0-9]+$ ]] && printf '%s' "$pid" || true
}

cmdline_of() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null || true; }

# A listener with an inaccessible PID is occupied, not free.
port_listener_pid() {
  local port="$1"
  ss -H -tlnp "sport = :$port" 2>/dev/null |
    grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2 || true
}

# "free" | "self" | "other" | "unknown"
port_state() {
  local port="$1" expected_pid="${2:-}" lines actual
  command -v ss >/dev/null 2>&1 || { echo unknown; return; }
  lines="$(ss -H -tlnp "sport = :$port" 2>/dev/null)" || { echo unknown; return; }
  [[ -n "$lines" ]] || { echo free; return; }
  actual="$(printf '%s\n' "$lines" | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2 || true)"
  # All listeners for this port must be loopback; 'ss' may hide process owners.
  if [[ -n "$expected_pid" && "$actual" == "$expected_pid" ]] &&
    ! printf '%s\n' "$lines" | awk '{print $4}' |
      grep -Ev "^127\\.0\\.0\\.1:$port\$" >/dev/null; then
    echo self
  else
    echo other
  fi
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
  # fd 9 is the lifecycle lock; do not let the daemon inherit it.
  nohup "$@" 9>&- >> "$log_file" 2>&1 &
  local pid=$! ticks
  ticks="$(pid_start_ticks "$pid")" || fail "$name: unable to record PID generation"
  printf '%s %s\n' "$pid" "$ticks" > "$pid_file"
  echo "$pid"
}

# stop_service NAME PID_FILE LOG_FILE PORT CMD_MATCH [GRACE_SECONDS]
# Returns 0 if stopped or already stopped, 1 on refusal (unrelated process).
stop_service() {
  local name="$1" pid_file="$2" port="$3" match="$4" grace="${5:-10}"
  local pid cmd i
  pid="$(read_pid "$pid_file")"

  if [[ -z "$pid" ]]; then
    if [[ "$(port_state "$port")" != free ]]; then
      warn "$name: port $port is occupied without an owned PID record; refusing"
      return 1
    fi
    return 0
  fi
  if ! pid_alive "$pid"; then
    warn "$name: stale PID file (PID $pid not running); removing"
    rm -f "$pid_file"
    [[ "$(port_state "$port")" == free ]]
    return
  fi
  if ! pid_owned "$pid_file" "$pid" "$match"; then
    warn "$name: refusing to signal PID $pid: starttime or command signature mismatches PID record"
    return 1
  fi
  cmd="$(cmdline_of "$pid")"

  info "$name: stopping PID $pid"
  kill "$pid" 2>/dev/null || true
  for ((i = 0; i < grace * 10; i++)); do
    pid_alive "$pid" || break
    sleep 0.1
  done
  if pid_alive "$pid"; then
    if ! pid_owned "$pid_file" "$pid" "$match"; then
      warn "$name: PID changed identity while stopping; refusing SIGKILL"
      return 1
    fi
    warn "$name: PID $pid did not exit gracefully; sending SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$pid_file"

  if [[ "$(port_state "$port")" != free ]]; then
    warn "$name: port $port remains occupied (or listener state is unknown)"
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
