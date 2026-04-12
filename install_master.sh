#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.72"

APP_DIR="/opt/sahar-master"
APP_APP_DIR="$APP_DIR/app"
APP_AGENT_APP_DIR="$APP_DIR/agent_app"
APP_DATA_DIR="$APP_DIR/data"
APP_LOG_DIR="$APP_DIR/logs"
APP_QR_DIR="$APP_DIR/qrcodes"
APP_BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"
SERVICE_USER="sahar-master"
SERVICE_GROUP="sahar-master"
BOT_SERVICE_NAME="sahar-master-bot"
SCHED_SERVICE_NAME="sahar-master-scheduler"
LOCAL_AGENT_SERVICE_NAME="sahar-master-local-agent"
SUB_SERVICE_NAME="sahar-master-subscription"
XRAY_CONFIG_PATH="/usr/local/etc/xray/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_ENV_DIR="/etc/sahar"
TOKEN_ENV_FILE="$TOKEN_ENV_DIR/master.env"
INSTALLER_STATE_DIR="$APP_DATA_DIR/.installer-state"
CACHE_DIR="/var/cache/sahar"
PIP_CACHE_DIR="$CACHE_DIR/pip"
WHEELHOUSE_DIR="$CACHE_DIR/wheelhouse/master"

LOG_FILE="/tmp/sahar-master-installer.log"
STATUS_FILE="/tmp/sahar-master-installer.status"
TOTAL_STEPS=16
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
VALIDATION_ERROR=""
VALIDATION_SUCCESS=""
VALIDATION_INVALID_FIELD=""
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
UI_LANG="${UI_LANG:-fa}"
UI_LANG_LABEL="فارسی"

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

select_language() {
  local choice=""
  if [[ ! -t 0 ]]; then
    UI_LANG="${UI_LANG:-fa}"
  fi
  if (( UI_TTY )); then
    printf '[H[2J'
  fi
  printf '%s%s%s
' "$C_BOLD" "$C_CYAN" 'زبان خود را انتخاب کنید / Choose your language' "$C_RESET"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  printf '  1) فارسی
'
  printf '  2) English

'
  if [[ -t 0 ]]; then
    if (( UI_TTY )); then
      printf '%s' "$C_BOLD"
    fi
    read -r -p 'Selection [1/2]: ' choice || true
    if (( UI_TTY )); then
      printf '%s' "$C_RESET"
    fi
  fi
  case "$(printf '%s' "$choice" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')" in
    2|en|english)
      UI_LANG='en'
      UI_LANG_LABEL='English'
      ;;
    *)
      UI_LANG='fa'
      UI_LANG_LABEL='فارسی'
      ;;
  esac
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
  printf '%s%sSahar Master Installer v%s%s
' "$C_BOLD" "$C_CYAN" "$APP_VERSION" "$C_RESET"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  printf ' %sMode%s        Master
' "$C_DIM" "$C_RESET"
  printf ' %sSystem%s      %s
' "$C_DIM" "$C_RESET" "${OS_PRETTY_NAME:-Detecting...}"
  printf ' %sInit%s        %s
' "$C_DIM" "$C_RESET" "${INIT_SYSTEM:-Detecting...}"
  printf ' %sLanguage%s    %s
' "$C_DIM" "$C_RESET" "${UI_LANG_LABEL:-فارسی}"
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
  printf '%sفقط سه مقدار لازم است / Only three values are requested: Telegram bot token, Cloudflare API token and domain.%s
' "$C_YELLOW" "$C_RESET"
  printf '%sبقیه کارها خودکار انجام می‌شود / Cloudflare tunnel and DNS are configured automatically when those values are provided.%s
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

http_status_code() {
  local url="$1"
  local token="${2:-}"
  local extra=()
  if [[ -n "$token" ]]; then
    extra=(-H "X-Agent-Token: $token")
  fi
  curl -fsS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 "${extra[@]}" "$url"
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

wait_for_http_ready() {
  local url="$1"
  local token="$2"
  local attempts="${3:-20}"
  local delay="${4:-2}"
  local label="${5:-service}"
  local code=''
  for ((i=1; i<=attempts; i++)); do
    status_note "Waiting for ${label} HTTP endpoint (${i}/${attempts})"
    code="$(http_status_code "$url" "$token" 2>/dev/null || true)"
    case "$code" in
      200) return 0 ;;
      401|403)
        set_fail_hint "${label} returned HTTP ${code}; check token or allowed_sources"
        return 1
        ;;
    esac
    sleep "$delay"
  done
  set_fail_hint "Timed out waiting for ${label} HTTP endpoint"
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

persist_bot_token() {
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    return 0
  fi
  mkdir -p "$TOKEN_ENV_DIR"
  umask 077
  printf 'BOT_TOKEN=%q
' "$BOT_TOKEN" > "$TOKEN_ENV_FILE"
  chmod 600 "$TOKEN_ENV_FILE"
}

load_saved_bot_token() {
  if [[ -z "${BOT_TOKEN:-}" && -r "$TOKEN_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    . "$TOKEN_ENV_FILE"
  fi
  if [[ -z "${BOT_TOKEN:-}" && -r "$APP_DATA_DIR/config.json" ]]; then
    BOT_TOKEN="$(sed -n 's/.*"bot_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$APP_DATA_DIR/config.json" | head -n1)"
  fi
}

load_saved_cloudflare_inputs() {
  if [[ -r "$APP_DATA_DIR/config.json" ]]; then
    if [[ -z "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
      CLOUDFLARE_DOMAIN_NAME="$(sed -n 's/.*"cloudflare_domain_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$APP_DATA_DIR/config.json" | head -n1)"
    fi
    if [[ -z "${CLOUDFLARE_BASE_SUBDOMAIN:-}" ]]; then
      CLOUDFLARE_BASE_SUBDOMAIN="$(sed -n 's/.*"cloudflare_base_subdomain"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$APP_DATA_DIR/config.json" | head -n1)"
    fi
  fi
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

install_packages() {
  local need_install=0
  if [[ "$OS_FAMILY" == "debian" ]]; then
    for cmd in python3 pip3 sqlite3 curl tar unzip jq git openssl; do
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
    run_with_timeout 900 apt install -y python3 python3-venv python3-pip sqlite3 curl ca-certificates tar zip unzip jq uuid-runtime dnsutils logrotate git openssl
  else
    for cmd in python3 pip3 curl unzip jq git gcc openssl; do
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
    run_with_timeout 1200 apk add --no-cache bash python3 py3-pip py3-virtualenv sqlite curl ca-certificates tar zip unzip jq uuidgen bind-tools logrotate shadow build-base python3-dev musl-dev linux-headers git openssl
  fi
  begin_step_phase 88 96 "Verifying installed commands"
  for cmd in python3 pip3 curl tar unzip jq git openssl; do
    if ! command_exists "$cmd"; then
      set_fail_hint "Required command missing after package install: $cmd"
      return 1
    fi
  done
  set_step_progress 100 "System packages are ready"
}

ensure_user() {
  if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    if [[ "$OS_FAMILY" == "debian" ]]; then
      groupadd --system "$SERVICE_GROUP"
    else
      addgroup -S "$SERVICE_GROUP"
    fi
  fi

  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    if [[ "$OS_FAMILY" == "debian" ]]; then
      useradd --system --gid "$SERVICE_GROUP" --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    else
      adduser -S -D -H -h "$APP_DIR" -s /sbin/nologin -G "$SERVICE_GROUP" "$SERVICE_USER"
    fi
  fi
}

parse_bool() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|on|ON|On) echo "true" ;;
    *) echo "false" ;;
  esac
}

infer_host_mode() {
  local host="${1:-}"
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

first_nonempty() {
  local value
  for value in "$@"; do
    if [[ -n "$value" ]]; then
      echo "$value"
      return 0
    fi
  done
  return 1
}

init_config_defaults() {
  local detected_public_ip cf_requested
  BOT_TOKEN="${BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
  ADMIN_CHAT_IDS="${ADMIN_CHAT_IDS:-${SAHAR_ADMIN_CHAT_IDS:-}}"
  SCHEDULER_INTERVAL="${SCHEDULER_INTERVAL:-300}"
  AGENT_TIMEOUT="${AGENT_TIMEOUT:-15}"
  WARN_DAYS_LEFT="${WARN_DAYS_LEFT:-3}"
  WARN_USAGE_PERCENT="${WARN_USAGE_PERCENT:-80}"
  BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
  BACKUP_RETENTION="${BACKUP_RETENTION:-10}"
  SUBSCRIPTION_BIND_HOST="${SUBSCRIPTION_BIND_HOST:-0.0.0.0}"
  SUBSCRIPTION_BIND_PORT="${SUBSCRIPTION_BIND_PORT:-8090}"
  detected_public_ip="$(detect_public_ipv4 || true)"
  SUBSCRIPTION_BASE_URL="${SUBSCRIPTION_BASE_URL:-}"
  if [[ -z "$SUBSCRIPTION_BASE_URL" && -n "$detected_public_ip" ]]; then
    SUBSCRIPTION_BASE_URL="http://${detected_public_ip}:${SUBSCRIPTION_BIND_PORT}"
  fi

  CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-}"
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
  cf_requested='false'
  if [[ -n "$CLOUDFLARE_API_TOKEN" || -n "$CLOUDFLARE_DOMAIN_NAME" ]]; then
    cf_requested='true'
  fi
  CLOUDFLARE_ENABLED="$(parse_bool "${CLOUDFLARE_ENABLED:-$cf_requested}")"
  if [[ "$CLOUDFLARE_ENABLED" != "true" ]]; then
    CLOUDFLARE_DOMAIN_NAME=""
    CLOUDFLARE_BASE_SUBDOMAIN=""
    CLOUDFLARE_API_TOKEN=""
  fi
  CLOUDFLARE_TOKEN_ENCRYPTION_KEY="${CLOUDFLARE_TOKEN_ENCRYPTION_KEY:-$(python3 - <<'PY2'
import os, base64
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY2
)}"

  LOCAL_NODE_ENABLED="$(parse_bool "${LOCAL_NODE_ENABLED:-true}")"
  LOCAL_SERVER_NAME="${LOCAL_SERVER_NAME:-local}"
  LOCAL_AGENT_LISTEN_HOST="${LOCAL_AGENT_LISTEN_HOST:-127.0.0.1}"
  LOCAL_AGENT_LISTEN_PORT="${LOCAL_AGENT_LISTEN_PORT:-8787}"
  LOCAL_TRANSPORT_MODE="ws"
  LOCAL_WS_PATH="${LOCAL_WS_PATH:-/ws}"
  LOCAL_REALITY_SERVER_NAME="${LOCAL_REALITY_SERVER_NAME:-www.cloudflare.com}"
  LOCAL_REALITY_DEST="${LOCAL_REALITY_DEST:-${LOCAL_REALITY_SERVER_NAME}:443}"
  LOCAL_FINGERPRINT="${LOCAL_FINGERPRINT:-chrome}"
  LOCAL_XRAY_PORT="${LOCAL_XRAY_PORT:-443}"
  LOCAL_REALITY_PORT="${LOCAL_REALITY_PORT:-8443}"
  LOCAL_XRAY_API_PORT="${LOCAL_XRAY_API_PORT:-10085}"
  LOCAL_AGENT_API_TOKEN="${LOCAL_AGENT_API_TOKEN:-}"
  LOCAL_AGENT_API_URL=""
  LOCAL_PUBLIC_HOST="$(first_nonempty "${LOCAL_PUBLIC_HOST:-}" "$detected_public_ip" "$(hostname -f 2>/dev/null || true)" "$(hostname 2>/dev/null || true)" || true)"
  LOCAL_HOST_MODE="${LOCAL_HOST_MODE:-$(infer_host_mode "$LOCAL_PUBLIC_HOST")}"

  if [[ "$LOCAL_NODE_ENABLED" == "true" ]]; then
    if [[ -z "$LOCAL_AGENT_API_TOKEN" ]]; then
      LOCAL_AGENT_API_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
    fi
    LOCAL_AGENT_API_URL="http://127.0.0.1:${LOCAL_AGENT_LISTEN_PORT}"
    if [[ "$LOCAL_HOST_MODE" == "domain" && -n "$LOCAL_PUBLIC_HOST" ]] && ! resolve_host_ready "$LOCAL_PUBLIC_HOST"; then
      echo "Warning: local node domain does not resolve yet: $LOCAL_PUBLIC_HOST"
    fi
  else
    LOCAL_SERVER_NAME="local"
    LOCAL_AGENT_API_URL=""
    LOCAL_AGENT_API_TOKEN=""
    LOCAL_PUBLIC_HOST=""
    LOCAL_HOST_MODE=""
  fi
}

telegram_bot_enabled() {
  [[ -n "${BOT_TOKEN:-}" ]]
}

show_bot_token_help() {
  printf '%s%s📌 توکن ربات تلگرام / Telegram bot token%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چیزی که لازم داری / What you need:%s توکن HTTP API ربات تلگرام.
' "$C_YELLOW" "$C_RESET"
  printf '  %s• از کجا بگیری / Where to get it: open Telegram, chat with BotFather, run /newbot (or open your existing bot), then copy the token.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نمونه درست / Correct format example:%s 123456789:AAExampleTokenValue

' "$C_YELLOW" "$C_RESET"
}

show_cloudflare_token_help() {
  printf '%s%s☁️  توکن API کلودفلر / Cloudflare API token%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چیزی که لازم داری / What you need: a Cloudflare API token, not the Global API Key.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• از کجا بگیری / Where to get it: Cloudflare Dashboard → My Profile → API Tokens → Create Token.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نوع پیشنهادی / Recommended type:%s Custom Token
' "$C_YELLOW" "$C_RESET"
  printf '  %s• دسترسی‌های لازم / Required permissions:%s
' "$C_YELLOW" "$C_RESET"
  printf '      - Zone / Zone / Read
'
  printf '      - Zone / DNS / Edit
'
  printf '      - Account / Cloudflare Tunnel / Edit
'
  printf '  %s• نکته مهم / Important:%s توکن باید به همان اکانت و دامنه‌ای دسترسی داشته باشد که پایین وارد می‌کنی.

' "$C_YELLOW" "$C_RESET"
}

show_domain_help() {
  printf '%s%s🌐 دامنه اصلی / Domain%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چه چیزی وارد شود / What to enter:%s دامنه اصلی که از قبل داخل Cloudflare اضافه شده است.
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نمونه درست / Correct example:%s example.com
' "$C_YELLOW" "$C_RESET"
  printf '  %s• وارد نکن / Do not enter:%s https://example.com ، sub.example.com ، example.com/test

' "$C_YELLOW" "$C_RESET"
}

read_visible_input() {
  local prompt="$1"
  local result_var="$2"
  local value=""
  if (( UI_TTY )); then
    printf ' %s%s%s' "$C_BOLD$C_GREEN" "$prompt" "$C_RESET"
    read -r value || true
  else
    read -r -p "${prompt}" value || true
  fi
  printf -v "$result_var" '%s' "$value"
}

normalize_domain_value() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]'
}

domain_format_error() {
  local domain
  domain="$(normalize_domain_value "$1")"
  if [[ -z "$domain" ]]; then
    printf 'Domain cannot be empty.'
    return 0
  fi
  if [[ "$domain" == *"://"* ]]; then
    printf 'Use only the root domain, without http:// or https://.'
    return 0
  fi
  if [[ "$domain" == */* ]]; then
    printf 'Do not include any path. Use only the root domain, مثل example.com.'
    return 0
  fi
  if [[ "$domain" == *"*"* ]]; then
    printf 'Wildcard domains are not accepted here. Enter the root domain only.'
    return 0
  fi
  if [[ "$domain" != *.* ]]; then
    printf 'This does not look like a root domain. Example: example.com'
    return 0
  fi
  if [[ ! "$domain" =~ ^[a-z0-9.-]+$ ]]; then
    printf 'The domain contains invalid characters. Use letters, numbers, dots, and hyphens only.'
    return 0
  fi
  if [[ "$domain" =~ ^[.-] || "$domain" =~ [.-]$ || "$domain" =~ \.\. || "$domain" =~ -- ]]; then
    printf 'The domain format is not valid. Example: example.com'
    return 0
  fi
  return 1
}

telegram_bot_enabled() {
  [[ -n "${BOT_TOKEN:-}" ]]
}

validate_bot_token_once() {
  local payload response http_code description error_code username first_name
  VALIDATION_ERROR=""
  VALIDATION_SUCCESS=""
  VALIDATION_INVALID_FIELD=""
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    VALIDATION_ERROR='Telegram bot token is empty.'
    VALIDATION_INVALID_FIELD='bot_token'
    return 1
  fi

  status_note 'Telegram API: checking BOT_TOKEN over IPv4'
  payload="$(api_json_get_ipv4 "https://api.telegram.org/bot${BOT_TOKEN}/getMe")"
  if [[ -z "$payload" ]]; then
    set_fail_hint 'Telegram API unreachable (check DNS, IPv4 egress, or CA certificates)'
    VALIDATION_ERROR='The server could not reach api.telegram.org, so the bot token could not be verified right now.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi

  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    VALIDATION_ERROR='Telegram API returned an empty response. This usually means DNS/TLS/egress trouble or a timed out request.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi

  if ! printf '%s' "$response" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    description="$(printf '%s' "$response" | sed -n 's/.*"description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    error_code="$(printf '%s' "$response" | sed -n 's/.*"error_code"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n1)"
    description="${description:-unknown Telegram API error}"
    error_code="${error_code:-${http_code:-unknown}}"
    VALIDATION_ERROR="This is not a valid Telegram bot token (${error_code}: ${description})."
    VALIDATION_INVALID_FIELD='bot_token'
    return 1
  fi

  username="$(printf '%s' "$response" | sed -n 's/.*"username"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  first_name="$(printf '%s' "$response" | sed -n 's/.*"first_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  if [[ -n "$username" ]]; then
    VALIDATION_SUCCESS="This Telegram bot token is correct. Bot username: @${username}"
  elif [[ -n "$first_name" ]]; then
    VALIDATION_SUCCESS="This Telegram bot token is correct. Bot name: ${first_name}"
  else
    VALIDATION_SUCCESS='This Telegram bot token is correct.'
  fi
  return 0
}

prompt_for_bot_token() {
  local rc
  while true; do
    show_bot_token_help
    read_visible_input '🤖 توکن ربات تلگرام / Telegram bot token: ' BOT_TOKEN_INPUT
    BOT_TOKEN="${BOT_TOKEN_INPUT:-}"
    validate_bot_token_once
    rc=$?
    if (( rc == 0 )); then
      printf '✓ %s\n\n' "$VALIDATION_SUCCESS"
      return 0
    fi
    if (( rc == 2 )); then
      echo "ERROR: $VALIDATION_ERROR"
      return 1
    fi
    printf '✗ %s\n' "$VALIDATION_ERROR"
    echo 'Please copy the token again from BotFather and try once more.'
    echo
  done
}

validate_cloudflare_inputs_once() {
  local payload response http_code domain zone_id account_id tunnel_ok error_message
  VALIDATION_ERROR=""
  VALIDATION_SUCCESS=""
  VALIDATION_INVALID_FIELD=""
  domain="$(normalize_domain_value "${CLOUDFLARE_DOMAIN_NAME:-}")"
  CLOUDFLARE_DOMAIN_NAME="$domain"
  if [[ -z "$domain" && -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    CLOUDFLARE_ENABLED='false'
    VALIDATION_SUCCESS='Cloudflare automation is skipped.'
    return 0
  fi
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    VALIDATION_ERROR='Cloudflare API token is empty.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  if error_message="$(domain_format_error "$domain")"; then
    VALIDATION_ERROR="$error_message"
    VALIDATION_INVALID_FIELD='cloudflare_domain'
    return 1
  fi
  status_note "Cloudflare API: checking zone ${domain} over IPv4"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones?name=${domain}" "${CLOUDFLARE_API_TOKEN}")"
  if [[ -z "$payload" ]]; then
    set_fail_hint 'Cloudflare API unreachable (check DNS, IPv4 egress, or CA certificates)'
    VALIDATION_ERROR='The server could not reach api.cloudflare.com, so the Cloudflare values could not be verified right now.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi
  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    VALIDATION_ERROR='Cloudflare API returned an empty response. This usually means DNS/TLS/egress trouble or a timed out request.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi
  mapfile -t cf_parts < <(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('json_error')
    print('invalid JSON from Cloudflare API')
    print('')
    print('')
    raise SystemExit(0)
if not data.get('success'):
    errors = data.get('errors') or []
    msg = '; '.join(str(item.get('message') or item) for item in errors) or 'unknown Cloudflare API error'
    print('api_error')
    print(msg)
    print('')
    print('')
    raise SystemExit(0)
rows = data.get('result') or []
if not rows:
    print('zone_missing')
    print('domain not found in Cloudflare account')
    print('')
    print('')
    raise SystemExit(0)
row = rows[0]
print('ok')
print(row.get('id') or '')
print(((row.get('account') or {}).get('id')) or '')
print('')
PY2
)
  case "${cf_parts[0]:-json_error}" in
    ok)
      zone_id="${cf_parts[1]:-}"
      account_id="${cf_parts[2]:-}"
      ;;
    zone_missing)
      VALIDATION_ERROR='This domain was not found in the Cloudflare account behind the provided API token.'
      VALIDATION_INVALID_FIELD='cloudflare_domain'
      return 1
      ;;
    api_error)
      error_message="${cf_parts[1]:-invalid Cloudflare response}"
      if printf '%s' "$error_message" | grep -Eqi 'auth|token|permission|forbidden|unauthorized'; then
        VALIDATION_INVALID_FIELD='cloudflare_token'
        VALIDATION_ERROR="This Cloudflare API token is not correct for this request: ${error_message}"
      else
        VALIDATION_INVALID_FIELD='cloudflare_token'
        VALIDATION_ERROR="Cloudflare rejected the API token or request: ${error_message}"
      fi
      return 1
      ;;
    *)
      error_message="${cf_parts[1]:-invalid Cloudflare response}"
      VALIDATION_INVALID_FIELD='cloudflare_token'
      VALIDATION_ERROR="Cloudflare validation failed (${http_code:-unknown}): ${error_message}"
      return 1
      ;;
  esac
  if [[ -z "$account_id" ]]; then
    status_note "Cloudflare API: resolving account id for ${domain}"
    payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones/${zone_id}" "${CLOUDFLARE_API_TOKEN}")"
    response="${payload%$'\n'*}"
    account_id="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('')
    raise SystemExit(0)
print((((data.get('result') or {}).get('account') or {}).get('id')) or '')
PY2
)"
  fi
  if [[ -z "$account_id" ]]; then
    VALIDATION_ERROR='Cloudflare zone resolved, but the account id is missing.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  status_note "Cloudflare API: checking Tunnel permission on account ${account_id}"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/accounts/${account_id}/cfd_tunnel?is_deleted=false&page=1&per_page=1" "${CLOUDFLARE_API_TOKEN}")"
  response="${payload%$'\n'*}"
  tunnel_ok="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('no')
    raise SystemExit(0)
print('yes' if data.get('success') else 'no')
PY2
)"
  if [[ "$tunnel_ok" != 'yes' ]]; then
    VALIDATION_ERROR='This Cloudflare API token can see the zone, but it does not have Cloudflare Tunnel permission.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  status_note "Cloudflare API: access OK for ${domain}"
  CLOUDFLARE_ENABLED='true'
  VALIDATION_SUCCESS="This Cloudflare API token and domain are correct. Zone: ${domain}"
  return 0
}

prompt_for_cloudflare_inputs() {
  local rc
  while true; do
    show_cloudflare_token_help
    if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
      read_visible_input '☁️  توکن API کلودفلر / Cloudflare API token: ' CLOUDFLARE_API_TOKEN_INPUT
      CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN_INPUT:-}"
    else
      printf 'توکن فعلی کلودفلر ثبت شده است و با دامنه پایین بررسی می‌شود. / Current Cloudflare API token is set. It will be verified with the domain below.\n'
    fi
    show_domain_help
    if [[ -z "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
      read_visible_input '🌐 دامنه اصلی / Root domain for subdomains: ' CLOUDFLARE_DOMAIN_NAME_INPUT
      CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME_INPUT:-}"
    else
      printf 'دامنه فعلی / Current domain is: %s\n' "$CLOUDFLARE_DOMAIN_NAME"
    fi
    validate_cloudflare_inputs_once
    rc=$?
    if (( rc == 0 )); then
      printf '✓ %s\n\n' "$VALIDATION_SUCCESS"
      return 0
    fi
    if (( rc == 2 )); then
      echo "ERROR: $VALIDATION_ERROR"
      return 1
    fi
    printf '✗ %s\n' "$VALIDATION_ERROR"
    case "$VALIDATION_INVALID_FIELD" in
      cloudflare_domain)
        echo 'Please enter the root domain again. Example: example.com'
        CLOUDFLARE_DOMAIN_NAME=''
        ;;
      cloudflare_token)
        echo 'Please create or copy the Cloudflare API token again, then paste it here.'
        CLOUDFLARE_API_TOKEN=''
        ;;
      *)
        CLOUDFLARE_API_TOKEN=''
        CLOUDFLARE_DOMAIN_NAME=''
        ;;
    esac
    echo
  done
}

prompt_for_install_inputs() {
  if [[ ! -t 0 ]]; then
    return 0
  fi
  if [[ -n "${BOT_TOKEN:-}" && -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
    return 0
  fi
  if (( UI_TTY )); then
    printf '\033[H\033[2J'
    printf '%s%sAutomatic setup%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
    printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  fi
  cat <<'EOF'
فقط سه مقدار لازم است.
Only three values are needed.

نصاب هر مقدار را همان لحظه بررسی می‌کند و می‌گوید درست است یا نه.
The installer will verify each one and tell you if it is correct.

بعد از آن، ساخت Tunnel و تنظیم DNS کلودفلر خودکار انجام می‌شود.
After that, Cloudflare tunnel and DNS are configured automatically.

اولین چت خصوصی که /start بفرستد، خودکار Owner می‌شود.
The first private chat that sends /start becomes owner automatically.

EOF
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    prompt_for_bot_token || exit 1
  else
    validate_bot_token_once
    case $? in
      0) printf '✓ %s\n\n' "$VALIDATION_SUCCESS" ;;
      2) echo "ERROR: $VALIDATION_ERROR"; exit 1 ;;
      *) echo "ERROR: $VALIDATION_ERROR"; BOT_TOKEN=''; prompt_for_bot_token || exit 1 ;;
    esac
  fi
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
    CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
    CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-}"
    prompt_for_cloudflare_inputs || exit 1
  else
    validate_cloudflare_inputs_once
    case $? in
      0) printf '✓ %s\n\n' "$VALIDATION_SUCCESS" ;;
      2) echo "ERROR: $VALIDATION_ERROR"; exit 1 ;;
      *) echo "ERROR: $VALIDATION_ERROR"; CLOUDFLARE_API_TOKEN=''; CLOUDFLARE_DOMAIN_NAME=''; prompt_for_cloudflare_inputs || exit 1 ;;
    esac
  fi
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  CURRENT_LABEL="Installer inputs captured"
  CURRENT_STATUS="Ready"
  draw_screen
}

validate_bot_token() {
  local rc
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    return 0
  fi
  validate_bot_token_once
  rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  if (( rc == 2 )); then
    echo "ERROR: $VALIDATION_ERROR"
    echo 'Check outbound network access to api.telegram.org or rerun later.'
    exit 1
  fi
  echo "ERROR: $VALIDATION_ERROR"
  exit 1
}

prepare_install_inputs() {
  BOT_TOKEN="${BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
  CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}"
  CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-${DOMAIN:-}}"
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  load_saved_bot_token
  load_saved_cloudflare_inputs
  prompt_for_install_inputs
}

api_json_get_ipv4() {
  local url="$1"
  local bearer_token="${2:-}"
  local payload
  local -a args
  args=(-4 -sS --connect-timeout 5 --max-time 12 --retry 0 -H 'Content-Type: application/json' -w $'
%{http_code}')
  if [[ -n "$bearer_token" ]]; then
    args+=(-H "Authorization: Bearer ${bearer_token}")
  fi
  payload="$(run_with_timeout 20 curl "${args[@]}" "$url" 2>/dev/null || true)"
  printf '%s' "$payload"
}

validate_cloudflare_inputs() {
  local rc
  validate_cloudflare_inputs_once
  rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  if (( rc == 2 )); then
    echo "ERROR: $VALIDATION_ERROR"
    echo 'Check outbound network access to api.cloudflare.com and rerun the installer.'
    exit 1
  fi
  echo "ERROR: $VALIDATION_ERROR"
  exit 1
}

init_config_defaults() {
  local detected_public_ip cf_requested
  BOT_TOKEN="${BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
  ADMIN_CHAT_IDS="${ADMIN_CHAT_IDS:-${SAHAR_ADMIN_CHAT_IDS:-}}"
  SCHEDULER_INTERVAL="${SCHEDULER_INTERVAL:-300}"
  AGENT_TIMEOUT="${AGENT_TIMEOUT:-15}"
  WARN_DAYS_LEFT="${WARN_DAYS_LEFT:-3}"
  WARN_USAGE_PERCENT="${WARN_USAGE_PERCENT:-80}"
  BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
  BACKUP_RETENTION="${BACKUP_RETENTION:-10}"
  SUBSCRIPTION_BIND_HOST="${SUBSCRIPTION_BIND_HOST:-0.0.0.0}"
  SUBSCRIPTION_BIND_PORT="${SUBSCRIPTION_BIND_PORT:-8090}"
  detected_public_ip="$(detect_public_ipv4 || true)"
  SUBSCRIPTION_BASE_URL="${SUBSCRIPTION_BASE_URL:-}"
  if [[ -z "$SUBSCRIPTION_BASE_URL" && -n "$detected_public_ip" ]]; then
    SUBSCRIPTION_BASE_URL="http://${detected_public_ip}:${SUBSCRIPTION_BIND_PORT}"
  fi

  CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-}"
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
  cf_requested='false'
  if [[ -n "$CLOUDFLARE_API_TOKEN" || -n "$CLOUDFLARE_DOMAIN_NAME" ]]; then
    cf_requested='true'
  fi
  CLOUDFLARE_ENABLED="$(parse_bool "${CLOUDFLARE_ENABLED:-$cf_requested}")"
  if [[ "$CLOUDFLARE_ENABLED" != "true" ]]; then
    CLOUDFLARE_DOMAIN_NAME=""
    CLOUDFLARE_BASE_SUBDOMAIN=""
    CLOUDFLARE_API_TOKEN=""
  fi
  CLOUDFLARE_TOKEN_ENCRYPTION_KEY="${CLOUDFLARE_TOKEN_ENCRYPTION_KEY:-$(python3 - <<'PY2'
import os, base64
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY2
)}"

  LOCAL_NODE_ENABLED="$(parse_bool "${LOCAL_NODE_ENABLED:-true}")"
  LOCAL_SERVER_NAME="${LOCAL_SERVER_NAME:-local}"
  LOCAL_AGENT_LISTEN_HOST="${LOCAL_AGENT_LISTEN_HOST:-127.0.0.1}"
  LOCAL_AGENT_LISTEN_PORT="${LOCAL_AGENT_LISTEN_PORT:-8787}"
  LOCAL_TRANSPORT_MODE="ws"
  LOCAL_WS_PATH="${LOCAL_WS_PATH:-/ws}"
  LOCAL_REALITY_SERVER_NAME="${LOCAL_REALITY_SERVER_NAME:-www.cloudflare.com}"
  LOCAL_REALITY_DEST="${LOCAL_REALITY_DEST:-${LOCAL_REALITY_SERVER_NAME}:443}"
  LOCAL_FINGERPRINT="${LOCAL_FINGERPRINT:-chrome}"
  LOCAL_XRAY_PORT="${LOCAL_XRAY_PORT:-443}"
  LOCAL_REALITY_PORT="${LOCAL_REALITY_PORT:-8443}"
  LOCAL_XRAY_API_PORT="${LOCAL_XRAY_API_PORT:-10085}"
  LOCAL_AGENT_API_TOKEN="${LOCAL_AGENT_API_TOKEN:-}"
  LOCAL_AGENT_API_URL=""
  LOCAL_PUBLIC_HOST="$(first_nonempty "${LOCAL_PUBLIC_HOST:-}" "$detected_public_ip" "$(hostname -f 2>/dev/null || true)" "$(hostname 2>/dev/null || true)" || true)"
  LOCAL_HOST_MODE="${LOCAL_HOST_MODE:-$(infer_host_mode "$LOCAL_PUBLIC_HOST")}"

  if [[ "$LOCAL_NODE_ENABLED" == "true" ]]; then
    if [[ -z "$LOCAL_AGENT_API_TOKEN" ]]; then
      LOCAL_AGENT_API_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
    fi
    LOCAL_AGENT_API_URL="http://127.0.0.1:${LOCAL_AGENT_LISTEN_PORT}"
    if [[ "$LOCAL_HOST_MODE" == "domain" && -n "$LOCAL_PUBLIC_HOST" ]] && ! resolve_host_ready "$LOCAL_PUBLIC_HOST"; then
      echo "Warning: local node domain does not resolve yet: $LOCAL_PUBLIC_HOST"
    fi
  else
    LOCAL_SERVER_NAME="local"
    LOCAL_AGENT_API_URL=""
    LOCAL_AGENT_API_TOKEN=""
    LOCAL_PUBLIC_HOST=""
    LOCAL_HOST_MODE=""
  fi
}

telegram_bot_enabled() {
  [[ -n "${BOT_TOKEN:-}" ]]
}

show_bot_token_help() {
  printf '%s%s📌 توکن ربات تلگرام / Telegram bot token%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چیزی که لازم داری / What you need:%s توکن HTTP API ربات تلگرام.
' "$C_YELLOW" "$C_RESET"
  printf '  %s• از کجا بگیری / Where to get it: open Telegram, chat with BotFather, run /newbot (or open your existing bot), then copy the token.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نمونه درست / Correct format example:%s 123456789:AAExampleTokenValue

' "$C_YELLOW" "$C_RESET"
}

show_cloudflare_token_help() {
  printf '%s%s☁️  توکن API کلودفلر / Cloudflare API token%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چیزی که لازم داری / What you need: a Cloudflare API token, not the Global API Key.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• از کجا بگیری / Where to get it: Cloudflare Dashboard → My Profile → API Tokens → Create Token.%s
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نوع پیشنهادی / Recommended type:%s Custom Token
' "$C_YELLOW" "$C_RESET"
  printf '  %s• دسترسی‌های لازم / Required permissions:%s
' "$C_YELLOW" "$C_RESET"
  printf '      - Zone / Zone / Read
'
  printf '      - Zone / DNS / Edit
'
  printf '      - Account / Cloudflare Tunnel / Edit
'
  printf '  %s• نکته مهم / Important:%s توکن باید به همان اکانت و دامنه‌ای دسترسی داشته باشد که پایین وارد می‌کنی.

' "$C_YELLOW" "$C_RESET"
}

show_domain_help() {
  printf '%s%s🌐 دامنه اصلی / Domain%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '  %s• چه چیزی وارد شود / What to enter:%s دامنه اصلی که از قبل داخل Cloudflare اضافه شده است.
' "$C_YELLOW" "$C_RESET"
  printf '  %s• نمونه درست / Correct example:%s example.com
' "$C_YELLOW" "$C_RESET"
  printf '  %s• وارد نکن / Do not enter:%s https://example.com ، sub.example.com ، example.com/test

' "$C_YELLOW" "$C_RESET"
}

read_visible_input() {
  local prompt="$1"
  local result_var="$2"
  local value=""
  if (( UI_TTY )); then
    printf ' %s%s%s' "$C_BOLD$C_GREEN" "$prompt" "$C_RESET"
    read -r value || true
  else
    read -r -p "${prompt}" value || true
  fi
  printf -v "$result_var" '%s' "$value"
}

normalize_domain_value() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]'
}

domain_format_error() {
  local domain
  domain="$(normalize_domain_value "$1")"
  if [[ -z "$domain" ]]; then
    printf 'Domain cannot be empty.'
    return 0
  fi
  if [[ "$domain" == *"://"* ]]; then
    printf 'Use only the root domain, without http:// or https://.'
    return 0
  fi
  if [[ "$domain" == */* ]]; then
    printf 'Do not include any path. Use only the root domain, مثل example.com.'
    return 0
  fi
  if [[ "$domain" == *"*"* ]]; then
    printf 'Wildcard domains are not accepted here. Enter the root domain only.'
    return 0
  fi
  if [[ "$domain" != *.* ]]; then
    printf 'This does not look like a root domain. Example: example.com'
    return 0
  fi
  if [[ ! "$domain" =~ ^[a-z0-9.-]+$ ]]; then
    printf 'The domain contains invalid characters. Use letters, numbers, dots, and hyphens only.'
    return 0
  fi
  if [[ "$domain" =~ ^[.-] || "$domain" =~ [.-]$ || "$domain" =~ \.\. || "$domain" =~ -- ]]; then
    printf 'The domain format is not valid. Example: example.com'
    return 0
  fi
  return 1
}

telegram_bot_enabled() {
  [[ -n "${BOT_TOKEN:-}" ]]
}

validate_bot_token_once() {
  local payload response http_code description error_code username first_name
  VALIDATION_ERROR=""
  VALIDATION_SUCCESS=""
  VALIDATION_INVALID_FIELD=""
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    VALIDATION_ERROR='Telegram bot token is empty.'
    VALIDATION_INVALID_FIELD='bot_token'
    return 1
  fi

  status_note 'Telegram API: checking BOT_TOKEN over IPv4'
  payload="$(api_json_get_ipv4 "https://api.telegram.org/bot${BOT_TOKEN}/getMe")"
  if [[ -z "$payload" ]]; then
    set_fail_hint 'Telegram API unreachable (check DNS, IPv4 egress, or CA certificates)'
    VALIDATION_ERROR='The server could not reach api.telegram.org, so the bot token could not be verified right now.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi

  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    VALIDATION_ERROR='Telegram API returned an empty response. This usually means DNS/TLS/egress trouble or a timed out request.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi

  if ! printf '%s' "$response" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    description="$(printf '%s' "$response" | sed -n 's/.*"description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    error_code="$(printf '%s' "$response" | sed -n 's/.*"error_code"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n1)"
    description="${description:-unknown Telegram API error}"
    error_code="${error_code:-${http_code:-unknown}}"
    VALIDATION_ERROR="This is not a valid Telegram bot token (${error_code}: ${description})."
    VALIDATION_INVALID_FIELD='bot_token'
    return 1
  fi

  username="$(printf '%s' "$response" | sed -n 's/.*"username"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  first_name="$(printf '%s' "$response" | sed -n 's/.*"first_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  if [[ -n "$username" ]]; then
    VALIDATION_SUCCESS="This Telegram bot token is correct. Bot username: @${username}"
  elif [[ -n "$first_name" ]]; then
    VALIDATION_SUCCESS="This Telegram bot token is correct. Bot name: ${first_name}"
  else
    VALIDATION_SUCCESS='This Telegram bot token is correct.'
  fi
  return 0
}

prompt_for_bot_token() {
  local rc
  while true; do
    show_bot_token_help
    read_visible_input '🤖 توکن ربات تلگرام / Telegram bot token: ' BOT_TOKEN_INPUT
    BOT_TOKEN="${BOT_TOKEN_INPUT:-}"
    validate_bot_token_once
    rc=$?
    if (( rc == 0 )); then
      printf '✓ %s\n\n' "$VALIDATION_SUCCESS"
      return 0
    fi
    if (( rc == 2 )); then
      echo "ERROR: $VALIDATION_ERROR"
      return 1
    fi
    printf '✗ %s\n' "$VALIDATION_ERROR"
    echo 'Please copy the token again from BotFather and try once more.'
    echo
  done
}

validate_cloudflare_inputs_once() {
  local payload response http_code domain zone_id account_id tunnel_ok error_message
  VALIDATION_ERROR=""
  VALIDATION_SUCCESS=""
  VALIDATION_INVALID_FIELD=""
  domain="$(normalize_domain_value "${CLOUDFLARE_DOMAIN_NAME:-}")"
  CLOUDFLARE_DOMAIN_NAME="$domain"
  if [[ -z "$domain" && -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    CLOUDFLARE_ENABLED='false'
    VALIDATION_SUCCESS='Cloudflare automation is skipped.'
    return 0
  fi
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    VALIDATION_ERROR='Cloudflare API token is empty.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  if error_message="$(domain_format_error "$domain")"; then
    VALIDATION_ERROR="$error_message"
    VALIDATION_INVALID_FIELD='cloudflare_domain'
    return 1
  fi
  status_note "Cloudflare API: checking zone ${domain} over IPv4"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones?name=${domain}" "${CLOUDFLARE_API_TOKEN}")"
  if [[ -z "$payload" ]]; then
    set_fail_hint 'Cloudflare API unreachable (check DNS, IPv4 egress, or CA certificates)'
    VALIDATION_ERROR='The server could not reach api.cloudflare.com, so the Cloudflare values could not be verified right now.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi
  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    VALIDATION_ERROR='Cloudflare API returned an empty response. This usually means DNS/TLS/egress trouble or a timed out request.'
    VALIDATION_INVALID_FIELD='network'
    return 2
  fi
  mapfile -t cf_parts < <(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('json_error')
    print('invalid JSON from Cloudflare API')
    print('')
    print('')
    raise SystemExit(0)
if not data.get('success'):
    errors = data.get('errors') or []
    msg = '; '.join(str(item.get('message') or item) for item in errors) or 'unknown Cloudflare API error'
    print('api_error')
    print(msg)
    print('')
    print('')
    raise SystemExit(0)
rows = data.get('result') or []
if not rows:
    print('zone_missing')
    print('domain not found in Cloudflare account')
    print('')
    print('')
    raise SystemExit(0)
row = rows[0]
print('ok')
print(row.get('id') or '')
print(((row.get('account') or {}).get('id')) or '')
print('')
PY2
)
  case "${cf_parts[0]:-json_error}" in
    ok)
      zone_id="${cf_parts[1]:-}"
      account_id="${cf_parts[2]:-}"
      ;;
    zone_missing)
      VALIDATION_ERROR='This domain was not found in the Cloudflare account behind the provided API token.'
      VALIDATION_INVALID_FIELD='cloudflare_domain'
      return 1
      ;;
    api_error)
      error_message="${cf_parts[1]:-invalid Cloudflare response}"
      if printf '%s' "$error_message" | grep -Eqi 'auth|token|permission|forbidden|unauthorized'; then
        VALIDATION_INVALID_FIELD='cloudflare_token'
        VALIDATION_ERROR="This Cloudflare API token is not correct for this request: ${error_message}"
      else
        VALIDATION_INVALID_FIELD='cloudflare_token'
        VALIDATION_ERROR="Cloudflare rejected the API token or request: ${error_message}"
      fi
      return 1
      ;;
    *)
      error_message="${cf_parts[1]:-invalid Cloudflare response}"
      VALIDATION_INVALID_FIELD='cloudflare_token'
      VALIDATION_ERROR="Cloudflare validation failed (${http_code:-unknown}): ${error_message}"
      return 1
      ;;
  esac
  if [[ -z "$account_id" ]]; then
    status_note "Cloudflare API: resolving account id for ${domain}"
    payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones/${zone_id}" "${CLOUDFLARE_API_TOKEN}")"
    response="${payload%$'\n'*}"
    account_id="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('')
    raise SystemExit(0)
print((((data.get('result') or {}).get('account') or {}).get('id')) or '')
PY2
)"
  fi
  if [[ -z "$account_id" ]]; then
    VALIDATION_ERROR='Cloudflare zone resolved, but the account id is missing.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  status_note "Cloudflare API: checking Tunnel permission on account ${account_id}"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/accounts/${account_id}/cfd_tunnel?is_deleted=false&page=1&per_page=1" "${CLOUDFLARE_API_TOKEN}")"
  response="${payload%$'\n'*}"
  tunnel_ok="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('no')
    raise SystemExit(0)
print('yes' if data.get('success') else 'no')
PY2
)"
  if [[ "$tunnel_ok" != 'yes' ]]; then
    VALIDATION_ERROR='This Cloudflare API token can see the zone, but it does not have Cloudflare Tunnel permission.'
    VALIDATION_INVALID_FIELD='cloudflare_token'
    return 1
  fi
  status_note "Cloudflare API: access OK for ${domain}"
  CLOUDFLARE_ENABLED='true'
  VALIDATION_SUCCESS="This Cloudflare API token and domain are correct. Zone: ${domain}"
  return 0
}

prompt_for_cloudflare_inputs() {
  local rc
  while true; do
    show_cloudflare_token_help
    if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
      read_visible_input '☁️  توکن API کلودفلر / Cloudflare API token: ' CLOUDFLARE_API_TOKEN_INPUT
      CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN_INPUT:-}"
    else
      printf 'توکن فعلی کلودفلر ثبت شده است و با دامنه پایین بررسی می‌شود. / Current Cloudflare API token is set. It will be verified with the domain below.\n'
    fi
    show_domain_help
    if [[ -z "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
      read_visible_input '🌐 دامنه اصلی / Root domain for subdomains: ' CLOUDFLARE_DOMAIN_NAME_INPUT
      CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME_INPUT:-}"
    else
      printf 'دامنه فعلی / Current domain is: %s\n' "$CLOUDFLARE_DOMAIN_NAME"
    fi
    validate_cloudflare_inputs_once
    rc=$?
    if (( rc == 0 )); then
      printf '✓ %s\n\n' "$VALIDATION_SUCCESS"
      return 0
    fi
    if (( rc == 2 )); then
      echo "ERROR: $VALIDATION_ERROR"
      return 1
    fi
    printf '✗ %s\n' "$VALIDATION_ERROR"
    case "$VALIDATION_INVALID_FIELD" in
      cloudflare_domain)
        echo 'Please enter the root domain again. Example: example.com'
        CLOUDFLARE_DOMAIN_NAME=''
        ;;
      cloudflare_token)
        echo 'Please create or copy the Cloudflare API token again, then paste it here.'
        CLOUDFLARE_API_TOKEN=''
        ;;
      *)
        CLOUDFLARE_API_TOKEN=''
        CLOUDFLARE_DOMAIN_NAME=''
        ;;
    esac
    echo
  done
}

prompt_for_install_inputs() {
  if [[ ! -t 0 ]]; then
    return 0
  fi
  if [[ -n "${BOT_TOKEN:-}" && -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
    return 0
  fi
  if (( UI_TTY )); then
    printf '\033[H\033[2J'
    printf '%s%sAutomatic setup%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
    printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  fi
  cat <<'EOF'
فقط سه مقدار لازم است.
Only three values are needed.

نصاب هر مقدار را همان لحظه بررسی می‌کند و می‌گوید درست است یا نه.
The installer will verify each one and tell you if it is correct.

بعد از آن، ساخت Tunnel و تنظیم DNS کلودفلر خودکار انجام می‌شود.
After that, Cloudflare tunnel and DNS are configured automatically.

اولین چت خصوصی که /start بفرستد، خودکار Owner می‌شود.
The first private chat that sends /start becomes owner automatically.

EOF
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    prompt_for_bot_token || exit 1
  else
    validate_bot_token_once
    case $? in
      0) printf '✓ %s\n\n' "$VALIDATION_SUCCESS" ;;
      2) echo "ERROR: $VALIDATION_ERROR"; exit 1 ;;
      *) echo "ERROR: $VALIDATION_ERROR"; BOT_TOKEN=''; prompt_for_bot_token || exit 1 ;;
    esac
  fi
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_DOMAIN_NAME:-}" ]]; then
    CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
    CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-}"
    prompt_for_cloudflare_inputs || exit 1
  else
    validate_cloudflare_inputs_once
    case $? in
      0) printf '✓ %s\n\n' "$VALIDATION_SUCCESS" ;;
      2) echo "ERROR: $VALIDATION_ERROR"; exit 1 ;;
      *) echo "ERROR: $VALIDATION_ERROR"; CLOUDFLARE_API_TOKEN=''; CLOUDFLARE_DOMAIN_NAME=''; prompt_for_cloudflare_inputs || exit 1 ;;
    esac
  fi
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  CURRENT_LABEL="Installer inputs captured"
  CURRENT_STATUS="Ready"
  draw_screen
}

validate_bot_token() {
  local rc
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    return 0
  fi
  validate_bot_token_once
  rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  if (( rc == 2 )); then
    echo "ERROR: $VALIDATION_ERROR"
    echo 'Check outbound network access to api.telegram.org or rerun later.'
    exit 1
  fi
  echo "ERROR: $VALIDATION_ERROR"
  exit 1
}

prepare_install_inputs() {
  BOT_TOKEN="${BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
  CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}"
  CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-${DOMAIN:-}}"
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-vpn}"
  load_saved_bot_token
  load_saved_cloudflare_inputs
  prompt_for_install_inputs
}

api_json_get_ipv4() {
  local url="$1"
  local bearer_token="${2:-}"
  local payload
  local -a args
  args=(-4 -sS --connect-timeout 5 --max-time 12 --retry 0 -H 'Content-Type: application/json' -w $'
%{http_code}')
  if [[ -n "$bearer_token" ]]; then
    args+=(-H "Authorization: Bearer ${bearer_token}")
  fi
  payload="$(run_with_timeout 20 curl "${args[@]}" "$url" 2>/dev/null || true)"
  printf '%s' "$payload"
}

validate_cloudflare_inputs() {
  local payload response http_code domain zone_id account_id tunnel_ok error_message
  domain="$(printf '%s' "${CLOUDFLARE_DOMAIN_NAME:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  CLOUDFLARE_DOMAIN_NAME="$domain"
  if [[ -z "$domain" && -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    CLOUDFLARE_ENABLED='false'
    return 0
  fi
  if [[ -z "$domain" || -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    echo 'ERROR: Cloudflare setup needs both CLOUDFLARE_API_TOKEN and CLOUDFLARE_DOMAIN_NAME.'
    echo 'Provide both values or leave both empty to skip Cloudflare automation.'
    exit 1
  fi
  status_note "Cloudflare API: checking zone ${domain} over IPv4"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones?name=${domain}" "${CLOUDFLARE_API_TOKEN}")"
  if [[ -z "$payload" ]]; then
    set_fail_hint 'Cloudflare API unreachable (check DNS, IPv4 egress, or CA certificates)'
    echo 'ERROR: Could not reach the Cloudflare API to validate the zone.'
    echo 'Check outbound network access to api.cloudflare.com and rerun the installer.'
    exit 1
  fi
  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    echo 'ERROR: Cloudflare API returned an empty response while validating the zone.
This usually means DNS/TLS/egress trouble or a timed out request.'
    exit 1
  fi
  mapfile -t cf_parts < <(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('json_error')
    print('invalid JSON from Cloudflare API')
    print('')
    print('')
    raise SystemExit(0)
if not data.get('success'):
    errors = data.get('errors') or []
    msg = '; '.join(str(item.get('message') or item) for item in errors) or 'unknown Cloudflare API error'
    print('api_error')
    print(msg)
    print('')
    print('')
    raise SystemExit(0)
rows = data.get('result') or []
if not rows:
    print('zone_missing')
    print('domain not found in Cloudflare account')
    print('')
    print('')
    raise SystemExit(0)
row = rows[0]
print('ok')
print(row.get('id') or '')
print(((row.get('account') or {}).get('id')) or '')
print('')
PY2
)
  case "${cf_parts[0]:-json_error}" in
    ok)
      zone_id="${cf_parts[1]:-}"
      account_id="${cf_parts[2]:-}"
      ;;
    *)
      error_message="${cf_parts[1]:-invalid Cloudflare response}"
      set_fail_hint "Cloudflare validation failed for ${domain}: ${error_message}"
      echo "ERROR: Cloudflare validation failed (${http_code:-unknown}): ${error_message}"
      exit 1
      ;;
  esac
  if [[ -z "$account_id" ]]; then
    status_note "Cloudflare API: resolving account id for ${domain}"
    payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/zones/${zone_id}" "${CLOUDFLARE_API_TOKEN}")"
    response="${payload%$'\n'*}"
    account_id="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('')
    raise SystemExit(0)
print((((data.get('result') or {}).get('account') or {}).get('id')) or '')
PY2
)"
  fi
  if [[ -z "$account_id" ]]; then
    set_fail_hint 'Cloudflare zone resolved, but account id is missing'
    echo 'ERROR: Cloudflare account id could not be resolved from the selected zone.'
    exit 1
  fi
  status_note "Cloudflare API: checking Tunnel permission on account ${account_id}"
  payload="$(api_json_get_ipv4 "https://api.cloudflare.com/client/v4/accounts/${account_id}/cfd_tunnel?is_deleted=false&page=1&per_page=1" "${CLOUDFLARE_API_TOKEN}")"
  response="${payload%$'\n'*}"
  tunnel_ok="$(python3 - "$response" <<'PY2'
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    print('no')
    raise SystemExit(0)
print('yes' if data.get('success') else 'no')
PY2
)"
  if [[ "$tunnel_ok" != 'yes' ]]; then
    set_fail_hint 'Cloudflare token can see the zone, but Tunnel permission is missing'
    echo 'ERROR: Cloudflare token is valid for the zone, but tunnel access is missing.'
    echo 'Grant Cloudflare Tunnel read/edit permissions on the same account and rerun the installer.'
    exit 1
  fi
  status_note "Cloudflare API: access OK for ${domain}"
  CLOUDFLARE_ENABLED='true'
}

ask_config() {
  init_config_defaults
  ADMIN_CHAT_IDS=""
}

prepare_dirs() {
  mkdir -p "$APP_APP_DIR" "$APP_AGENT_APP_DIR" "$APP_DATA_DIR" "$APP_LOG_DIR" "$APP_QR_DIR" "$APP_BACKUP_DIR"
}

copy_code() {
  cp -R "$SCRIPT_DIR/master_app/." "$APP_APP_DIR/"
  cp -R "$SCRIPT_DIR/agent_app/." "$APP_AGENT_APP_DIR/"
}

write_config() {
  export APP_DATA_DIR APP_LOG_DIR APP_QR_DIR APP_BACKUP_DIR APP_VERSION BOT_TOKEN SCHEDULER_INTERVAL AGENT_TIMEOUT WARN_DAYS_LEFT WARN_USAGE_PERCENT BACKUP_INTERVAL_HOURS BACKUP_RETENTION CLOUDFLARE_ENABLED CLOUDFLARE_DOMAIN_NAME CLOUDFLARE_BASE_SUBDOMAIN CLOUDFLARE_TOKEN_ENCRYPTION_KEY SUBSCRIPTION_BASE_URL SUBSCRIPTION_BIND_HOST SUBSCRIPTION_BIND_PORT LOCAL_NODE_ENABLED LOCAL_SERVER_NAME LOCAL_AGENT_API_URL LOCAL_AGENT_API_TOKEN
  python3 - <<'PY'
import json
import os
from pathlib import Path
cfg = {
    'bot_token': os.environ.get('BOT_TOKEN', ''),
    'admin_chat_ids': '',
    'database_path': os.path.join(os.environ['APP_DATA_DIR'], 'master.db'),
    'log_path': os.path.join(os.environ['APP_LOG_DIR'], 'master.log'),
    'qr_dir': os.environ['APP_QR_DIR'],
    'backup_dir': os.environ['APP_BACKUP_DIR'],
    'scheduler_interval_seconds': int(os.environ['SCHEDULER_INTERVAL']),
    'agent_timeout_seconds': int(os.environ['AGENT_TIMEOUT']),
    'warn_days_left': int(os.environ['WARN_DAYS_LEFT']),
    'warn_usage_percent': int(os.environ['WARN_USAGE_PERCENT']),
    'backup_interval_hours': int(os.environ['BACKUP_INTERVAL_HOURS']),
    'backup_retention': int(os.environ['BACKUP_RETENTION']),
    'quick_snapshot_retention': 20,
    'warn_days_schedule': '7,3,1',
    'warn_usage_schedule': '80,95',
    'package_version': os.environ['APP_VERSION'],
    'cloudflare_enabled': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true',
    'cloudflare_domain_name': os.environ.get('CLOUDFLARE_DOMAIN_NAME', ''),
    'cloudflare_zone_name': os.environ.get('CLOUDFLARE_DOMAIN_NAME', ''),
    'cloudflare_base_subdomain': os.environ.get('CLOUDFLARE_BASE_SUBDOMAIN', ''),
    'cloudflare_token_encryption_key': os.environ.get('CLOUDFLARE_TOKEN_ENCRYPTION_KEY', ''),
    'cloudflare_dns_proxied': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true',
    'cloudflare_tunnel_enabled': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true',
    'cloudflare_argo_enabled': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true',
    'cloudflare_auto_sync_enabled': True,
    'cloudflare_auto_sync_interval_minutes': 30,
    'notify_on_server_status_change': True,
    'subscription_base_url': os.environ.get('SUBSCRIPTION_BASE_URL', ''),
    'subscription_bind_host': os.environ.get('SUBSCRIPTION_BIND_HOST', '0.0.0.0'),
    'subscription_bind_port': int(os.environ['SUBSCRIPTION_BIND_PORT']),
    'local_node_enabled': os.environ.get('LOCAL_NODE_ENABLED', 'false').lower() == 'true',
    'local_server_name': os.environ.get('LOCAL_SERVER_NAME', 'local'),
    'local_agent_api_url': os.environ.get('LOCAL_AGENT_API_URL', ''),
    'local_agent_api_token': os.environ.get('LOCAL_AGENT_API_TOKEN', ''),
}
path = Path(os.environ['APP_DATA_DIR']) / 'config.json'
path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
path.chmod(0o600)
Path(cfg['database_path']).parent.mkdir(parents=True, exist_ok=True)
Path(cfg['database_path']).touch(exist_ok=True)
PY
  persist_bot_token

  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    mkdir -p "$APP_BACKUP_DIR/local-agent"
    export XRAY_CONFIG_PATH LOCAL_SERVER_NAME LOCAL_AGENT_API_TOKEN LOCAL_AGENT_LISTEN_HOST LOCAL_AGENT_LISTEN_PORT LOCAL_PUBLIC_HOST LOCAL_HOST_MODE LOCAL_XRAY_PORT LOCAL_REALITY_PORT LOCAL_XRAY_API_PORT LOCAL_TRANSPORT_MODE LOCAL_WS_PATH LOCAL_REALITY_SERVER_NAME LOCAL_REALITY_DEST LOCAL_FINGERPRINT
    python3 - <<'PY'
import json
import os
from pathlib import Path
cfg = {
    'agent_name': os.environ['LOCAL_SERVER_NAME'],
    'agent_token': os.environ['LOCAL_AGENT_API_TOKEN'],
    'allowed_sources': '127.0.0.1/32',
    'agent_listen_host': os.environ['LOCAL_AGENT_LISTEN_HOST'],
    'agent_listen_port': int(os.environ['LOCAL_AGENT_LISTEN_PORT']),
    'public_host': os.environ['LOCAL_PUBLIC_HOST'],
    'host_mode': os.environ['LOCAL_HOST_MODE'],
    'xray_port': int(os.environ['LOCAL_XRAY_PORT']),
    'simple_port': int(os.environ['LOCAL_XRAY_PORT']),
    'reality_port': int(os.environ['LOCAL_REALITY_PORT']),
    'xray_api_port': int(os.environ['LOCAL_XRAY_API_PORT']),
    'xray_config_path': os.environ['XRAY_CONFIG_PATH'],
    'transport_mode': os.environ['LOCAL_TRANSPORT_MODE'],
    'ws_path': os.environ['LOCAL_WS_PATH'],
    'reality_server_name': os.environ['LOCAL_REALITY_SERVER_NAME'],
    'reality_dest': os.environ['LOCAL_REALITY_DEST'],
    'reality_public_key': '',
    'reality_private_key': '',
    'reality_short_id': '',
    'fingerprint': os.environ['LOCAL_FINGERPRINT'],
    'log_path': os.path.join(os.environ['APP_LOG_DIR'], 'local-agent.log'),
    'backup_dir': os.path.join(os.environ['APP_BACKUP_DIR'], 'local-agent'),
    'xray_access_log': '/var/log/xray/access.log',
    'xray_error_log': '/var/log/xray/error.log',
    'rate_limit_window_seconds': 60,
    'rate_limit_max_requests': 120,
}
path = Path(os.environ['APP_DATA_DIR']) / 'local-agent-config.json'
path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
path.chmod(0o600)
PY
  fi
}

setup_venv() {
  local req_hash state_file wheel_state_file venv_python_tag wheel_state expected_wheel_state
  mkdir -p "$INSTALLER_STATE_DIR" "$PIP_CACHE_DIR" "$WHEELHOUSE_DIR"
  state_file="$INSTALLER_STATE_DIR/master-requirements.sha256"
  wheel_state_file="$INSTALLER_STATE_DIR/master-wheelhouse.sha256"
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

bootstrap_cloudflare() {
  if [[ "$CLOUDFLARE_ENABLED" == true ]]; then
    CF_API_TOKEN="$CLOUDFLARE_API_TOKEN" SAHAR_CONFIG="$APP_DATA_DIR/config.json" "$VENV_DIR/bin/python" "$APP_APP_DIR/bootstrap_cloudflare.py"
  fi
}

write_services() {
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    cat > "/etc/systemd/system/${BOT_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Master Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_APP_DIR
Environment=SAHAR_CONFIG=$APP_DATA_DIR/config.json
ExecStart=$VENV_DIR/bin/python $APP_APP_DIR/bot.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
SERVICE

    cat > "/etc/systemd/system/${SUB_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Master Subscription API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_APP_DIR
Environment=SAHAR_CONFIG=$APP_DATA_DIR/config.json
ExecStart=$VENV_DIR/bin/gunicorn -w 2 -k gthread --threads 4 --bind ${SUBSCRIPTION_BIND_HOST}:${SUBSCRIPTION_BIND_PORT} subscription_api:APP
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
SERVICE

    cat > "/etc/systemd/system/${SCHED_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Master Scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_APP_DIR
Environment=SAHAR_CONFIG=$APP_DATA_DIR/config.json
ExecStart=$VENV_DIR/bin/python $APP_APP_DIR/scheduler.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
SERVICE

    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      cat > "/etc/systemd/system/${LOCAL_AGENT_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Local Agent API
After=network-online.target xray.service
Wants=network-online.target
Requires=xray.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$APP_AGENT_APP_DIR
Environment=SAHAR_CONFIG=$APP_DATA_DIR/local-agent-config.json
ExecStart=$VENV_DIR/bin/gunicorn -w 2 -k gthread --threads 4 --bind ${LOCAL_AGENT_LISTEN_HOST}:${LOCAL_AGENT_LISTEN_PORT} agent_api:APP
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
    fi
  else
    cat > "/etc/init.d/${BOT_SERVICE_NAME}" <<SERVICE
#!/sbin/openrc-run
name="${BOT_SERVICE_NAME}"
description="Sahar Master Telegram Bot"
command="${VENV_DIR}/bin/python"
command_args="${APP_APP_DIR}/bot.py"
command_user="${SERVICE_USER}:${SERVICE_USER}"
directory="${APP_APP_DIR}"
pidfile="/run/${BOT_SERVICE_NAME}.pid"
command_background=true
output_log="${APP_LOG_DIR}/bot-service.log"
error_log="${APP_LOG_DIR}/bot-service.err"
depend() { need net; }
start_pre() { export SAHAR_CONFIG="${APP_DATA_DIR}/config.json"; }
SERVICE
    chmod +x "/etc/init.d/${BOT_SERVICE_NAME}"

    cat > "/etc/init.d/${SUB_SERVICE_NAME}" <<SERVICE
#!/sbin/openrc-run
name="${SUB_SERVICE_NAME}"
description="Sahar Master Subscription API"
command="${VENV_DIR}/bin/gunicorn"
command_args="-w 2 -k gthread --threads 4 --bind ${SUBSCRIPTION_BIND_HOST}:${SUBSCRIPTION_BIND_PORT} subscription_api:APP"
command_user="${SERVICE_USER}:${SERVICE_USER}"
directory="${APP_APP_DIR}"
pidfile="/run/${SUB_SERVICE_NAME}.pid"
command_background=true
output_log="${APP_LOG_DIR}/subscription-service.log"
error_log="${APP_LOG_DIR}/subscription-service.err"
depend() { need net; }
start_pre() { export SAHAR_CONFIG="${APP_DATA_DIR}/config.json"; }
SERVICE
    chmod +x "/etc/init.d/${SUB_SERVICE_NAME}"

    cat > "/etc/init.d/${SCHED_SERVICE_NAME}" <<SERVICE
#!/sbin/openrc-run
name="${SCHED_SERVICE_NAME}"
description="Sahar Master Scheduler"
command="${VENV_DIR}/bin/python"
command_args="${APP_APP_DIR}/scheduler.py"
command_user="${SERVICE_USER}:${SERVICE_USER}"
directory="${APP_APP_DIR}"
pidfile="/run/${SCHED_SERVICE_NAME}.pid"
command_background=true
output_log="${APP_LOG_DIR}/scheduler-service.log"
error_log="${APP_LOG_DIR}/scheduler-service.err"
depend() { need net; }
start_pre() { export SAHAR_CONFIG="${APP_DATA_DIR}/config.json"; }
SERVICE
    chmod +x "/etc/init.d/${SCHED_SERVICE_NAME}"

    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      cat > "/etc/init.d/${LOCAL_AGENT_SERVICE_NAME}" <<SERVICE
#!/sbin/openrc-run
name="${LOCAL_AGENT_SERVICE_NAME}"
description="Sahar Local Agent API"
command="${VENV_DIR}/bin/gunicorn"
command_args="-w 2 -k gthread --threads 4 --bind ${LOCAL_AGENT_LISTEN_HOST}:${LOCAL_AGENT_LISTEN_PORT} agent_api:APP"
directory="${APP_AGENT_APP_DIR}"
pidfile="/run/${LOCAL_AGENT_SERVICE_NAME}.pid"
command_background=true
output_log="${APP_LOG_DIR}/local-agent-service.log"
error_log="${APP_LOG_DIR}/local-agent-service.err"
depend() { need net xray; }
start_pre() { export SAHAR_CONFIG="${APP_DATA_DIR}/local-agent-config.json"; }
SERVICE
      chmod +x "/etc/init.d/${LOCAL_AGENT_SERVICE_NAME}"
    fi
  fi
}


write_logrotate() {
  cat > /etc/logrotate.d/sahar-master <<EOF2
$APP_LOG_DIR/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
EOF2
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
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 300 -H "User-Agent: Sahar/0.1.72" "$download_url" -o "$output_zip"; then
    set_fail_hint "Failed to download Xray archive"
    return 1
  fi
  digest_file="$(mktemp)"
  if curl -fL --retry 2 --retry-delay 2 --connect-timeout 15 --max-time 60 -H "User-Agent: Sahar/0.1.72" "$digest_url" -o "$digest_file"; then
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


install_xray_if_needed() {
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    if command_exists xray; then
      set_step_progress 100 "Xray already installed"
      return 0
    fi
    status_note "Installing Xray"
    install_xray_alpine
  else
    set_step_progress 100 "Local Xray node is disabled"
  fi
}

enable_services() {
  chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"
  mkdir -p "$APP_LOG_DIR"
  touch "$APP_LOG_DIR/master.log" "$APP_LOG_DIR/error.log" "$APP_LOG_DIR/bot.log" "$APP_LOG_DIR/scheduler.log" "$APP_LOG_DIR/provision.log"
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    touch "$APP_LOG_DIR/local-agent.log"
  fi
  chown "$SERVICE_USER:$SERVICE_GROUP" "$APP_LOG_DIR"/*.log 2>/dev/null || true
  chown "$SERVICE_USER:$SERVICE_GROUP" "$APP_DATA_DIR"/*.db 2>/dev/null || true
  chmod 664 "$APP_LOG_DIR"/*.log 2>/dev/null || true
  chmod 775 "$APP_LOG_DIR"
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    systemctl daemon-reload
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      systemctl enable xray --now
      systemctl enable "$LOCAL_AGENT_SERVICE_NAME" --now
      wait_for_tcp_listener "$LOCAL_AGENT_LISTEN_HOST" "$LOCAL_AGENT_LISTEN_PORT" 30 2
      wait_for_http_ready "$LOCAL_AGENT_API_URL/health" "$LOCAL_AGENT_API_TOKEN" 25 2 "local agent"
    fi
    systemctl enable "$SUB_SERVICE_NAME" --now
    if telegram_bot_enabled; then
      systemctl enable "$BOT_SERVICE_NAME" --now
      systemctl enable "$SCHED_SERVICE_NAME" --now
    else
      systemctl disable "$BOT_SERVICE_NAME" >/dev/null 2>&1 || true
      systemctl disable "$SCHED_SERVICE_NAME" >/dev/null 2>&1 || true
    fi
  else
    rc-update add "$SUB_SERVICE_NAME" default
    if telegram_bot_enabled; then
      rc-update add "$BOT_SERVICE_NAME" default
      rc-update add "$SCHED_SERVICE_NAME" default
    fi
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      rc-update add xray default
      rc-service xray start
      rc-update add "$LOCAL_AGENT_SERVICE_NAME" default
      rc-service "$LOCAL_AGENT_SERVICE_NAME" start
      wait_for_tcp_listener "$LOCAL_AGENT_LISTEN_HOST" "$LOCAL_AGENT_LISTEN_PORT" 30 2
      wait_for_http_ready "$LOCAL_AGENT_API_URL/health" "$LOCAL_AGENT_API_TOKEN" 25 2 "local agent"
    fi
    rc-service "$SUB_SERVICE_NAME" start
    if telegram_bot_enabled; then
      rc-service "$BOT_SERVICE_NAME" start
      rc-service "$SCHED_SERVICE_NAME" start
    fi
  fi
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    if ! SAHAR_CONFIG="$APP_DATA_DIR/config.json" "$VENV_DIR/bin/python" "$APP_APP_DIR/register_local_server.py"; then
      append_post_install_warning "Local node registration did not complete automatically. See $APP_LOG_DIR/provision.log and rerun register_local_server.py after the local agent is healthy."
    fi
  fi
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
  printf '%sMaster installed successfully.%s
' "$C_GREEN" "$C_RESET"
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    echo "Services:"
    echo "  systemctl status $BOT_SERVICE_NAME"
    echo "  systemctl status $SCHED_SERVICE_NAME"
    echo "  systemctl status $SUB_SERVICE_NAME"
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      echo "  systemctl status xray"
      echo "  systemctl status $LOCAL_AGENT_SERVICE_NAME"
      echo "Local server auto-registered as: $LOCAL_SERVER_NAME"
    fi
    echo "Logs:"
    echo "  journalctl -u $BOT_SERVICE_NAME -f"
    echo "  journalctl -u $SCHED_SERVICE_NAME -f"
    echo "  journalctl -u $SUB_SERVICE_NAME -f"
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      echo "  journalctl -u $LOCAL_AGENT_SERVICE_NAME -f"
    fi
  else
    echo "Services:"
    echo "  rc-service $BOT_SERVICE_NAME status"
    echo "  rc-service $SCHED_SERVICE_NAME status"
    echo "  rc-service $SUB_SERVICE_NAME status"
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      echo "  rc-service xray status"
      echo "  rc-service $LOCAL_AGENT_SERVICE_NAME status"
      echo "Local server auto-registered as: $LOCAL_SERVER_NAME"
    fi
    echo "Logs:"
    echo "  tail -f $APP_LOG_DIR/*.log"
  fi
  echo "Subscription base URL: $SUBSCRIPTION_BASE_URL"
  if telegram_bot_enabled; then
    echo "Send /start to the bot from a private chat."
    echo "The first private chat that reaches the bot becomes the owner automatically."
  else
    echo "Telegram bot service was not started because BOT_TOKEN is empty."
    echo "Set BOT_TOKEN in $APP_DATA_DIR/config.json or reinstall with BOT_TOKEN=..."
    echo "Then start: ${BOT_SERVICE_NAME} and ${SCHED_SERVICE_NAME}"
  fi
}


main() {
  setup_ui
  select_language
  print_banner
  require_root
  run_step "Checking system" check_os
  run_step "Running preflight checks" preflight_checks
  run_step "Installing system packages" install_packages
  prepare_install_inputs
  run_step "Validating bot token" validate_bot_token
  run_step "Validating Cloudflare access" validate_cloudflare_inputs
  run_step "Creating service account" ensure_user
  run_step "Preparing defaults" ask_config
  run_step "Creating directories" prepare_dirs
  run_step "Copying application files" copy_code
  run_step "Writing configuration" write_config
  run_step "Building Python environment" setup_venv
  run_step "Bootstrapping Cloudflare" bootstrap_cloudflare
  run_step "Installing Xray components" install_xray_if_needed
  run_step "Writing service files" write_services
  run_step "Configuring log rotation" write_logrotate
  run_step "Starting services" enable_services
  ui_newline
  print_done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
