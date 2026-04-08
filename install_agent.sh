#!/usr/bin/env bash
set -euo pipefail

APP_VERSION="0.1.19"

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
  echo "Detected OS: $OS_PRETTY_NAME"
  echo "Detected OS family: $OS_FAMILY"
  echo "Detected init system: $INIT_SYSTEM"
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
    apt install -y python3 python3-venv python3-pip curl jq uuid-runtime ca-certificates dnsutils tar unzip logrotate
  else
    apk add --no-cache bash python3 py3-pip py3-virtualenv curl jq uuidgen ca-certificates bind-tools tar unzip logrotate
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

load_noninteractive_env() {
  HOST_MODE="${HOST_MODE:-$(infer_host_mode "${PUBLIC_HOST:-}")}"
  TRANSPORT_MODE="dual"
  FINGERPRINT="${FINGERPRINT:-chrome}"
  REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-www.cloudflare.com}"
  REALITY_DEST="${REALITY_DEST:-${REALITY_SERVER_NAME}:443}"
  AGENT_NAME="${AGENT_NAME:-agent-node}"
  XRAY_PORT="${XRAY_PORT:-443}"
  REALITY_PORT="${REALITY_PORT:-8443}"
  XRAY_API_PORT="${XRAY_API_PORT:-10085}"
  AGENT_LISTEN_HOST="${AGENT_LISTEN_HOST:-0.0.0.0}"
  AGENT_LISTEN_PORT="${AGENT_LISTEN_PORT:-8787}"
  ALLOWED_SOURCES="$(normalize_allowed_sources "${ALLOWED_SOURCES:-}")"
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

install_xray_alpine() {
  local arch tag url tmpdir
  arch="$(map_xray_arch)"
  tag="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')"
  url="https://github.com/XTLS/Xray-core/releases/download/${tag}/Xray-linux-${arch}.zip"
  tmpdir="$(mktemp -d)"
  mkdir -p /usr/local/bin /usr/local/etc/xray /usr/local/share/xray /var/log/xray
  curl -fsSL "$url" -o "$tmpdir/xray.zip"
  unzip -qo "$tmpdir/xray.zip" -d "$tmpdir"
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
  echo
  echo "Agent installed successfully."
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
