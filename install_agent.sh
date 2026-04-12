#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.74"

APP_DIR="/opt/sahar-agent"
APP_APP_DIR="$APP_DIR/app"
APP_DATA_DIR="$APP_DIR/data"
APP_LOG_DIR="$APP_DIR/logs"
APP_BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"
API_SERVICE_NAME="sahar-agent"
XRAY_CONFIG_PATH="/usr/local/etc/xray/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_STATE_DIR="$APP_DATA_DIR/.installer-state"
CACHE_DIR="/var/cache/sahar"
PIP_CACHE_DIR="$CACHE_DIR/pip"
WHEELHOUSE_DIR="$CACHE_DIR/wheelhouse/agent"

LOG_FILE="/tmp/sahar-agent-installer.log"
STATUS_FILE="/tmp/sahar-agent-installer.status"
TOTAL_STEPS=12
CURRENT_STEP=0
STEP_PROGRESS=0
STEP_PROGRESS_CEILING=0
STEP_PROGRESS_STARTED_AT=0
BAR_WIDTH=40
CURRENT_LABEL="Preparing installer"
CURRENT_STATUS="Waiting"
CURRENT_SPINNER="-"
SPINNER_INDEX=0
UI_TTY=0
FAIL_HINT=""
POST_INSTALL_WARNINGS=()
C_RESET=""
C_BOLD=""
C_DIM=""
C_GREEN=""
C_CYAN=""
C_YELLOW=""
C_RED=""
OS_ID=""
OS_VERSION_ID=""
OS_PRETTY_NAME=""
OS_FAMILY=""
INIT_SYSTEM=""
XRAY_VERSION="26.1.13"

setup_ui() {
  : > "$LOG_FILE"
  : > "$STATUS_FILE"
  if [[ -t 1 && "${TERM:-}" != "dumb" ]]; then
    UI_TTY=1
    C_RESET=$'[0m'
    C_BOLD=$'[1m'
    C_DIM=$'[2m'
    C_GREEN=$'[32m'
    C_CYAN=$'[36m'
    C_YELLOW=$'[33m'
    C_RED=$'[31m'
    printf '[?25l'
    trap cleanup_ui EXIT
  fi
}

cleanup_ui() {
  if (( UI_TTY )); then
    printf '[?25h'
  fi
}

advance_spinner() {
  case $((SPINNER_INDEX % 4)) in
    0) CURRENT_SPINNER='|' ;;
    1) CURRENT_SPINNER='/' ;;
    2) CURRENT_SPINNER='-' ;;
    3) CURRENT_SPINNER='\' ;;
  esac
  SPINNER_INDEX=$((SPINNER_INDEX + 1))
}

clamp_percent() {
  local value="${1:-0}"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    value=0
  fi
  if (( value < 0 )); then
    value=0
  elif (( value > 100 )); then
    value=100
  fi
  printf '%s' "$value"
}

reset_step_progress() {
  STEP_PROGRESS=0
  STEP_PROGRESS_CEILING=0
  STEP_PROGRESS_STARTED_AT=$(date +%s)
}

set_step_progress() {
  local value
  value="$(clamp_percent "${1:-0}")"
  STEP_PROGRESS="$value"
  STEP_PROGRESS_CEILING="$value"
  STEP_PROGRESS_STARTED_AT=$(date +%s)
  if [[ $# -ge 2 && -n "${2:-}" ]]; then
    status_note "$2"
  fi
}

begin_step_phase() {
  local start cap
  start="$(clamp_percent "${1:-0}")"
  cap="$(clamp_percent "${2:-${1:-0}}")"
  if (( cap < start )); then
    cap=$start
  fi
  STEP_PROGRESS="$start"
  STEP_PROGRESS_CEILING="$cap"
  STEP_PROGRESS_STARTED_AT=$(date +%s)
  if [[ $# -ge 3 && -n "${3:-}" ]]; then
    status_note "$3"
  fi
}

effective_step_progress() {
  local visible elapsed auto
  visible="$STEP_PROGRESS"
  if (( STEP_PROGRESS_CEILING > STEP_PROGRESS )); then
    elapsed=$(( $(date +%s) - STEP_PROGRESS_STARTED_AT ))
    auto=$((STEP_PROGRESS + elapsed / 4))
    if (( auto >= STEP_PROGRESS_CEILING )); then
      auto=$((STEP_PROGRESS_CEILING - 1))
    fi
    if (( auto > visible )); then
      visible=$auto
    fi
  fi
  printf '%s' "$visible"
}

progress_bar() {
  local step_percent overall_percent done_slots pending_slots fill empty
  step_percent="$(effective_step_progress)"
  overall_percent=$(((CURRENT_STEP * 100 + step_percent) / TOTAL_STEPS))
  done_slots=$((overall_percent * BAR_WIDTH / 100))
  pending_slots=$((BAR_WIDTH - done_slots))
  fill=$(printf '%*s' "$done_slots" '')
  fill=${fill// /=}
  empty=$(printf '%*s' "$pending_slots" '')
  printf '%s%s' "$fill" "$empty"
}

draw_screen() {
  local percent step_no bar
  (( UI_TTY )) || return 0
  percent=$(((CURRENT_STEP * 100 + $(effective_step_progress)) / TOTAL_STEPS))
  step_no=$((CURRENT_STEP + 1))
  if (( step_no > TOTAL_STEPS )); then
    step_no=$TOTAL_STEPS
  fi
  bar="$(progress_bar)"
  printf '[H[2J'
  printf '%s%sSahar Agent Installer v%s%s
' "$C_BOLD" "$C_CYAN" "$APP_VERSION" "$C_RESET"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  printf ' %sMode%s        Agent
' "$C_DIM" "$C_RESET"
  printf ' %sSystem%s      %s
' "$C_DIM" "$C_RESET" "${OS_PRETTY_NAME:-Detecting...}"
  printf ' %sInit%s        %s
' "$C_DIM" "$C_RESET" "${INIT_SYSTEM:-Detecting...}"
  printf ' %sStep%s        %d/%d
' "$C_DIM" "$C_RESET" "$step_no" "$TOTAL_STEPS"
  printf ' %sStage%s       %s
' "$C_DIM" "$C_RESET" "$CURRENT_LABEL"
  printf ' %sStatus%s      %s
' "$C_DIM" "$C_RESET" "$CURRENT_STATUS"
  printf ' %sLog%s         %s

' "$C_DIM" "$C_RESET" "$LOG_FILE"
  printf ' %sProgress%s    [%s%s%s] %s%3d%%%s

' "$C_DIM" "$C_RESET" "$C_GREEN" "$bar" "$C_RESET" "$C_BOLD" "$percent" "$C_RESET"
  printf '%sAgent setup runs silently with defaults and keeps package output hidden.%s
' "$C_YELLOW" "$C_RESET"
  printf '%sPython environment shows cache and wheel activity live.%s
' "$C_DIM" "$C_RESET"
}
ui_newline() {
  printf '\n'
}

status_note() {
  local message="${1:-}"
  printf '%s\n' "$message" > "$STATUS_FILE"
  printf 'STATUS: %s\n' "$message" >> "$LOG_FILE"
}

current_step_status() {
  if [[ -s "$STATUS_FILE" ]]; then
    tail -n 1 "$STATUS_FILE" 2>/dev/null || true
  fi
}

spinner_loop() {
  local start_ts elapsed step_note
  start_ts=$(date +%s)
  while true; do
    elapsed=$(( $(date +%s) - start_ts ))
    advance_spinner
    step_note="$(current_step_status)"
    if [[ -n "$step_note" ]]; then
      CURRENT_STATUS="Running ${CURRENT_SPINNER}  ${elapsed}s · ${step_note}"
    else
      CURRENT_STATUS="Running ${CURRENT_SPINNER}  ${elapsed}s"
    fi
    draw_screen
    sleep 0.12
  done
}


set_fail_hint() {
  FAIL_HINT="$1"
}

clear_fail_hint() {
  FAIL_HINT=""
}

append_post_install_warning() {
  local message="${1:-}"
  [[ -n "$message" ]] || return 0
  POST_INSTALL_WARNINGS+=("$message")
  printf 'WARNING: %s
' "$message" >> "$LOG_FILE"
}

tcp_target_host() {
  local host="${1:-}"
  case "$host" in
    ''|0.0.0.0|::|[::]|localhost) printf '%s' '127.0.0.1' ;;
    *) printf '%s' "$host" ;;
  esac
}

tcp_connect_check() {
  local host port timeout_s
  host="$1"
  port="$2"
  timeout_s="${3:-3}"
  if command_exists python3; then
    python3 - "$host" "$port" "$timeout_s" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
timeout_s = float(sys.argv[3])
try:
    with socket.create_connection((host, port), timeout=timeout_s):
        pass
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
    return $?
  fi
  if command_exists nc; then
    nc -z -w "$timeout_s" "$host" "$port" >/dev/null 2>&1
    return $?
  fi
  if command_exists timeout; then
    if timeout_supports_foreground; then
      timeout --foreground "$timeout_s" bash -lc "exec 3<>/dev/tcp/${host}/${port}; exec 3<&-; exec 3>&-" >/dev/null 2>&1
    else
      timeout "$timeout_s" bash -lc "exec 3<>/dev/tcp/${host}/${port}; exec 3<&-; exec 3>&-" >/dev/null 2>&1
    fi
    return $?
  fi
  bash -lc "exec 3<>/dev/tcp/${host}/${port}; exec 3<&-; exec 3>&-" >/dev/null 2>&1
}

wait_for_tcp_listener() {
  local host port attempts delay target_host
  host="$1"
  port="$2"
  attempts="${3:-30}"
  delay="${4:-2}"
  target_host="$(tcp_target_host "$host")"
  for ((i=1; i<=attempts; i++)); do
    status_note "Waiting for ${target_host}:${port} to accept TCP connections (${i}/${attempts})"
    if tcp_connect_check "$target_host" "$port" 3; then
      return 0
    fi
    sleep "$delay"
  done
  set_fail_hint "Timed out waiting for ${target_host}:${port} to accept TCP connections"
  return 1
}

assert_runtime_tools() {
  local missing=()
  [[ -x "$VENV_DIR/bin/python" ]] || missing+=("python")
  [[ -x "$VENV_DIR/bin/pip" ]] || missing+=("pip")
  [[ -x "$VENV_DIR/bin/gunicorn" ]] || missing+=("gunicorn")
  if (( ${#missing[@]} > 0 )); then
    set_fail_hint "Python environment is incomplete: missing ${missing[*]}"
    return 1
  fi
}

timeout_supports_foreground() {
  if ! command_exists timeout; then
    return 1
  fi
  timeout --help 2>&1 | grep -q -- '--foreground'
}

run_with_timeout() {
  local timeout_s="$1" rc
  shift
  if command_exists timeout; then
    if timeout_supports_foreground; then
      timeout --foreground "$timeout_s" "$@"
    else
      timeout "$timeout_s" "$@"
    fi
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
      if [[ "$rc" -eq 124 ]]; then
        set_fail_hint "Timed out after ${timeout_s}s"
        printf 'timeout after %ss: %s
' "$timeout_s" "$*" >> "$LOG_FILE"
      fi
      return "$rc"
    fi
    return 0
  fi
  "$@"
}
run_step() {
  local label="$1" spinner_pid
  shift
  CURRENT_LABEL="$label"
  clear_fail_hint
  reset_step_progress
  : > "$STATUS_FILE"
  if (( UI_TTY )); then
    spinner_loop &
    spinner_pid=$!
    if ! "$@" >>"$LOG_FILE" 2>&1; then
      kill "$spinner_pid" 2>/dev/null || true
      wait "$spinner_pid" 2>/dev/null || true
      ui_fail "$label"
    fi
    kill "$spinner_pid" 2>/dev/null || true
    wait "$spinner_pid" 2>/dev/null || true
  else
    printf '[%d/%d] %s
' "$((CURRENT_STEP + 1))" "$TOTAL_STEPS" "$label"
    if ! "$@" >>"$LOG_FILE" 2>&1; then
      ui_fail "$label"
    fi
  fi
  set_step_progress 100
  : > "$STATUS_FILE"
  CURRENT_STEP=$((CURRENT_STEP + 1))
  reset_step_progress
  CURRENT_STATUS="Completed"
  draw_screen
}

ui_fail() {
  local label="$1"
  CURRENT_STATUS="Failed"
  draw_screen
  ui_newline
  printf '%sInstallation failed.%s
' "$C_RED" "$C_RESET" >&2
  printf 'Step: %s
' "$label" >&2
  if [[ -n "$FAIL_HINT" ]]; then
    printf 'Reason: %s
' "$FAIL_HINT" >&2
  fi
  printf 'Details: %s
' "$LOG_FILE" >&2
  if [[ -s "$LOG_FILE" ]]; then
    printf '
Last log lines:
' >&2
    tail -n 20 "$LOG_FILE" >&2 || true
  fi
  exit 1
}

print_banner() {
  CURRENT_STATUS="Ready"
  draw_screen
}


require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must be run as root"
    exit 1
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

file_sha256() {
  sha256sum "$1" | awk '{print $1}'
}

detect_platform() {
  if [[ ! -r /etc/os-release ]]; then
    echo "Unsupported Linux distribution: /etc/os-release not found"
    exit 1
  fi

  # shellcheck disable=SC1091
  . /etc/os-release

  OS_ID="${ID:-unknown}"
  OS_VERSION_ID="${VERSION_ID:-unknown}"
  OS_PRETTY_NAME="${PRETTY_NAME:-unknown}"

  case "$OS_ID" in
    alpine)
      OS_FAMILY="alpine"
      ;;
    ubuntu|debian)
      OS_FAMILY="debian"
      ;;
    *)
      case "${ID_LIKE:-}" in
        *debian*|*ubuntu*)
          OS_FAMILY="debian"
          ;;
        *)
          echo "Unsupported Linux distribution: ${OS_PRETTY_NAME}"
          echo "Supported families: Alpine, Debian, Ubuntu"
          exit 1
          ;;
      esac
      ;;
  esac

  if command_exists systemctl; then
    INIT_SYSTEM="systemd"
  elif command_exists rc-service; then
    INIT_SYSTEM="openrc"
  else
    INIT_SYSTEM="unknown"
  fi
}

check_os() {
  detect_platform
}

preflight_checks() {
  mkdir -p "$INSTALLER_STATE_DIR" "$PIP_CACHE_DIR" "$WHEELHOUSE_DIR"
}


detect_ssh_client_ip() {
  if [[ -n "${SSH_CLIENT:-}" ]]; then
    echo "${SSH_CLIENT%% *}"
    return
  fi
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    echo "${SSH_CONNECTION%% *}"
    return
  fi
}

normalize_allowed_sources() {
  local raw="${1:-}"
  if [[ "$raw" == "ANY" || "$raw" == "any" || "$raw" == "Any" || "$raw" == "*" ]]; then
    echo "*"
  else
    echo "$raw"
  fi
}

resolve_host_ready() {
  local host="$1"
  if command -v getent >/dev/null 2>&1 && getent hosts "$host" >/dev/null 2>&1; then
    return 0
  fi
  if command -v nslookup >/dev/null 2>&1 && nslookup "$host" >/dev/null 2>&1; then
    return 0
  fi
  if command -v dig >/dev/null 2>&1 && [[ -n "$(dig +short "$host" | head -n1)" ]]; then
    return 0
  fi
  return 1
}

parse_bool() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|on|ON|On) echo "true" ;;
    *) echo "false" ;;
  esac
}

install_packages() {
  local need_install=0
  if [[ "$OS_FAMILY" == "debian" ]]; then
    for cmd in python3 pip3 curl jq git unzip openssl; do
      if ! command_exists "$cmd"; then
        need_install=1
        break
      fi
    done
    if [[ $need_install -eq 0 ]]; then
      set_step_progress 100 "System packages already available"
      return 0
    fi
    begin_step_phase 10 28 "Refreshing package metadata"
    run_with_timeout 300 apt update
    begin_step_phase 34 82 "Installing system packages"
    run_with_timeout 900 apt install -y python3 python3-venv python3-pip curl jq uuid-runtime ca-certificates dnsutils tar unzip logrotate git openssl
  else
    for cmd in python3 pip3 curl jq git unzip gcc openssl; do
      if ! command_exists "$cmd"; then
        need_install=1
        break
      fi
    done
    if [[ $need_install -eq 0 ]]; then
      set_step_progress 100 "System packages already available"
      return 0
    fi
    begin_step_phase 18 86 "Installing Alpine system packages"
    run_with_timeout 1200 apk add --no-cache bash python3 py3-pip py3-virtualenv curl jq uuidgen ca-certificates bind-tools tar unzip logrotate build-base python3-dev musl-dev linux-headers git openssl
  fi
  begin_step_phase 88 96 "Verifying installed commands"
  for cmd in python3 pip3 curl jq git unzip openssl; do
    if ! command_exists "$cmd"; then
      set_fail_hint "Required command missing after package install: $cmd"
      return 1
    fi
  done
  set_step_progress 100 "System packages are ready"
}


infer_host_mode() {
  local host="$1"
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ip"
  else
    echo "domain"
  fi
}

detect_public_ipv4() {
  local ip=""
  for url in \
    "https://api.ipify.org" \
    "https://ipv4.icanhazip.com" \
    "https://ifconfig.me/ip"; do
    ip="$(curl -4fsS --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "$ip"
      return 0
    fi
  done
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}' || true)"
    if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "$ip"
      return 0
    fi
  fi
  return 1
}

default_public_host() {
  local detected
  detected="${PUBLIC_HOST:-}"
  if [[ -n "$detected" ]]; then
    echo "$detected"
    return 0
  fi
  detected="$(detect_public_ipv4 || true)"
  if [[ -n "$detected" ]]; then
    echo "$detected"
    return 0
  fi
  detected="$(hostname -f 2>/dev/null || true)"
  if [[ -n "$detected" ]]; then
    echo "$detected"
    return 0
  fi
  hostname 2>/dev/null || true
}

load_noninteractive_env() {
  PUBLIC_HOST="${PUBLIC_HOST:-$(default_public_host)}"
  HOST_MODE="${HOST_MODE:-$(infer_host_mode "${PUBLIC_HOST:-}")}"
  TRANSPORT_MODE="ws"
  WS_PATH="${WS_PATH:-/ws}"
  FINGERPRINT="${FINGERPRINT:-chrome}"
  REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-www.cloudflare.com}"
  REALITY_DEST="${REALITY_DEST:-${REALITY_SERVER_NAME}:443}"
  AGENT_NAME="${AGENT_NAME:-$(hostname 2>/dev/null || echo agent-node)}"
  XRAY_PORT="${XRAY_PORT:-443}"
  REALITY_PORT="${REALITY_PORT:-8443}"
  XRAY_API_PORT="${XRAY_API_PORT:-10085}"
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
  AGENT_TLS_ENABLED="$(parse_bool "${AGENT_TLS_ENABLED:-true}")"
  ALLOWED_SOURCES_RAW="${ALLOWED_SOURCES:-}"
  if [[ -z "$ALLOWED_SOURCES_RAW" ]]; then
    ALLOWED_SOURCES_RAW="$(detect_ssh_client_ip || true)"
    if [[ -n "$ALLOWED_SOURCES_RAW" && "$ALLOWED_SOURCES_RAW" != */* ]]; then
      ALLOWED_SOURCES_RAW="$ALLOWED_SOURCES_RAW/32"
    fi
  fi
  ALLOWED_SOURCES="$(normalize_allowed_sources "$ALLOWED_SOURCES_RAW")"
  AGENT_TOKEN="${AGENT_TOKEN:-}"
  if [[ -z "$AGENT_TOKEN" ]]; then
    AGENT_TOKEN="$(python3 - <<'PYTOK'
import secrets
print(secrets.token_urlsafe(32))
PYTOK
)"
  fi
}

ask_host_mode() {
  echo "Choose public host type:"
  echo "1) IP"
  echo "2) Domain"
  read -rp "Select [1/2]: " HOST_TYPE
  if [[ "$HOST_TYPE" == "1" ]]; then
    HOST_MODE="ip"
    read -rp "Public IP: " PUBLIC_HOST
  elif [[ "$HOST_TYPE" == "2" ]]; then
    HOST_MODE="domain"
    read -rp "Domain or subdomain: " PUBLIC_HOST
    read -rp "Have you already pointed DNS (A record) to this server IP? [y/n]: " DNS_READY
    if [[ "$DNS_READY" != "y" && "$DNS_READY" != "Y" ]]; then
      echo "Please create/update the A record first, then run the installer again."
      exit 1
    fi
    if resolve_host_ready "$PUBLIC_HOST"; then
      echo "Domain resolves successfully."
    else
      echo "Warning: domain does not resolve yet."
      read -rp "Continue anyway? [y/n]: " CONTINUE_ANYWAY
      if [[ "$CONTINUE_ANYWAY" != "y" && "$CONTINUE_ANYWAY" != "Y" ]]; then
        exit 1
      fi
    fi
  else
    echo "Invalid option."
    exit 1
  fi
}

ask_transport_mode() {
  echo
  echo "This node will install both profiles:"
  echo "- VLESS | Simple"
  echo "- VLESS | Reality"
  FINGERPRINT="chrome"
  WS_PATH="${WS_PATH:-/ws}"
  read -rp "REALITY serverName/SNI (example: www.cloudflare.com): " REALITY_SERVER_NAME
  read -rp "REALITY dest [default ${REALITY_SERVER_NAME}:443]: " REALITY_DEST
  REALITY_DEST="${REALITY_DEST:-${REALITY_SERVER_NAME}:443}"
  read -rp "Fingerprint [default chrome]: " FINGERPRINT
  FINGERPRINT="${FINGERPRINT:-chrome}"
}

ask_config() {
  read -rp "Agent display name: " AGENT_NAME
  read -rp "VLESS Simple port [443]: " XRAY_PORT
  XRAY_PORT="${XRAY_PORT:-443}"
  REALITY_PORT="${REALITY_PORT:-8443}"
  read -rp "VLESS Reality port [8443]: " REALITY_PORT
  REALITY_PORT="${REALITY_PORT:-8443}"
  read -rp "Xray API stats port [10085]: " XRAY_API_PORT
  XRAY_API_PORT="${XRAY_API_PORT:-10085}"
  local detected_source default_source
  detected_source="$(detect_ssh_client_ip || true)"
  default_source="${detected_source:+${detected_source}/32}"
  read -rp "Agent listen host [0.0.0.0]: " AGENT_LISTEN_HOST
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  read -rp "Agent listen port [8787]: " AGENT_LISTEN_PORT
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
  if [[ -n "$default_source" ]]; then
    read -rp "Allowed source IPs/CIDRs (recommended: master IP, use ANY for unrestricted) [$default_source]: " ALLOWED_SOURCES
    ALLOWED_SOURCES="${ALLOWED_SOURCES:-$default_source}"
  else
    read -rp "Allowed source IPs/CIDRs (recommended: master IP, use ANY for unrestricted): " ALLOWED_SOURCES
  fi
  ALLOWED_SOURCES="$(normalize_allowed_sources "$ALLOWED_SOURCES")"
  read -rp "Agent API token [leave blank to auto-generate]: " AGENT_TOKEN
  if [[ -z "$AGENT_TOKEN" ]]; then
    AGENT_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  fi
}


map_xray_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "64" ;;
    aarch64|arm64) echo "arm64-v8a" ;;
    armv7l|armv7) echo "arm32-v7a" ;;
    armv6l) echo "arm32-v6" ;;
    i386|i686) echo "32" ;;
    s390x) echo "s390x" ;;
    riscv64) echo "riscv64" ;;
    *) echo "Unsupported CPU architecture: $(uname -m)" >&2; exit 1 ;;
  esac
}

download_xray_release_zip() {
  local arch="$1" output_zip="$2" asset_name base_url download_url digest_url digest_file digest actual
  asset_name="Xray-linux-${arch}.zip"
  base_url="${XRAY_DOWNLOAD_BASE_URL:-https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}}"
  download_url="${base_url}/${asset_name}"
  digest_url="${base_url}/${asset_name}.dgst"
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 300 -H "User-Agent: Sahar/0.1.74" "$download_url" -o "$output_zip"; then
    set_fail_hint "Failed to download Xray archive"
    return 1
  fi
  digest_file="$(mktemp)"
  if curl -fL --retry 2 --retry-delay 2 --connect-timeout 15 --max-time 60 -H "User-Agent: Sahar/0.1.74" "$digest_url" -o "$digest_file"; then
    digest="$(grep -Eo '[A-Fa-f0-9]{64}' "$digest_file" | head -n1 || true)"
    if [[ -n "$digest" ]]; then
      actual="$(sha256sum "$output_zip" | awk '{print $1}')"
      if [[ "$actual" != "$digest" ]]; then
        rm -f "$digest_file"
        set_fail_hint "Xray checksum verification failed"
        return 1
      fi
    fi
  fi
  rm -f "$digest_file"
}

install_xray_alpine() {
  local arch tmpdir
  arch="$(map_xray_arch)"
  tmpdir="$(mktemp -d)"
  begin_step_phase 10 18 "Preparing Xray directories"
  mkdir -p /usr/local/bin /usr/local/etc/xray /usr/local/share/xray /var/log/xray
  begin_step_phase 22 58 "Downloading Xray release archive"
  if ! download_xray_release_zip "$arch" "$tmpdir/xray.zip"; then
    rm -rf "$tmpdir"
    return 1
  fi
  set_step_progress 62 "Extracting Xray archive"
  unzip -qo "$tmpdir/xray.zip" -d "$tmpdir"
  if [[ ! -f "$tmpdir/xray" ]]; then
    rm -rf "$tmpdir"
    set_fail_hint "Downloaded Xray archive does not contain the xray binary"
    return 1
  fi
  begin_step_phase 66 82 "Installing Xray binaries"
  install -m 0755 "$tmpdir/xray" /usr/local/bin/xray
  if [[ -f "$tmpdir/geoip.dat" ]]; then install -m 0644 "$tmpdir/geoip.dat" /usr/local/share/xray/geoip.dat; fi
  if [[ -f "$tmpdir/geosite.dat" ]]; then install -m 0644 "$tmpdir/geosite.dat" /usr/local/share/xray/geosite.dat; fi
  begin_step_phase 86 96 "Writing Xray service definition"
  if [[ ! -f /usr/local/etc/xray/config.json ]]; then
    echo '{"log":{"loglevel":"warning"},"inbounds":[],"outbounds":[{"protocol":"freedom","settings":{}}]}' > /usr/local/etc/xray/config.json
  fi
  cat > /etc/init.d/xray <<'EOF'
#!/sbin/openrc-run
name="xray"
description="Xray service"
command="/usr/local/bin/xray"
command_args="run -config /usr/local/etc/xray/config.json"
pidfile="/run/xray.pid"
command_background=true
output_log="/var/log/xray/service.log"
error_log="/var/log/xray/service.err"
depend() { need net; }
EOF
  chmod +x /etc/init.d/xray
  rm -rf "$tmpdir"
  set_step_progress 100 "Xray components are ready"
}


install_xray() {
  if command_exists xray; then
    set_step_progress 100 "Xray already installed"
    return 0
  fi
  status_note "Installing Xray"
  install_xray_alpine
}

prepare_dirs() {
  mkdir -p "$APP_APP_DIR" "$APP_DATA_DIR" "$APP_LOG_DIR" "$APP_BACKUP_DIR" "$APP_DIR/tls"
}

write_tls_material() {
  local cert_path="$APP_DIR/tls/agent.crt" key_path="$APP_DIR/tls/agent.key" san_entries subject_cn actual_host
  actual_host="${PUBLIC_HOST:-localhost}"
  if [[ -f "$cert_path" && -f "$key_path" ]]; then
    AGENT_TLS_CERT_PATH="$cert_path"
    AGENT_TLS_KEY_PATH="$key_path"
    AGENT_TLS_FINGERPRINT="$(openssl x509 -in "$cert_path" -noout -fingerprint -sha256 | awk -F= '{print tolower($2)}' | tr -d ':')"
    return 0
  fi
  if [[ "$HOST_MODE" == "ip" ]]; then
    san_entries="IP:${actual_host},IP:127.0.0.1,DNS:localhost"
    subject_cn="${actual_host}"
  else
    san_entries="DNS:${actual_host},DNS:localhost,IP:127.0.0.1"
    subject_cn="${actual_host}"
  fi
  openssl req -x509 -nodes -newkey rsa:2048 -days 825     -keyout "$key_path"     -out "$cert_path"     -subj "/CN=${subject_cn}"     -addext "subjectAltName=${san_entries}" >/dev/null 2>&1
  chmod 600 "$key_path" "$cert_path"
  AGENT_TLS_CERT_PATH="$cert_path"
  AGENT_TLS_KEY_PATH="$key_path"
  AGENT_TLS_FINGERPRINT="$(openssl x509 -in "$cert_path" -noout -fingerprint -sha256 | awk -F= '{print tolower($2)}' | tr -d ':')"
}

copy_code() {
  cp -R "$SCRIPT_DIR/agent_app/." "$APP_APP_DIR/"
}

write_config() {
  export APP_DATA_DIR APP_LOG_DIR APP_BACKUP_DIR AGENT_NAME AGENT_TOKEN ALLOWED_SOURCES AGENT_LISTEN_HOST AGENT_LISTEN_PORT PUBLIC_HOST HOST_MODE XRAY_PORT REALITY_PORT XRAY_API_PORT XRAY_CONFIG_PATH TRANSPORT_MODE WS_PATH REALITY_SERVER_NAME REALITY_DEST FINGERPRINT APP_VERSION AGENT_TLS_ENABLED AGENT_TLS_CERT_PATH AGENT_TLS_KEY_PATH AGENT_TLS_FINGERPRINT
  python3 - <<'PY'
import json
import os
from pathlib import Path
cfg = {
    'agent_name': os.environ['AGENT_NAME'],
    'agent_token': os.environ['AGENT_TOKEN'],
    'allowed_sources': os.environ['ALLOWED_SOURCES'],
    'agent_listen_host': os.environ['AGENT_LISTEN_HOST'],
    'agent_listen_port': int(os.environ['AGENT_LISTEN_PORT']),
    'public_host': os.environ['PUBLIC_HOST'],
    'host_mode': os.environ['HOST_MODE'],
    'xray_port': int(os.environ['XRAY_PORT']),
    'simple_port': int(os.environ['XRAY_PORT']),
    'reality_port': int(os.environ['REALITY_PORT']),
    'xray_api_port': int(os.environ['XRAY_API_PORT']),
    'xray_config_path': os.environ['XRAY_CONFIG_PATH'],
    'transport_mode': os.environ['TRANSPORT_MODE'],
    'ws_path': os.environ['WS_PATH'],
    'reality_server_name': os.environ['REALITY_SERVER_NAME'],
    'reality_dest': os.environ['REALITY_DEST'],
    'reality_public_key': '',
    'reality_private_key': '',
    'reality_short_id': '',
    'fingerprint': os.environ['FINGERPRINT'],
    'log_path': os.path.join(os.environ['APP_LOG_DIR'], 'agent.log'),
    'backup_dir': os.environ['APP_BACKUP_DIR'],
    'xray_access_log': '/var/log/xray/access.log',
    'xray_error_log': '/var/log/xray/error.log',
    'rate_limit_window_seconds': 60,
    'rate_limit_max_requests': 120,
    'package_version': os.environ['APP_VERSION'],
    'agent_tls_enabled': os.environ.get('AGENT_TLS_ENABLED', 'false').lower() == 'true',
    'agent_tls_cert_path': os.environ.get('AGENT_TLS_CERT_PATH', ''),
    'agent_tls_key_path': os.environ.get('AGENT_TLS_KEY_PATH', ''),
    'agent_tls_fingerprint': os.environ.get('AGENT_TLS_FINGERPRINT', ''),
}
path = Path(os.environ['APP_DATA_DIR']) / 'config.json'
path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
path.chmod(0o600)
PY
}

setup_venv() {
  local req_hash state_file wheel_state_file venv_python_tag wheel_state expected_wheel_state
  mkdir -p "$INSTALLER_STATE_DIR" "$PIP_CACHE_DIR" "$WHEELHOUSE_DIR"
  state_file="$INSTALLER_STATE_DIR/agent-requirements.sha256"
  wheel_state_file="$INSTALLER_STATE_DIR/agent-wheelhouse.sha256"
  begin_step_phase 5 14 "Preparing virtual environment"
  if ! run_with_timeout 180 python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
    if command -v virtualenv >/dev/null 2>&1; then
      begin_step_phase 10 18 "Creating virtual environment with virtualenv"
      run_with_timeout 180 virtualenv "$VENV_DIR"
    else
      begin_step_phase 10 16 "Bootstrapping ensurepip"
      run_with_timeout 180 python3 -m ensurepip --upgrade || true
      begin_step_phase 16 22 "Creating virtual environment"
      run_with_timeout 180 python3 -m venv "$VENV_DIR"
    fi
  fi
  req_hash="$(file_sha256 "$APP_APP_DIR/requirements.txt")"
  venv_python_tag="$($VENV_DIR/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
  expected_wheel_state="${req_hash}|${OS_FAMILY}|${venv_python_tag}"
  if [[ -x "$VENV_DIR/bin/python" && -x "$VENV_DIR/bin/pip" && -f "$state_file" ]] && [[ "$(cat "$state_file")" == "$expected_wheel_state" ]]; then
    set_step_progress 100 "Using cached Python environment"
    return 0
  fi
  export PIP_CACHE_DIR
  begin_step_phase 24 34 "Refreshing pip, setuptools and wheel"
  run_with_timeout 600 "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
  wheel_state=""
  if [[ -f "$wheel_state_file" ]]; then
    wheel_state="$(cat "$wheel_state_file")"
  fi
  if [[ "$wheel_state" != "$expected_wheel_state" ]]; then
    begin_step_phase 38 72 "Building wheels for Python packages"
    rm -rf "$WHEELHOUSE_DIR"
    mkdir -p "$WHEELHOUSE_DIR"
    run_with_timeout 2400 "$VENV_DIR/bin/pip" wheel -r "$APP_APP_DIR/requirements.txt" --wheel-dir "$WHEELHOUSE_DIR"
    printf '%s
' "$expected_wheel_state" > "$wheel_state_file"
  else
    set_step_progress 72 "Using cached wheels"
  fi
  begin_step_phase 76 96 "Installing from cached wheelhouse"
  run_with_timeout 1800 "$VENV_DIR/bin/pip" install --no-index --find-links "$WHEELHOUSE_DIR" -r "$APP_APP_DIR/requirements.txt"
  printf '%s
' "$expected_wheel_state" > "$state_file"
  set_step_progress 100 "Python environment is ready"
}

write_service() {
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    cat > "/etc/systemd/system/${API_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Agent API
After=network-online.target xray.service
Wants=network-online.target
Requires=xray.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$APP_APP_DIR
Environment=SAHAR_CONFIG=$APP_DATA_DIR/config.json
ExecStart=$VENV_DIR/bin/gunicorn -w 2 -k gthread --threads 4 --certfile $APP_DIR/tls/agent.crt --keyfile $APP_DIR/tls/agent.key --bind ${AGENT_LISTEN_HOST}:${AGENT_LISTEN_PORT} agent_api:APP
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR /usr/local/etc/xray /var/log/xray

[Install]
WantedBy=multi-user.target
SERVICE
  else
    cat > "/etc/init.d/${API_SERVICE_NAME}" <<SERVICE
#!/sbin/openrc-run
name="${API_SERVICE_NAME}"
description="Sahar Agent API"
command="${VENV_DIR}/bin/gunicorn"
command_args="-w 2 -k gthread --threads 4 --certfile $APP_DIR/tls/agent.crt --keyfile $APP_DIR/tls/agent.key --bind ${AGENT_LISTEN_HOST}:${AGENT_LISTEN_PORT} agent_api:APP"
directory="${APP_APP_DIR}"
pidfile="/run/${API_SERVICE_NAME}.pid"
command_background=true
output_log="${APP_LOG_DIR}/agent-service.log"
error_log="${APP_LOG_DIR}/agent-service.err"
depend() { need net xray; }
start_pre() { export SAHAR_CONFIG="${APP_DATA_DIR}/config.json"; }
SERVICE
    chmod +x "/etc/init.d/${API_SERVICE_NAME}"
  fi
}


enable_services() {
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    systemctl daemon-reload
    systemctl enable xray --now
    systemctl enable "$API_SERVICE_NAME" --now
  else
    rc-update add xray default
    rc-service xray start
    rc-update add "$API_SERVICE_NAME" default
    rc-service "$API_SERVICE_NAME" start
  fi
  wait_for_tcp_listener "$AGENT_LISTEN_HOST" "$AGENT_LISTEN_PORT" 30 2 || {
    append_post_install_warning "Agent API socket did not become reachable during installation. Check $APP_LOG_DIR/agent-service.err and the xray service status."
  }
}


print_done() {
  if (( UI_TTY )); then
    CURRENT_STEP=$TOTAL_STEPS
    CURRENT_LABEL="Installation complete"
    CURRENT_STATUS="Ready"
    draw_screen
    ui_newline
  else
    echo
  fi
  printf '%sAgent installed successfully.%s
' "$C_GREEN" "$C_RESET"
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    echo "Service: systemctl status $API_SERVICE_NAME"
    echo "Logs: journalctl -u $API_SERVICE_NAME -f"
  else
    echo "Service: rc-service $API_SERVICE_NAME status"
    echo "Logs: tail -f $APP_LOG_DIR/*.log"
  fi
  echo
  echo "Agent API URL: https://${PUBLIC_HOST}:${AGENT_LISTEN_PORT}"
  echo "Agent TLS fingerprint: ${AGENT_TLS_FINGERPRINT}"
  echo "Agent credentials saved in: $APP_DATA_DIR/config.json"
}


main() {
  setup_ui
  print_banner
  require_root
  run_step "Checking system" check_os
  run_step "Running preflight checks" preflight_checks
  run_step "Installing system packages" install_packages
  run_step "Preparing defaults" load_noninteractive_env
  run_step "Installing Xray components" install_xray
  run_step "Creating directories" prepare_dirs
  run_step "Copying application files" copy_code
  run_step "Generating TLS certificate" write_tls_material
  run_step "Writing configuration" write_config
  run_step "Building Python environment" setup_venv
  run_step "Writing service files" write_service
  run_step "Configuring log rotation" write_logrotate
  run_step "Starting services" enable_services
  ui_newline
  print_done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
