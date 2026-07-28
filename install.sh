#!/usr/bin/env bash
# Cross-distribution installer for MIA and its optional OSINT package manager.
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${MIA_STATE_DIR:-$HOME/.local/share/mia}"
VENV_DIR="${MIA_VENV:-$STATE_DIR/venv}"
BOOTSTRAP_DIR="${MIA_BOOTSTRAP_DIR:-$STATE_DIR/bootstrap}"
PYTHON_DIR="${MIA_PYTHON_DIR:-$STATE_DIR/python}"
UV_CACHE_DIR="${MIA_UV_CACHE_DIR:-$STATE_DIR/uv-cache}"
DEFAULT_BIN_DIR="$HOME/.local/bin"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* && ":$PATH:" == *":$HOME/bin:"* ]]; then
  DEFAULT_BIN_DIR="$HOME/bin"
fi
BIN_DIR="${MIA_BIN_DIR:-$DEFAULT_BIN_DIR}"
LOG_DIR="${MIA_INSTALL_LOG_DIR:-$HOME/.local/state/mia}"
LOG_FILE="$LOG_DIR/install.log"
PACKAGE_MANAGER="${MIA_PACKAGE_MANAGER:-auto}"
CORE_PYTHON_VERSION="${MIA_CORE_PYTHON_VERSION:-auto}"
UV_SPEC="${MIA_UV_SPEC:-uv>=0.6,<1}"

INSTALL_CORE_TOOLS=1
INSTALL_SYSTEM_PACKAGES=1
ALL_TOOLS=0
INCLUDE_MIXED=0
DRY_RUN=0
NON_INTERACTIVE=0
INSTALL_DESKTOP=1
DESKTOP_READY=0
LAUNCH_MODE="none"
PKG_GROUPS=()
TOOLS=()

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Installs MIA in an isolated user environment. By default it also asks MIA's
package manager to install the "core" tool group. Every optional tool can later
be installed or removed with `mia pkg`.

Options:
  --mia-only                 Install MIA without any OSINT tools.
  --with GROUP               Add a package group (repeatable).
  --tool TOOL                Add one catalog tool (repeatable).
  --all-tools                Install every local/passive catalog tool.
  --include-mixed            With --all-tools, include broader DNS/HTTP tools.
  --skip-system-packages     Do not use apt/dnf/pacman/zypper/apk/brew.
  --package-manager NAME     auto, apt, dnf, pacman, zypper, apk, brew, none.
  --no-desktop               Do not add Discover and Workbench to the app menu.
  --launch MODE              Start discover or workbench after installation.
  --yes, -y                  Non-interactive mode.
  --dry-run                  Print actions without changing the host.
  -h, --help                 Show this help.

Examples:
  ./install.sh
  ./install.sh --mia-only
  ./install.sh --with username --with domain
  ./install.sh --tool ghunt --tool shodan
  ./install.sh --all-tools --include-mixed
  ./install.sh --mia-only --launch discover
USAGE
}

while (($#)); do
  case "$1" in
    --mia-only) INSTALL_CORE_TOOLS=0 ;;
    --with)
      shift; (($#)) || { echo 'Missing value for --with' >&2; exit 2; }
      PKG_GROUPS+=("$1")
      ;;
    --tool)
      shift; (($#)) || { echo 'Missing value for --tool' >&2; exit 2; }
      TOOLS+=("$1")
      ;;
    --all-tools) ALL_TOOLS=1; INSTALL_CORE_TOOLS=0 ;;
    --include-mixed) INCLUDE_MIXED=1 ;;
    --skip-system-packages|--skip-brew) INSTALL_SYSTEM_PACKAGES=0 ;;
    --package-manager)
      shift; (($#)) || { echo 'Missing value for --package-manager' >&2; exit 2; }
      PACKAGE_MANAGER="$1"
      ;;
    --no-desktop) INSTALL_DESKTOP=0 ;;
    --launch)
      shift; (($#)) || { echo 'Missing value for --launch' >&2; exit 2; }
      LAUNCH_MODE="$1"
      ;;
    --preserve-config) : ;; # compatibility no-op; package manager does not overwrite config
    --yes|-y) NON_INTERACTIVE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$PACKAGE_MANAGER" in
  auto|apt|dnf|pacman|zypper|apk|brew|none) ;;
  *) echo "Unsupported package manager: $PACKAGE_MANAGER" >&2; exit 2 ;;
esac
case "$LAUNCH_MODE" in
  none|discover|workbench) ;;
  *) echo "Unsupported launch mode: $LAUNCH_MODE (use none, discover, or workbench)" >&2; exit 2 ;;
esac

log() {
  printf '[MIA installer] %s\n' "$*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$LOG_DIR"
    printf '[%s] %s\n' "$(date -Is)" "$*" >>"$LOG_FILE"
  fi
}

warn() { printf '[MIA installer] WARNING: %s\n' "$*" >&2; }
fail() { printf '[MIA installer] ERROR: %s\n' "$*" >&2; exit 1; }
quote_command() { printf '  '; printf '%q ' "$@"; printf '\n'; }
show_log_tail() {
  if [[ -f "$LOG_FILE" ]]; then
    printf '\n[MIA installer] Last 40 log lines from %s:\n' "$LOG_FILE" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
  fi
}
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    quote_command "$@"
  elif ! "$@" >>"$LOG_FILE" 2>&1; then
    warn "Command failed: $(printf '%q ' "$@")"
    show_log_tail
    return 1
  fi
}
run_root() {
  if [[ "$EUID" -eq 0 ]]; then run "$@"
  elif command -v sudo >/dev/null 2>&1; then run sudo "$@"
  elif [[ "$DRY_RUN" -eq 1 ]]; then quote_command sudo "$@"
  else fail "sudo is required for system prerequisites; use --skip-system-packages after installing them manually"
  fi
}

load_os_release() {
  OS_NAME="Linux"
  OS_ID="unknown"
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_NAME="${PRETTY_NAME:-${NAME:-Linux}}"
    OS_ID="${ID:-unknown}"
  fi
}

is_immutable() {
  case "$OS_ID" in bazzite|silverblue|kinoite|ublue-os) return 0 ;; esac
  command -v rpm-ostree >/dev/null 2>&1
}

detect_manager() {
  if [[ "$PACKAGE_MANAGER" != auto ]]; then printf '%s\n' "$PACKAGE_MANAGER"; return; fi
  if is_immutable; then
    if command -v brew >/dev/null 2>&1; then printf 'brew\n'; else printf 'none\n'; fi
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then printf 'apt\n'
  elif command -v dnf >/dev/null 2>&1; then printf 'dnf\n'
  elif command -v pacman >/dev/null 2>&1; then printf 'pacman\n'
  elif command -v zypper >/dev/null 2>&1; then printf 'zypper\n'
  elif command -v apk >/dev/null 2>&1; then printf 'apk\n'
  elif command -v brew >/dev/null 2>&1; then printf 'brew\n'
  else printf 'none\n'; fi
}

install_base_packages() {
  case "$1" in
    apt) run_root apt-get update; run_root apt-get install -y git curl ca-certificates python3 python3-venv python3-pip ;;
    dnf) run_root dnf install -y git curl ca-certificates python3 python3-pip ;;
    pacman) run_root pacman -Sy --needed --noconfirm git curl ca-certificates python python-pip ;;
    zypper) run_root zypper --non-interactive install git curl ca-certificates python3 python3-pip ;;
    apk) run_root apk add --no-cache git curl ca-certificates python3 py3-pip py3-virtualenv ;;
    brew)
      for formula in git python@3.11 uv; do
        if [[ "$DRY_RUN" -eq 1 ]]; then quote_command brew install "$formula"
        elif ! brew list --formula "$formula" >/dev/null 2>&1; then run brew install "$formula"; fi
      done
      ;;
    none) warn 'No host package manager selected; using existing Python/Git commands.' ;;
  esac
}

find_bootstrap_python() {
  local candidate
  for candidate in python3 python python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,9))' >/dev/null 2>&1; then
      command -v "$candidate"; return
    fi
  done
  return 1
}

find_core_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(not ((3,11) <= sys.version_info[:2] < (3,14)))' >/dev/null 2>&1; then
      command -v "$candidate"; return
    fi
  done
  return 1
}

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  local python
  python="$(find_bootstrap_python)" || fail 'Python 3.9+ is required to bootstrap uv.'
  if [[ "$DRY_RUN" -eq 1 ]]; then printf 'uv\n'; return; fi
  rm -rf "$BOOTSTRAP_DIR"
  "$python" -m venv "$BOOTSTRAP_DIR" >>"$LOG_FILE" 2>&1
  "$BOOTSTRAP_DIR/bin/python" -m pip install --upgrade pip "$UV_SPEC" >>"$LOG_FILE" 2>&1
  printf '%s\n' "$BOOTSTRAP_DIR/bin/uv"
}

safe_link() {
  local source="$1" destination="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then quote_command ln -sfn "$source" "$destination"; return; fi
  mkdir -p "$(dirname "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    local backup
    backup="$STATE_DIR/backups/$(date +%Y%m%dT%H%M%S)"
    mkdir -p "$backup"
    mv "$destination" "$backup/$(basename "$destination")"
  fi
  ln -s "$source" "$destination"
}

[[ "$(uname -s)" == Linux ]] || fail 'This installer currently supports Linux hosts.'
load_os_release
SELECTED_MANAGER="$(detect_manager)"
if [[ "$INSTALL_SYSTEM_PACKAGES" -eq 0 ]]; then SELECTED_MANAGER=none; fi

if [[ "$NON_INTERACTIVE" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
  cat <<PROMPT
MIA is an early, vibe-coded public alpha. This installs the core application in
an isolated user environment. Optional third-party tools are managed separately.

  OS:              $OS_NAME
  Package manager: $SELECTED_MANAGER
  MIA environment: $VENV_DIR
  Commands:        $BIN_DIR
  Package state:   $STATE_DIR/package-state.json
PROMPT
  read -r -p 'Continue? [Y/n] ' answer
  case "${answer:-Y}" in [Yy]|[Yy][Ee][Ss]) ;; *) exit 0 ;; esac
fi

log "Detected OS: $OS_NAME"
log "Selected package manager: $SELECTED_MANAGER"
if [[ "$INSTALL_SYSTEM_PACKAGES" -eq 1 ]]; then install_base_packages "$SELECTED_MANAGER"; fi
if [[ "$DRY_RUN" -eq 0 ]]; then mkdir -p "$STATE_DIR" "$BIN_DIR" "$PYTHON_DIR" "$UV_CACHE_DIR" "$LOG_DIR"; fi
UV_BIN="$(find_uv)"
log "Using uv: $UV_BIN"
if [[ "$CORE_PYTHON_VERSION" == auto ]]; then
  if CORE_PYTHON="$(find_core_python)"; then
    log "Using existing supported Python: $CORE_PYTHON"
  else
    CORE_PYTHON=3.11
    log "No existing Python 3.11-3.13 found; uv will obtain Python 3.11"
  fi
else
  CORE_PYTHON="$CORE_PYTHON_VERSION"
fi

UV_ENV=(env "UV_PYTHON_INSTALL_DIR=$PYTHON_DIR" "UV_CACHE_DIR=$UV_CACHE_DIR")
EXPECTED_VERSION="$(awk -F'"' '/^version = / { print $2; exit }' "$PROJECT_DIR/pyproject.toml")"
VENV_BACKUP="$STATE_DIR/venv.previous"

restore_previous_environment() {
  rm -rf "$VENV_DIR"
  if [[ -e "$VENV_BACKUP" || -L "$VENV_BACKUP" ]]; then
    mv "$VENV_BACKUP" "$VENV_DIR"
    warn "Restored the previous MIA environment after the failed upgrade."
  fi
}

install_core_environment() {
  local had_previous=0 actual_version

  if [[ "$DRY_RUN" -eq 1 ]]; then
    if [[ -e "$VENV_DIR" || -L "$VENV_DIR" ]]; then
      quote_command mv "$VENV_DIR" "$VENV_BACKUP"
    fi
    run "${UV_ENV[@]}" "$UV_BIN" venv --python "$CORE_PYTHON" "$VENV_DIR"
    run "${UV_ENV[@]}" "$UV_BIN" pip install --python "$VENV_DIR/bin/python" --upgrade "$PROJECT_DIR"
    run "${UV_ENV[@]}" "$UV_BIN" pip check --python "$VENV_DIR/bin/python"
    return
  fi

  rm -rf "$VENV_BACKUP"
  if [[ -e "$VENV_DIR" || -L "$VENV_DIR" ]]; then
    log "Backing up the existing MIA environment before upgrade"
    mv "$VENV_DIR" "$VENV_BACKUP"
    had_previous=1
  fi

  if ! run "${UV_ENV[@]}" "$UV_BIN" venv --python "$CORE_PYTHON" "$VENV_DIR"; then
    restore_previous_environment
    fail "Could not create the new MIA environment. The previous installation was preserved."
  fi
  if ! run "${UV_ENV[@]}" "$UV_BIN" pip install --python "$VENV_DIR/bin/python" --upgrade "$PROJECT_DIR"; then
    restore_previous_environment
    fail "Could not install MIA $EXPECTED_VERSION. The previous installation was preserved."
  fi
  if ! run "${UV_ENV[@]}" "$UV_BIN" pip check --python "$VENV_DIR/bin/python"; then
    restore_previous_environment
    fail "Dependency validation failed. The previous installation was preserved."
  fi

  actual_version="$($VENV_DIR/bin/mia --version 2>>"$LOG_FILE" || true)"
  if [[ "$actual_version" != "$EXPECTED_VERSION" ]]; then
    warn "Expected MIA $EXPECTED_VERSION but the new environment reported ${actual_version:-no version}."
    restore_previous_environment
    fail "Version verification failed. The previous installation was preserved."
  fi

  if [[ "$had_previous" -eq 1 ]]; then
    rm -rf "$VENV_BACKUP"
  fi
  log "Installed and verified MIA $actual_version"
}

install_core_environment
safe_link "$VENV_DIR/bin/mia" "$BIN_DIR/mia"

PKG_ARGS=(pkg install --yes --package-manager "$SELECTED_MANAGER")
if [[ "$INSTALL_SYSTEM_PACKAGES" -eq 0 ]]; then PKG_ARGS+=(--no-system); fi
if [[ "$DRY_RUN" -eq 1 ]]; then PKG_ARGS+=(--dry-run); fi
if [[ "$INCLUDE_MIXED" -eq 1 ]]; then PKG_ARGS+=(--include-mixed); fi
if [[ "$ALL_TOOLS" -eq 1 ]]; then
  PKG_ARGS+=(--all)
else
  if [[ "$INSTALL_CORE_TOOLS" -eq 1 ]]; then PKG_GROUPS=(core "${PKG_GROUPS[@]}"); fi
  for group in "${PKG_GROUPS[@]}"; do PKG_ARGS+=(--group "$group"); done
  for tool in "${TOOLS[@]}"; do PKG_ARGS+=("$tool"); done
fi

if [[ "$ALL_TOOLS" -eq 1 || ${#PKG_GROUPS[@]} -gt 0 || ${#TOOLS[@]} -gt 0 ]]; then
  log 'Installing selected optional OSINT packages through mia pkg'
  if [[ "$DRY_RUN" -eq 1 ]]; then
    quote_command "$BIN_DIR/mia" "${PKG_ARGS[@]}"
  elif ! "$BIN_DIR/mia" "${PKG_ARGS[@]}"; then
    warn "One or more optional tools failed to install. MIA itself is installed; run \`mia pkg doctor\` for details."
  fi
fi

if [[ "$INSTALL_DESKTOP" -eq 1 ]]; then
  log 'Installing MIA Discover and MIA Workbench application-menu shortcuts'
  if [[ "$DRY_RUN" -eq 1 ]]; then
    quote_command "$BIN_DIR/mia" desktop install --command "$BIN_DIR/mia"
  elif ! "$BIN_DIR/mia" desktop install --command "$BIN_DIR/mia"; then
    warn "Desktop shortcuts could not be installed. MIA still works from the command line."
  else
    DESKTOP_READY=1
  fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then log 'Dry run complete; no files were changed.'; exit 0; fi
"$BIN_DIR/mia" --version
"$BIN_DIR/mia" doctor
printf '\nMIA installation complete.\n'
if [[ "$DESKTOP_READY" -eq 1 ]]; then
  printf '\nOpen it from your application menu:\n  MIA Discover\n  MIA Workbench\n'
fi
printf '\nRun:\n  %s discover\n  %s workbench\n\nInstall log: %s\n' "$BIN_DIR/mia" "$BIN_DIR/mia" "$LOG_FILE"
ACTIVE_MIA="$(command -v mia 2>/dev/null || true)"
if [[ -n "$ACTIVE_MIA" && "$ACTIVE_MIA" != "$BIN_DIR/mia" ]]; then
  warn "Another mia command appears earlier on PATH: $ACTIVE_MIA"
  warn "Run: type -a mia"
  warn "Then remove the obsolete launcher or run: hash -r"
fi
if [[ "$LAUNCH_MODE" != none ]]; then
  log "Launching MIA $LAUNCH_MODE"
  if command -v setsid >/dev/null 2>&1; then
    setsid "$BIN_DIR/mia" "$LAUNCH_MODE" >/dev/null 2>&1 < /dev/null &
  else
    nohup "$BIN_DIR/mia" "$LAUNCH_MODE" >/dev/null 2>&1 < /dev/null &
  fi
fi

printf '\nPackage manager examples:\n'
printf '  mia pkg groups\n  mia pkg list\n  mia pkg install --group username\n  mia pkg install subfinder gau\n  mia pkg uninstall social-analyzer\n'
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  # shellcheck disable=SC2016
  printf '\nAdd to PATH: export PATH="%s:$PATH"\n' "$BIN_DIR"
fi
