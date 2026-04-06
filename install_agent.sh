#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.14"

APP_DIR="/opt/sahar-agent"
APP_APP_DIR="$APP_DIR/app"
APP_DATA_DIR="$APP_DIR/data"
APP_LOG_DIR="$APP_DIR/logs"
APP_BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"
API_SERVICE_NAME="sahar-agent"
XRAY_CONFIG_PATH="/usr/local/etc/xray/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_banner() {
  echo "=========================================="
  echo "Sahar Agent Installer v${APP_VERSION}"
  echo "=========================================="
  echo
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must be run as root"
    exit 1
  fi
}

check_os() {
  if ! grep -Eqi 'ubuntu|debian' /etc/os-release; then
    echo "Only Ubuntu/Debian is supported"
    exit 1
  fi
}

install_packages() {
  apt update
  apt install -y python3 python3-venv python3-pip curl jq uuid-runtime ca-certificates dnsutils tar
}


infer_host_mode() {
  local host="$1"
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ip"
  else
    echo "domain"
  fi
}

load_noninteractive_env() {
  HOST_MODE="${HOST_MODE:-$(infer_host_mode "${PUBLIC_HOST:-}")}"
  TRANSPORT_MODE="dual"
  FINGERPRINT="${FINGERPRINT:-chrome}"
  REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-}"
  REALITY_DEST="${REALITY_DEST:-}"
  AGENT_NAME="${AGENT_NAME:-agent-node}"
  XRAY_PORT="${XRAY_PORT:-443}"
  REALITY_PORT="${REALITY_PORT:-8443}"
  XRAY_API_PORT="${XRAY_API_PORT:-10085}"
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
  ALLOWED_SOURCES="${ALLOWED_SOURCES:-}"
  AGENT_TOKEN="${AGENT_TOKEN:-}"
  if [[ -z "${PUBLIC_HOST:-}" ]]; then
    echo "PUBLIC_HOST is required in NONINTERACTIVE mode"
    exit 1
  fi
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
    if getent hosts "$PUBLIC_HOST" >/dev/null 2>&1; then
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
  read -rp "Agent listen host [0.0.0.0]: " AGENT_LISTEN_HOST
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  read -rp "Agent listen port [8787]: " AGENT_LISTEN_PORT
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
  read -rp "Allowed source IPs/CIDRs (comma-separated, blank means any): " ALLOWED_SOURCES
  read -rp "Agent API token [leave blank to auto-generate]: " AGENT_TOKEN
  if [[ -z "$AGENT_TOKEN" ]]; then
    AGENT_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  fi
}

install_xray() {
  echo "Installing Xray using the official installer..."
  bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install -u root --logrotate 00:00:00
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
  "rate_limit_max_requests": 120
}
JSON
  chmod 600 "$APP_DATA_DIR/config.json"
}

setup_venv() {
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$APP_APP_DIR/requirements.txt"
}

write_service() {
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
}

write_logrotate() {
  cat > /etc/logrotate.d/sahar-agent <<EOF2
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

enable_services() {
  systemctl daemon-reload
  systemctl enable xray --now
  systemctl enable "$API_SERVICE_NAME" --now
}

print_done() {
  echo
  echo "Agent installed successfully."
  echo "Service: systemctl status $API_SERVICE_NAME"
  echo "Logs: journalctl -u $API_SERVICE_NAME -f"
  echo
  echo "Agent API URL: http://${PUBLIC_HOST}:${AGENT_LISTEN_PORT}"
  echo "Agent token: ${AGENT_TOKEN}"
  if [[ "$TRANSPORT_MODE" == "reality" ]]; then
    echo "REALITY mode selected. Public key and short ID will be generated on first start and exposed via /server_health from the master."
  fi
}

main() {
  print_banner
  require_root
  check_os
  install_packages
  if [[ "${NONINTERACTIVE:-0}" == "1" ]]; then
    load_noninteractive_env
  else
    ask_host_mode
    ask_transport_mode
    ask_config
  fi
  install_xray
  prepare_dirs
  copy_code
  write_config
  setup_venv
  write_service
  write_logrotate
  enable_services
  print_done
}

main "$@"
