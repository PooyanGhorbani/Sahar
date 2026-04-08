#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.39"

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

LOG_FILE="/tmp/sahar-master-installer.log"
TOTAL_STEPS=12
CURRENT_STEP=0
BAR_WIDTH=40
CURRENT_LABEL="Preparing installer"
CURRENT_STATUS="Waiting"
CURRENT_SPINNER="-"
SPINNER_INDEX=0
UI_TTY=0
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

setup_ui() {
  : > "$LOG_FILE"
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

progress_bar() {
  local done_slots pending_slots fill empty
  done_slots=$((CURRENT_STEP * BAR_WIDTH / TOTAL_STEPS))
  pending_slots=$((BAR_WIDTH - done_slots))
  fill=$(printf '%*s' "$done_slots" '')
  fill=${fill// /=}
  empty=$(printf '%*s' "$pending_slots" '')
  printf '%s%s' "$fill" "$empty"
}

draw_screen() {
  local percent step_no bar
  (( UI_TTY )) || return 0
  percent=$((CURRENT_STEP * 100 / TOTAL_STEPS))
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
  printf '%sOnly the bot token is requested. Package details stay hidden.%s
' "$C_YELLOW" "$C_RESET"
}

ui_newline() {
  printf '
'
}

spinner_loop() {
  local start_ts elapsed
  start_ts=$(date +%s)
  while true; do
    elapsed=$(( $(date +%s) - start_ts ))
    advance_spinner
    CURRENT_STATUS="Running ${CURRENT_SPINNER}  ${elapsed}s"
    draw_screen
    sleep 0.12
  done
}

run_step() {
  local label="$1" spinner_pid
  shift
  CURRENT_LABEL="$label"
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
  CURRENT_STEP=$((CURRENT_STEP + 1))
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
  if [[ "$OS_FAMILY" == "debian" ]]; then
    apt update
    apt install -y python3 python3-venv python3-pip sqlite3 curl ca-certificates tar zip unzip jq uuid-runtime dnsutils logrotate git
  else
    apk add --no-cache bash python3 py3-pip py3-virtualenv sqlite curl ca-certificates tar zip unzip jq uuidgen bind-tools logrotate shadow build-base python3-dev musl-dev linux-headers git
  fi
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
  local detected_public_ip
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

  CLOUDFLARE_ENABLED="$(parse_bool "${CLOUDFLARE_ENABLED:-false}")"
  CLOUDFLARE_DOMAIN_NAME="${CLOUDFLARE_DOMAIN_NAME:-}"
  CLOUDFLARE_BASE_SUBDOMAIN="${CLOUDFLARE_BASE_SUBDOMAIN:-}"
  CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
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

prompt_for_bot_token() {
  if [[ -n "${BOT_TOKEN:-}" ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    return 0
  fi
  if (( UI_TTY )); then
    printf '[H[2J'
    printf '%s%sTelegram bot token required%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
    printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
    printf ' Paste the BotFather token below. Input stays hidden.
'
    printf ' The first private chat that sends /start becomes owner automatically.

'
    read -rsp ' BOT_TOKEN: ' BOT_TOKEN_INPUT || true
    printf '
'
  else
    read -r -p "BOT_TOKEN: " BOT_TOKEN_INPUT || true
  fi
  BOT_TOKEN="${BOT_TOKEN_INPUT:-}"
  CURRENT_LABEL="Bot token captured"
  CURRENT_STATUS="Ready"
  draw_screen
}

validate_bot_token() {
  local payload response http_code description error_code username first_name
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    return 0
  fi

  payload="$(curl -sS --connect-timeout 10 --max-time 20 -w $'\n%{http_code}' "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null || true)"
  if [[ -z "$payload" ]]; then
    echo "ERROR: Could not reach the Telegram API to validate BOT_TOKEN."
    echo "Check outbound network access to api.telegram.org or rerun later."
    exit 1
  fi

  http_code="${payload##*$'\n'}"
  response="${payload%$'\n'*}"
  if [[ -z "$response" ]]; then
    echo "ERROR: Telegram API returned an empty response while validating BOT_TOKEN."
    exit 1
  fi

  if ! printf '%s' "$response" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    description="$(printf '%s' "$response" | sed -n 's/.*"description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    error_code="$(printf '%s' "$response" | sed -n 's/.*"error_code"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n1)"
    description="${description:-unknown Telegram API error}"
    error_code="${error_code:-${http_code:-unknown}}"
    echo "ERROR: BOT_TOKEN validation failed (${error_code}): ${description}"
    exit 1
  fi

  username="$(printf '%s' "$response" | sed -n 's/.*"username"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  first_name="$(printf '%s' "$response" | sed -n 's/.*"first_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  if [[ -n "$username" ]]; then
    :
  elif [[ -n "$first_name" ]]; then
    :
  else
    :
  fi
}

prepare_bot_token_input() {
  BOT_TOKEN="${BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
  prompt_for_bot_token
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
  cat > "$APP_DATA_DIR/config.json" <<JSON
{
  "bot_token": "$BOT_TOKEN",
  "admin_chat_ids": "",
  "database_path": "$APP_DATA_DIR/master.db",
  "log_path": "$APP_LOG_DIR/master.log",
  "qr_dir": "$APP_QR_DIR",
  "backup_dir": "$APP_BACKUP_DIR",
  "scheduler_interval_seconds": $SCHEDULER_INTERVAL,
  "agent_timeout_seconds": $AGENT_TIMEOUT,
  "warn_days_left": $WARN_DAYS_LEFT,
  "warn_usage_percent": $WARN_USAGE_PERCENT,
  "backup_interval_hours": $BACKUP_INTERVAL_HOURS,
  "backup_retention": $BACKUP_RETENTION,
  "quick_snapshot_retention": 20,
  "warn_days_schedule": "7,3,1",
  "warn_usage_schedule": "80,95",
  "package_version": "$APP_VERSION",
  "cloudflare_enabled": $CLOUDFLARE_ENABLED,
  "cloudflare_domain_name": "$CLOUDFLARE_DOMAIN_NAME",
  "cloudflare_zone_name": "$CLOUDFLARE_DOMAIN_NAME",
  "cloudflare_base_subdomain": "$CLOUDFLARE_BASE_SUBDOMAIN",
  "cloudflare_token_encryption_key": "$CLOUDFLARE_TOKEN_ENCRYPTION_KEY",
  "cloudflare_dns_proxied": false,
  "subscription_base_url": "$SUBSCRIPTION_BASE_URL",
  "subscription_bind_host": "$SUBSCRIPTION_BIND_HOST",
  "subscription_bind_port": $SUBSCRIPTION_BIND_PORT,
  "local_node_enabled": $LOCAL_NODE_ENABLED,
  "local_server_name": "$LOCAL_SERVER_NAME",
  "local_agent_api_url": "$LOCAL_AGENT_API_URL",
  "local_agent_api_token": "$LOCAL_AGENT_API_TOKEN"
}
JSON
  chmod 600 "$APP_DATA_DIR/config.json"

  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    mkdir -p "$APP_BACKUP_DIR/local-agent"
    cat > "$APP_DATA_DIR/local-agent-config.json" <<JSON
{
  "agent_name": "$LOCAL_SERVER_NAME",
  "agent_token": "$LOCAL_AGENT_API_TOKEN",
  "allowed_sources": "127.0.0.1/32",
  "agent_listen_host": "$LOCAL_AGENT_LISTEN_HOST",
  "agent_listen_port": $LOCAL_AGENT_LISTEN_PORT,
  "public_host": "$LOCAL_PUBLIC_HOST",
  "host_mode": "$LOCAL_HOST_MODE",
  "xray_port": $LOCAL_XRAY_PORT,
  "simple_port": $LOCAL_XRAY_PORT,
  "reality_port": $LOCAL_REALITY_PORT,
  "xray_api_port": $LOCAL_XRAY_API_PORT,
  "xray_config_path": "$XRAY_CONFIG_PATH",
  "transport_mode": "$LOCAL_TRANSPORT_MODE",
  "ws_path": "$LOCAL_WS_PATH",
  "reality_server_name": "$LOCAL_REALITY_SERVER_NAME",
  "reality_dest": "$LOCAL_REALITY_DEST",
  "reality_public_key": "",
  "reality_private_key": "",
  "reality_short_id": "",
  "fingerprint": "$LOCAL_FINGERPRINT",
  "log_path": "$APP_LOG_DIR/local-agent.log",
  "backup_dir": "$APP_BACKUP_DIR/local-agent",
  "xray_access_log": "/var/log/xray/access.log",
  "xray_error_log": "/var/log/xray/error.log",
  "rate_limit_window_seconds": 60,
  "rate_limit_max_requests": 120
}
JSON
    chmod 600 "$APP_DATA_DIR/local-agent-config.json"
  fi
}

setup_venv() {
  if ! python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
    if command -v virtualenv >/dev/null 2>&1; then
      virtualenv "$VENV_DIR"
    else
      python3 -m ensurepip --upgrade || true
      python3 -m venv "$VENV_DIR"
    fi
  fi
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$APP_APP_DIR/requirements.txt"
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
  local arch="$1" output_zip="$2" ua latest_url resolved_url tag tagged_url
  ua="SaharInstaller/0.1.41"
  latest_url="https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${arch}.zip"

  if curl -A "$ua" --fail --location --retry 3 --retry-delay 2 --connect-timeout 15 "$latest_url" -o "$output_zip"; then
    return 0
  fi

  resolved_url="$(curl -A "$ua" -sS -L -o /dev/null -w '%{url_effective}' https://github.com/XTLS/Xray-core/releases/latest || true)"
  tag="${resolved_url##*/tag/}"
  tag="${tag%%[/?#]*}"
  if [[ -n "$tag" && "$tag" != "$resolved_url" ]]; then
    tagged_url="https://github.com/XTLS/Xray-core/releases/download/${tag}/Xray-linux-${arch}.zip"
    if curl -A "$ua" --fail --location --retry 3 --retry-delay 2 --connect-timeout 15 "$tagged_url" -o "$output_zip"; then
      return 0
    fi
  fi

  echo "ERROR: failed to download Xray release archive from GitHub." >&2
  echo "Tried: $latest_url" >&2
  if [[ -n "${tag:-}" && "$tag" != "$resolved_url" ]]; then
    echo "Tried: $tagged_url" >&2
  fi
  echo "GitHub may be temporarily blocked or rate-limited from this server." >&2
  return 1
}

install_xray_alpine() {
  local arch tmpdir
  arch="$(map_xray_arch)"
  tmpdir="$(mktemp -d)"
  mkdir -p /usr/local/bin /usr/local/etc/xray /usr/local/share/xray /var/log/xray
  if ! download_xray_release_zip "$arch" "$tmpdir/xray.zip"; then
    rm -rf "$tmpdir"
    exit 1
  fi
  unzip -qo "$tmpdir/xray.zip" -d "$tmpdir"
  if [[ ! -f "$tmpdir/xray" ]]; then
    echo "ERROR: downloaded Xray archive does not contain the xray binary." >&2
    rm -rf "$tmpdir"
    exit 1
  fi
  install -m 0755 "$tmpdir/xray" /usr/local/bin/xray
  if [[ -f "$tmpdir/geoip.dat" ]]; then install -m 0644 "$tmpdir/geoip.dat" /usr/local/share/xray/geoip.dat; fi
  if [[ -f "$tmpdir/geosite.dat" ]]; then install -m 0644 "$tmpdir/geosite.dat" /usr/local/share/xray/geosite.dat; fi
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
}


install_xray_if_needed() {
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    echo "Installing Xray..."
    if [[ "$OS_FAMILY" == "debian" ]]; then
      bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install -u root --logrotate 00:00:00
    else
      install_xray_alpine
    fi
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
  chmod 664 "$APP_LOG_DIR"/*.log 2>/dev/null || true
  chmod 775 "$APP_LOG_DIR"
  if [[ "$INIT_SYSTEM" == "systemd" ]]; then
    systemctl daemon-reload
    if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
      systemctl enable xray --now
      systemctl enable "$LOCAL_AGENT_SERVICE_NAME" --now
      for _ in $(seq 1 20); do
        if curl -fsS -H "X-Agent-Token: $LOCAL_AGENT_API_TOKEN" "$LOCAL_AGENT_API_URL/config/summary" >/dev/null 2>&1 ||            curl -fsS -H "X-Agent-Token: $LOCAL_AGENT_API_TOKEN" "$LOCAL_AGENT_API_URL/health" >/dev/null 2>&1; then
          break
        fi
        sleep 2
      done
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
      for _ in $(seq 1 20); do
        if curl -fsS -H "X-Agent-Token: $LOCAL_AGENT_API_TOKEN" "$LOCAL_AGENT_API_URL/config/summary" >/dev/null 2>&1 ||            curl -fsS -H "X-Agent-Token: $LOCAL_AGENT_API_TOKEN" "$LOCAL_AGENT_API_URL/health" >/dev/null 2>&1; then
          break
        fi
        sleep 2
      done
    fi
    rc-service "$SUB_SERVICE_NAME" start
    if telegram_bot_enabled; then
      rc-service "$BOT_SERVICE_NAME" start
      rc-service "$SCHED_SERVICE_NAME" start
    fi
  fi
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    if ! su -s /bin/sh "$SERVICE_USER" -c "SAHAR_CONFIG='$APP_DATA_DIR/config.json' '$VENV_DIR/bin/python' '$APP_APP_DIR/register_local_server.py'"; then
      echo "Local node registration failed. See $APP_LOG_DIR/provision.log" >&2
      return 1
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
  print_banner
  require_root
  run_step "Checking system" check_os
  prepare_bot_token_input
  run_step "Validating bot token" validate_bot_token
  run_step "Installing system packages" install_packages
  run_step "Creating service account" ensure_user
  run_step "Preparing defaults" ask_config
  run_step "Creating directories" prepare_dirs
  run_step "Copying application files" copy_code
  run_step "Writing configuration" write_config
  run_step "Building Python environment" setup_venv
  run_step "Installing Xray components" install_xray_if_needed
  run_step "Writing service files" write_services
  run_step "Configuring log rotation" write_logrotate
  run_step "Starting services" enable_services
  ui_newline
  print_done
}

main "$@"
