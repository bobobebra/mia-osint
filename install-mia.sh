#!/usr/bin/env bash
# Friendly MIA installer entry point.
#
# When this script is inside a MIA source archive it runs the bundled installer.
# When downloaded by itself it fetches the latest one-file Linux installer from
# the configured GitHub repository and verifies it when checksums are available.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/install.sh" && -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  exec bash "$SCRIPT_DIR/install.sh" "$@"
fi

REPOSITORY="${MIA_GITHUB_REPOSITORY:-bobobebra/mia-osint}"
ASSET="${MIA_LINUX_INSTALLER_ASSET:-MIA-Linux-Installer.run}"
BASE_URL="${MIA_RELEASE_BASE_URL:-https://github.com/$REPOSITORY/releases/latest/download}"
TMP_DIR="$(mktemp -d -t mia-installer.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT
INSTALLER="$TMP_DIR/$ASSET"
CHECKSUMS="$TMP_DIR/SHA256SUMS.txt"

if ! command -v curl >/dev/null 2>&1; then
  printf 'MIA installer error: curl is required to download the release.\n' >&2
  exit 1
fi

printf 'Downloading the latest MIA Linux installer…\n'
curl --fail --location --silent --show-error "$BASE_URL/$ASSET" -o "$INSTALLER"

if curl --fail --location --silent --show-error "$BASE_URL/SHA256SUMS.txt" -o "$CHECKSUMS"; then
  expected="$(awk -v asset="$ASSET" '$2 == asset || $2 == "*" asset {print $1; exit}' "$CHECKSUMS")"
  if [[ -n "$expected" ]]; then
    if command -v sha256sum >/dev/null 2>&1; then
      actual="$(sha256sum "$INSTALLER" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
      actual="$(shasum -a 256 "$INSTALLER" | awk '{print $1}')"
    else
      printf 'MIA installer warning: no SHA-256 utility is available; checksum was not verified.\n' >&2
      actual="$expected"
    fi
    if [[ "$actual" != "$expected" ]]; then
      printf 'MIA installer error: downloaded installer checksum does not match the release.\n' >&2
      exit 1
    fi
    printf 'Checksum verified.\n'
  fi
else
  printf 'MIA installer warning: release checksums were unavailable.\n' >&2
fi

exec bash "$INSTALLER" "$@"
