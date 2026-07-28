#!/usr/bin/env bash
set -Eeuo pipefail
STATE_DIR="${MIA_STATE_DIR:-$HOME/.local/share/mia}"
VENV_DIR="${MIA_VENV:-$STATE_DIR/venv}"
DEFAULT_BIN_DIR="$HOME/.local/bin"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* && ":$PATH:" == *":$HOME/bin:"* ]]; then DEFAULT_BIN_DIR="$HOME/bin"; fi
BIN_DIR="${MIA_BIN_DIR:-$DEFAULT_BIN_DIR}"
REMOVE_CONFIG=0
REMOVE_HISTORY=0
REMOVE_SYSTEM=0
KEEP_PACKAGES=0
YES=0

usage() {
  cat <<'USAGE'
Usage: ./uninstall.sh [options]

Removes MIA and, by default, all user-owned tool environments recorded by
`mia pkg`. Distribution packages are preserved unless explicitly requested.
Reports in ~/mia_reports are never removed automatically.

Options:
  --keep-packages            Keep optional OSINT tool environments.
  --remove-system-packages   Permit removal of system packages installed by MIA.
  --remove-config            Delete ~/.config/mia.
  --remove-history           Delete remaining MIA state and logs.
  --yes, -y                  Do not prompt.
  -h, --help                 Show this help.
USAGE
}
while (($#)); do
  case "$1" in
    --keep-packages) KEEP_PACKAGES=1 ;;
    --remove-system-packages) REMOVE_SYSTEM=1 ;;
    --remove-config) REMOVE_CONFIG=1 ;;
    --remove-history) REMOVE_HISTORY=1 ;;
    --keep-runtime-cache) : ;;
    --yes|-y) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

MIA_CMD="$BIN_DIR/mia"
if [[ ! -x "$MIA_CMD" && -x "$VENV_DIR/bin/mia" ]]; then MIA_CMD="$VENV_DIR/bin/mia"; fi
if [[ "$YES" -eq 0 ]]; then
  read -r -p 'Remove MIA and its user-managed optional tools? [y/N] ' answer
  case "$answer" in [Yy]|[Yy][Ee][Ss]) ;; *) exit 0 ;; esac
fi
if [[ -x "$MIA_CMD" ]]; then
  "$MIA_CMD" desktop remove >/dev/null 2>&1 || true
fi
if [[ "$KEEP_PACKAGES" -eq 0 && -x "$MIA_CMD" ]]; then
  args=(pkg uninstall --all --yes)
  if [[ "$REMOVE_SYSTEM" -eq 1 ]]; then args+=(--remove-system-packages); fi
  "$MIA_CMD" "${args[@]}" || true
fi
rm -f "$BIN_DIR/mia"
rm -rf "$VENV_DIR" "$STATE_DIR/bootstrap" "$STATE_DIR/python" "$STATE_DIR/uv-cache"
if [[ "$REMOVE_CONFIG" -eq 1 ]]; then rm -rf "${MIA_CONFIG_DIR:-$HOME/.config/mia}"; fi
if [[ "$REMOVE_HISTORY" -eq 1 ]]; then rm -rf "$STATE_DIR" "${MIA_LOG_DIR:-$HOME/.local/state/mia}"; fi
printf 'Removed MIA. Reports were preserved.\n'
