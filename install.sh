#!/bin/sh
set -eu

MODE="${1:-}"

print_banner() {
  echo "=========================================="
  echo "Sahar Unified Installer"
  echo "=========================================="
  echo
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must be run as root"
    exit 1
  fi
}

detect_os() {
  if [ ! -f /etc/os-release ]; then
    echo "Unsupported Linux distribution: /etc/os-release not found"
    exit 1
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-}"
  OS_LIKE="${ID_LIKE:-}"
  case "$OS_ID" in
    alpine)
      OS_FAMILY="alpine"
      ;;
    ubuntu|debian)
      OS_FAMILY="debian"
      ;;
    *)
      case "$OS_LIKE" in
        *debian*|*ubuntu*)
          OS_FAMILY="debian"
          ;;
        *)
          echo "Unsupported Linux distribution. Supported: Ubuntu, Debian, Alpine."
          exit 1
          ;;
      esac
      ;;
  esac
}

ensure_bootstrap_packages() {
  if [ "$OS_FAMILY" = "debian" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt update
    apt install -y bash curl unzip ca-certificates
  else
    apk add --no-cache bash curl unzip ca-certificates
  fi
}

prompt_mode() {
  if [ -n "$MODE" ]; then
    return
  fi
  echo "Install mode:"
  echo "1) Master"
  echo "2) Agent"
  printf "Select [1/2]: "
  read ans
  case "$ans" in
    1) MODE="master" ;;
    2) MODE="agent" ;;
    *)
      echo "Invalid install mode"
      exit 1
      ;;
  esac
}

run_mode() {
  case "$MODE" in
    master)
      exec bash ./install_master.sh
      ;;
    agent)
      exec bash ./install_agent.sh
      ;;
    *)
      echo "Invalid install mode. Use: sh install.sh master | sh install.sh agent"
      exit 1
      ;;
  esac
}

print_banner
require_root
prompt_mode
detect_os
echo "Detected OS family: $OS_FAMILY"
ensure_bootstrap_packages
run_mode
