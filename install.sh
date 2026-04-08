#!/bin/sh
set -eu

MODE="${1:-${SAHAR_INSTALL_MODE:-master}}"
OS_ID=""
OS_VERSION_ID=""
OS_PRETTY_NAME=""
OS_FAMILY=""
INIT_SYSTEM=""
LOG_FILE="/tmp/sahar-bootstrap-installer.log"
TOTAL_STEPS=2
CURRENT_STEP=0
BAR_WIDTH=34
CURRENT_LABEL="Preparing bootstrap"
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
    printf '[?25l'
    trap cleanup_ui EXIT INT TERM
  fi
}

cleanup_ui() {
  if [ "$UI_TTY" -eq 1 ]; then
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
  done_slots=$((CURRENT_STEP * BAR_WIDTH / TOTAL_STEPS))
  pending_slots=$((BAR_WIDTH - done_slots))
  fill=$(printf '%*s' "$done_slots" '')
  fill=$(printf '%s' "$fill" | tr ' ' '=')
  empty=$(printf '%*s' "$pending_slots" '')
  printf '%s%s' "$fill" "$empty"
}

print_banner() {
  CURRENT_STATUS="Ready"
  draw_screen
}

draw_screen() {
  if [ "$UI_TTY" -ne 1 ]; then
    return 0
  fi
  percent=$((CURRENT_STEP * 100 / TOTAL_STEPS))
  step_no=$((CURRENT_STEP + 1))
  if [ "$step_no" -gt "$TOTAL_STEPS" ]; then
    step_no=$TOTAL_STEPS
  fi
  bar=$(progress_bar)
  printf '[H[2J'
  printf '%s%sSahar Installer%s
' "$C_BOLD" "$C_CYAN" "$C_RESET"
  printf '%s━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━%s
' "$C_DIM" "$C_RESET"
  printf ' %sMode%s        %s
' "$C_DIM" "$C_RESET" "$MODE"
  printf ' %sSystem%s      %s
' "$C_DIM" "$C_RESET" "${OS_PRETTY_NAME:-Detecting...}"
  printf ' %sInit%s        %s
' "$C_DIM" "$C_RESET" "${INIT_SYSTEM:-Detecting...}"
  printf ' %sStep%s        %s/%s
' "$C_DIM" "$C_RESET" "$step_no" "$TOTAL_STEPS"
  printf ' %sStage%s       %s
' "$C_DIM" "$C_RESET" "$CURRENT_LABEL"
  printf ' %sStatus%s      %s
' "$C_DIM" "$C_RESET" "$CURRENT_STATUS"
  printf ' %sLog%s         %s

' "$C_DIM" "$C_RESET" "$LOG_FILE"
  printf ' %sProgress%s    [%s%s%s] %s%3s%%%s

' "$C_DIM" "$C_RESET" "$C_GREEN" "$bar" "$C_RESET" "$C_BOLD" "$percent" "$C_RESET"
  printf '%sBootstrap only prepares git, curl, unzip, certificates, and hands off quietly.%s
' "$C_YELLOW" "$C_RESET"
}

finish_progress() {
  printf '
'
}

fail_install() {
  finish_progress
  printf '%sInstallation failed.%s
' "$C_RED" "$C_RESET" >&2
  printf 'Step: %s
' "$1" >&2
  printf 'Details: %s
' "$LOG_FILE" >&2
  if [ -s "$LOG_FILE" ]; then
    printf '
Last log lines:
' >&2
    tail -n 20 "$LOG_FILE" >&2 || true
  fi
  exit 1
}

spinner_loop() {
  start_ts=$(date +%s)
  while :; do
    elapsed=$(( $(date +%s) - start_ts ))
    advance_spinner
    CURRENT_STATUS="Running ${CURRENT_SPINNER}  ${elapsed}s"
    draw_screen
    sleep 0.12
  done
}

run_step() {
  label="$1"
  shift
  CURRENT_LABEL="$label"
  if [ "$UI_TTY" -eq 1 ]; then
    spinner_loop &
    spinner_pid=$!
    if ! "$@" >>"$LOG_FILE" 2>&1; then
      kill "$spinner_pid" 2>/dev/null || true
      wait "$spinner_pid" 2>/dev/null || true
      fail_install "$label"
    fi
    kill "$spinner_pid" 2>/dev/null || true
    wait "$spinner_pid" 2>/dev/null || true
  else
    printf '[%s/%s] %s
' "$((CURRENT_STEP + 1))" "$TOTAL_STEPS" "$label"
    if ! "$@" >>"$LOG_FILE" 2>&1; then
      fail_install "$label"
    fi
  fi
  CURRENT_STEP=$((CURRENT_STEP + 1))
  CURRENT_STATUS="Completed"
  draw_screen
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must be run as root"
    exit 1
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_os() {
  if [ ! -r /etc/os-release ]; then
    echo "Unsupported Linux distribution: /etc/os-release not found"
    exit 1
  fi

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

ensure_bootstrap_packages() {
  if [ "$OS_FAMILY" = "debian" ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y bash curl unzip ca-certificates git
  else
    apk add --no-cache bash curl unzip ca-certificates git
  fi
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

setup_ui
print_banner
require_root
run_step "Checking system" detect_os
run_step "Preparing bootstrap tools" ensure_bootstrap_packages
CURRENT_STEP=$TOTAL_STEPS
CURRENT_LABEL="Handing off to ${MODE} installer"
CURRENT_STATUS="Ready"
draw_screen
finish_progress
run_mode
