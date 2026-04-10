#!/bin/sh
set -eu

MODE="${1:-${SAHAR_INSTALL_MODE:-master}}"
OS_PRETTY_NAME="Detecting..."
INIT_SYSTEM="Detecting..."
OS_FAMILY=""
LOG_FILE="/tmp/sahar-bootstrap-installer.log"
TOTAL_STEPS=2
CURRENT_STEP=0
UI_TTY=0
C_RESET=""
C_BOLD=""
C_DIM=""
C_GREEN=""
C_CYAN=""
C_YELLOW=""
C_RED=""
FAIL_HINT=""

setup_ui() {
  : > "$LOG_FILE"
  if [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; then
    UI_TTY=1
    C_RESET=$(printf '[0m')
    C_BOLD=$(printf '[1m')
    C_DIM=$(printf '[2m')
    C_GREEN=$(printf '[32m')
    C_CYAN=$(printf '[36m')
    C_YELLOW=$(printf '[33m')
    C_RED=$(printf '[31m')
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must be run as root" >&2
    exit 1
  fi
}

set_fail_hint() {
  FAIL_HINT="$1"
}

progress_percent() {
  echo $((CURRENT_STEP * 100 / TOTAL_STEPS))
}

draw_screen() {
  [ "$UI_TTY" -eq 1 ] || return 0
  printf '[H[2J'
  printf '%s%sSahar Installer%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '%s------------------------------------------------------------%s
' "$C_DIM" "$C_RESET"
  printf ' Mode        %s
' "$MODE"
  printf ' System      %s
' "$OS_PRETTY_NAME"
  printf ' Init        %s
' "$INIT_SYSTEM"
  printf ' Step        %s/%s
' "$((CURRENT_STEP + 1 <= TOTAL_STEPS ? CURRENT_STEP + 1 : TOTAL_STEPS))" "$TOTAL_STEPS"
  printf ' Stage       %s
' "$1"
  printf ' Status      %s
' "$2"
  printf ' Log         %s

' "$LOG_FILE"
  printf ' Progress    %s%%

' "$(progress_percent)"
  printf '%sBootstrap only ensures bash is present, then hands off to the main installer.%s
' "$C_YELLOW" "$C_RESET"
}

fail_install() {
  stage="$1"
  draw_screen "$stage" "Failed"
  printf '%sInstallation failed.%s
' "$C_RED" "$C_RESET" >&2
  printf 'Step: %s
' "$stage" >&2
  if [ -n "$FAIL_HINT" ]; then
    printf 'Reason: %s
' "$FAIL_HINT" >&2
  fi
  printf 'Details: %s
' "$LOG_FILE" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
  exit 1
}

run_with_timeout() {
  timeout_s="$1"
  shift
  if command_exists timeout; then
    timeout "$timeout_s" "$@"
  else
    "$@"
  fi
}

detect_os() {
  if [ ! -r /etc/os-release ]; then
    set_fail_hint "/etc/os-release not found"
    return 1
  fi
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_PRETTY_NAME="${PRETTY_NAME:-unknown}"
  case "$OS_ID" in
    alpine) OS_FAMILY="alpine" ;;
    ubuntu|debian) OS_FAMILY="debian" ;;
    *)
      case "${ID_LIKE:-}" in
        *debian*|*ubuntu*) OS_FAMILY="debian" ;;
        *) set_fail_hint "Unsupported Linux distribution: ${PRETTY_NAME:-$OS_ID}"; return 1 ;;
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

ensure_bootstrap_packages() {
  if command_exists bash; then
    echo 'bootstrap bash already present' >> "$LOG_FILE"
    return 0
  fi
  echo 'bootstrap installing bash only; remaining packages handled by mode installer' >> "$LOG_FILE"
  if [ "$OS_FAMILY" = "debian" ]; then
    export DEBIAN_FRONTEND=noninteractive
    run_with_timeout 180 apt-get update >> "$LOG_FILE" 2>&1
    run_with_timeout 180 apt-get install -y bash >> "$LOG_FILE" 2>&1
  else
    run_with_timeout 120 apk add --no-cache bash >> "$LOG_FILE" 2>&1
  fi
  command_exists bash
}

run_step() {
  stage="$1"
  shift
  draw_screen "$stage" "Running"
  if ! "$@" >> "$LOG_FILE" 2>&1; then
    fail_install "$stage"
  fi
  CURRENT_STEP=$((CURRENT_STEP + 1))
  draw_screen "$stage" "Completed"
}

run_mode() {
  case "$MODE" in
    master) exec bash ./install_master.sh ;;
    agent) exec bash ./install_agent.sh ;;
    *) echo "Invalid install mode. Use: sh install.sh master | sh install.sh agent" >&2; exit 1 ;;
  esac
}

setup_ui
require_root
run_step "Checking system" detect_os
run_step "Preparing bootstrap tools" ensure_bootstrap_packages
CURRENT_STEP=$TOTAL_STEPS
run_mode
