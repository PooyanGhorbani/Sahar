#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.14"

APP_DIR="/opt/sahar-master"
APP_APP_DIR="$APP_DIR/app"
APP_AGENT_APP_DIR="$APP_DIR/agent_app"
APP_DATA_DIR="$APP_DIR/data"
APP_LOG_DIR="$APP_DIR/logs"
APP_QR_DIR="$APP_DIR/qrcodes"
APP_BACKUP_DIR="$APP_DIR/backups"
VENV_DIR="$APP_DIR/venv"
SERVICE_USER="sahar-master"
BOT_SERVICE_NAME="sahar-master-bot"
SCHED_SERVICE_NAME="sahar-master-scheduler"
LOCAL_AGENT_SERVICE_NAME="sahar-master-local-agent"
SUB_SERVICE_NAME="sahar-master-subscription"
XRAY_CONFIG_PATH="/usr/local/etc/xray/config.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_banner() {
  echo "=========================================="
  echo "Sahar Master Installer v${APP_VERSION}"
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
  apt install -y python3 python3-venv python3-pip sqlite3 curl ca-certificates tar zip jq uuid-runtime dnsutils
}

ensure_user() {
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
}

ask_config() {
  read -rp "Telegram bot token: " BOT_TOKEN
  read -rp "Admin chat IDs (comma-separated): " ADMIN_CHAT_IDS
  read -rp "Scheduler interval seconds [300]: " SCHEDULER_INTERVAL
  SCHEDULER_INTERVAL="${SCHEDULER_INTERVAL:-300}"
  read -rp "Agent timeout seconds [15]: " AGENT_TIMEOUT
  AGENT_TIMEOUT="${AGENT_TIMEOUT:-15}"
  read -rp "Warn when days left <= [3]: " WARN_DAYS_LEFT
  WARN_DAYS_LEFT="${WARN_DAYS_LEFT:-3}"
  read -rp "Warn when usage percent >= [80]: " WARN_USAGE_PERCENT
  WARN_USAGE_PERCENT="${WARN_USAGE_PERCENT:-80}"
  read -rp "Backup every N hours [24]: " BACKUP_INTERVAL_HOURS
  BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
  read -rp "Keep latest N backups [10]: " BACKUP_RETENTION
  BACKUP_RETENTION="${BACKUP_RETENTION:-10}"
  read -rp "Subscription public base URL (example: https://sub.example.com or http://IP:8090): " SUBSCRIPTION_BASE_URL
  read -rp "Subscription bind host [0.0.0.0]: " SUBSCRIPTION_BIND_HOST
  SUBSCRIPTION_BIND_HOST="${SUBSCRIPTION_BIND_HOST:-0.0.0.0}"
  read -rp "Subscription bind port [8090]: " SUBSCRIPTION_BIND_PORT
  SUBSCRIPTION_BIND_PORT="${SUBSCRIPTION_BIND_PORT:-8090}"
  read -rp "Enable Cloudflare DNS automation? [Y/n]: " CLOUDFLARE_ENABLED_CHOICE
  CLOUDFLARE_ENABLED_CHOICE="${CLOUDFLARE_ENABLED_CHOICE:-Y}"
  if [[ "$CLOUDFLARE_ENABLED_CHOICE" =~ ^([Yy]|yes|YES)$ ]]; then
    CLOUDFLARE_ENABLED=true
    read -rp "Cloudflare domain name (example.com): " CLOUDFLARE_DOMAIN_NAME
    read -rp "Base subdomain (optional, example: vpn): " CLOUDFLARE_BASE_SUBDOMAIN
    read -rp "Cloudflare API token (Zone:Read + DNS:Write): " CLOUDFLARE_API_TOKEN
  else
    CLOUDFLARE_ENABLED=false
    CLOUDFLARE_DOMAIN_NAME=""
    CLOUDFLARE_BASE_SUBDOMAIN=""
    CLOUDFLARE_API_TOKEN=""
  fi
  CLOUDFLARE_TOKEN_ENCRYPTION_KEY="$(python3 - <<'PY2'
import os, base64
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY2
)"
  read -rp "Enable local VPN node on this master server? [Y/n]: " LOCAL_NODE_CHOICE
  LOCAL_NODE_CHOICE="${LOCAL_NODE_CHOICE:-Y}"
  if [[ "$LOCAL_NODE_CHOICE" =~ ^([Yy]|yes|YES)$ ]]; then
    LOCAL_NODE_ENABLED=true
  else
    LOCAL_NODE_ENABLED=false
  fi

  LOCAL_SERVER_NAME="local"
  LOCAL_AGENT_API_URL=""
  LOCAL_AGENT_API_TOKEN=""
  LOCAL_AGENT_LISTEN_HOST="127.0.0.1"
  LOCAL_AGENT_LISTEN_PORT="8787"
  LOCAL_PUBLIC_HOST=""
  LOCAL_HOST_MODE=""
  LOCAL_TRANSPORT_MODE="dual"
  LOCAL_REALITY_SERVER_NAME=""
  LOCAL_REALITY_DEST=""
  LOCAL_FINGERPRINT="chrome"
  LOCAL_XRAY_PORT="443"
  LOCAL_REALITY_PORT="8443"
  LOCAL_XRAY_API_PORT="10085"

  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    read -rp "Local server display name [local]: " LOCAL_SERVER_NAME
    LOCAL_SERVER_NAME="${LOCAL_SERVER_NAME:-local}"
    echo "Choose local node public host type:"
    echo "1) IP"
    echo "2) Domain"
    read -rp "Select [1/2]: " LOCAL_HOST_TYPE
    if [[ "$LOCAL_HOST_TYPE" == "1" ]]; then
      LOCAL_HOST_MODE="ip"
      read -rp "Local node public IP: " LOCAL_PUBLIC_HOST
    elif [[ "$LOCAL_HOST_TYPE" == "2" ]]; then
      LOCAL_HOST_MODE="domain"
      read -rp "Local node domain or subdomain: " LOCAL_PUBLIC_HOST
      read -rp "Have you already pointed DNS (A record) to this server IP? [y/n]: " DNS_READY
      if [[ "$DNS_READY" != "y" && "$DNS_READY" != "Y" ]]; then
        echo "Please create/update the A record first, then run the installer again."
        exit 1
      fi
      if getent hosts "$LOCAL_PUBLIC_HOST" >/dev/null 2>&1; then
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
    echo "This local node will install both profiles:"
    echo "- VLESS | Simple"
    echo "- VLESS | Reality"
    read -rp "REALITY serverName/SNI (example: www.cloudflare.com): " LOCAL_REALITY_SERVER_NAME
    read -rp "REALITY dest [default ${LOCAL_REALITY_SERVER_NAME}:443]: " LOCAL_REALITY_DEST
    LOCAL_REALITY_DEST="${LOCAL_REALITY_DEST:-${LOCAL_REALITY_SERVER_NAME}:443}"
    read -rp "Fingerprint [default chrome]: " LOCAL_FINGERPRINT
    LOCAL_FINGERPRINT="${LOCAL_FINGERPRINT:-chrome}"

    read -rp "Local node VLESS Simple port [443]: " LOCAL_XRAY_PORT
    LOCAL_XRAY_PORT="${LOCAL_XRAY_PORT:-443}"
    read -rp "Local node VLESS Reality port [8443]: " LOCAL_REALITY_PORT
    LOCAL_REALITY_PORT="${LOCAL_REALITY_PORT:-8443}"
    read -rp "Local node Xray API stats port [10085]: " LOCAL_XRAY_API_PORT
    LOCAL_XRAY_API_PORT="${LOCAL_XRAY_API_PORT:-10085}"
    read -rp "Local agent listen port [8787]: " LOCAL_AGENT_LISTEN_PORT
    LOCAL_AGENT_LISTEN_PORT="${LOCAL_AGENT_LISTEN_PORT:-8787}"
    read -rp "Local agent API token [leave blank to auto-generate]: " LOCAL_AGENT_API_TOKEN
    if [[ -z "$LOCAL_AGENT_API_TOKEN" ]]; then
      LOCAL_AGENT_API_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
    fi
    LOCAL_AGENT_API_URL="http://127.0.0.1:${LOCAL_AGENT_LISTEN_PORT}"
  fi
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
  "admin_chat_ids": "$ADMIN_CHAT_IDS",
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
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$APP_APP_DIR/requirements.txt"
}

bootstrap_cloudflare() {
  if [[ "$CLOUDFLARE_ENABLED" == true ]]; then
    CF_API_TOKEN="$CLOUDFLARE_API_TOKEN" SAHAR_CONFIG="$APP_DATA_DIR/config.json" "$VENV_DIR/bin/python" "$APP_APP_DIR/bootstrap_cloudflare.py"
  fi
}

write_services() {
  cat > "/etc/systemd/system/${BOT_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Sahar Master Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
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
Group=$SERVICE_USER
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
Group=$SERVICE_USER
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

install_xray_if_needed() {
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    echo "Installing Xray using the official installer..."
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install -u root --logrotate 00:00:00
  fi
}

enable_services() {
  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
  systemctl daemon-reload
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    systemctl enable xray --now
    systemctl enable "$LOCAL_AGENT_SERVICE_NAME" --now
    for _ in $(seq 1 20); do
      if curl -fsS -H "X-Agent-Token: $LOCAL_AGENT_API_TOKEN" "$LOCAL_AGENT_API_URL/health" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi
  systemctl enable "$BOT_SERVICE_NAME" --now
  systemctl enable "$SCHED_SERVICE_NAME" --now
  systemctl enable "$SUB_SERVICE_NAME" --now
  if [[ "$LOCAL_NODE_ENABLED" == true ]]; then
    su -s /bin/bash "$SERVICE_USER" -c "SAHAR_CONFIG='$APP_DATA_DIR/config.json' '$VENV_DIR/bin/python' '$APP_APP_DIR/register_local_server.py'"
  fi
}

print_done() {
  echo
  echo "Master installed successfully."
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
  echo "Subscription base URL: $SUBSCRIPTION_BASE_URL"
  echo "Start in Telegram with /help"
}

main() {
  print_banner
  require_root
  check_os
  install_packages
  ensure_user
  ask_config
  prepare_dirs
  copy_code
  write_config
  setup_venv
  install_xray_if_needed
  write_services
  write_logrotate
  enable_services
  print_done
}

main "$@"
