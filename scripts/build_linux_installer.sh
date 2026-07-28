#!/usr/bin/env bash
# Build a self-extracting MIA Linux installer from the current source tree.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist/MIA-Linux-Installer.run}"
VERSION="$(awk -F'"' '/^version = / {print $2; exit}' "$ROOT/pyproject.toml")"
DISPLAY_VERSION="${VERSION/a/-alpha.}"
TOP="mia-osint-${DISPLAY_VERSION}"
WORK="$(mktemp -d -t mia-run-builder.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$(dirname "$OUTPUT")" "$WORK/$TOP"

# Copy only distributable project content. This intentionally excludes local
# investigations, tool environments, caches, frontend dependencies, and builds.
tar -C "$ROOT" \
  --exclude='./.git' \
  --exclude='./.venv' \
  --exclude='./venv' \
  --exclude='./dist' \
  --exclude='./build' \
  --exclude='./node_modules' \
  --exclude='*/node_modules' \
  --exclude='./.pytest_cache' \
  --exclude='./.ruff_cache' \
  --exclude='./.mypy_cache' \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.db' \
  --exclude='mia_reports' \
  --exclude='mia_cases' \
  -cf - . | tar -C "$WORK/$TOP" -xf -

tar -C "$WORK" -czf "$WORK/payload.tar.gz" "$TOP"
cat > "$OUTPUT" <<'HEADER'
#!/usr/bin/env bash
set -Eeuo pipefail
MARKER='__MIA_PAYLOAD_BELOW__'
SELF="${BASH_SOURCE[0]}"
LINE="$(awk -v marker="$MARKER" '$0 == marker {print NR + 1; exit}' "$SELF")"
if [[ -z "$LINE" ]]; then
  printf 'MIA installer error: embedded payload marker was not found.\n' >&2
  exit 1
fi
WORK="$(mktemp -d -t mia-install.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

tail -n "+$LINE" "$SELF" | tar -xzf - -C "$WORK"
PROJECT="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -name 'mia-osint-*' -print -quit)"
if [[ -z "$PROJECT" || ! -f "$PROJECT/install.sh" ]]; then
  printf 'MIA installer error: embedded project could not be extracted.\n' >&2
  exit 1
fi
printf 'MIA one-file Linux installer\n'
printf 'The application, optional tools, and desktop shortcuts are installed for your user account.\n\n'
exec bash "$PROJECT/install.sh" "$@"
exit 0
__MIA_PAYLOAD_BELOW__
HEADER
cat "$WORK/payload.tar.gz" >> "$OUTPUT"
chmod +x "$OUTPUT"
printf 'Built %s (%s)\n' "$OUTPUT" "$VERSION"
