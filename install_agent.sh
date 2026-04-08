#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.37"

APP_DIR="/opt/sahar-agent"
APP_APP_DIR="$APP_DIR/app"
APP_DATA_DIR="$APP_DIR/data"
APP_LOG_DIR="$APP_DIR/logs"
APP_BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"
API_SERVICE_NAME="sahar-agent"
XRAY_CONFIG_PATH="/usr/local/etc/xray/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_FILE="/tmp/sahar-agent-installer.log"
TOTAL_STEPS=10
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
  printf '%s%sSahar Agent Installer v%s%s
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
  printf '%sAgent setup runs silently with defaults and keeps package output hidden.%s
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
    echo ""
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

install_packages() {
  if [[ "$OS_FAMILY" == "debian" ]]; then
    apt update
    apt install -y python3 python3-venv python3-pip curl jq uuid-runtime ca-certificates dnsutils tar unzip logrotate git
  else
    apk add --no-cache bash python3 py3-pip py3-virtualenv curl jq uuidgen ca-certificates bind-tools tar unzip logrotate build-base python3-dev musl-dev linux-headers git
  fi
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
  TRANSPORT_MODE="dual"
  FINGERPRINT="${FINGERPRINT:-chrome}"
  REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-www.cloudflare.com}"
  REALITY_DEST="${REALITY_DEST:-${REALITY_SERVER_NAME}:443}"
  AGENT_NAME="${AGENT_NAME:-$(hostname 2>/dev/null || echo agent-node)}"
  XRAY_PORT="${XRAY_PORT:-443}"
  REALITY_PORT="${REALITY_PORT:-8443}"
  XRAY_API_PORT="${XRAY_API_PORT:-10085}"
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
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
  local arch="$1" output_zip="$2" ua latest_url resolved_url tag tagged_url
  ua="SaharInstaller/0.1.37"
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


install_xray() {
  echo "Installing Xray..."
  if [[ "$OS_FAMILY" == "debian" ]]; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install -u root --logrotate 00:00:00
  else
    install_xray_alpine
  fi
}

prepare_dirs() {
  mkdir -p "$APP_APP_DIR" "$APP_DATA_DIR" "$APP_LOG_DIR" "$APP_BACKUP_DIR"
}

copy_code() {
  cp -R "$SCRIPT_DIR/agent_app/." "$APP_APP_DIR/"
}

write_config() {
  cat > "$APP_DATA_DIR/config.json" <<JSON
{
  "agent_name": "$AGENT_NAME",
  "agent_token": "$AGENT_TOKEN",
  "allowed_sources": "$ALLOWED_SOURCES",
  "agent_listen_host": "$AGENT_LISTEN_HOST",
  "agent_listen_port": $AGENT_LISTEN_PORT,
  "public_host": "$PUBLIC_HOST",
  "host_mode": "$HOST_MODE",
  "xray_port": $XRAY_PORT,
  "simple_port": $XRAY_PORT,
  "reality_port": $REALITY_PORT,
  "xray_api_port": $XRAY_API_PORT,
  "xray_config_path": "$XRAY_CONFIG_PATH",
  "transport_mode": "$TRANSPORT_MODE",
  "reality_server_name": "$REALITY_SERVER_NAME",
  "reality_dest": "$REALITY_DEST",
  "reality_public_key": "",
  "reality_private_key": "",
  "reality_short_id": "",
  "fingerprint": "$FINGERPRINT",
  "log_path": "$APP_LOG_DIR/agent.log",
  "backup_dir": "$APP_BACKUP_DIR",
  "xray_access_log": "/var/log/xray/access.log",
  "xray_error_log": "/var/log/xray/error.log",
  "rate_limit_window_seconds": 60,
  "rate_limit_max_requests": 120,
  "package_version": "$APP_VERSION"
}
JSON
  chmod 600 "$APP_DATA_DIR/config.json"
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
ExecStart=$VENV_DIR/bin/gunicorn -w 2 -k gthread --threads 4 --bind ${AGENT_LISTEN_HOST}:${AGENT_LISTEN_PORT} agent_api:APP
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
command_args="-w 2 -k gthread --threads 4 --bind ${AGENT_LISTEN_HOST}:${AGENT_LISTEN_PORT} agent_api:APP"
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
  echo "Agent API URL: http://${PUBLIC_HOST}:${AGENT_LISTEN_PORT}"
  echo "Agent token: ${AGENT_TOKEN}"
}


main() {
  setup_ui
  print_banner
  require_root
  run_step "Checking system" check_os
  run_step "Installing system packages" install_packages
  run_step "Preparing defaults" load_noninteractive_env
  run_step "Installing Xray components" install_xray
  run_step "Creating directories" prepare_dirs
  run_step "Copying application files" copy_code
  run_step "Writing configuration" write_config
  run_step "Building Python environment" setup_venv
  run_step "Writing service files" write_service
  run_step "Configuring log rotation" write_logrotate
  run_step "Starting services" enable_services
  ui_newline
  print_done
}

main "$@"
