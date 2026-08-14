# Installation

## Status and scope

MIA alpha 10 supports a native Windows desktop package and the existing Linux
managed installation. Both use one MIA Core, keep persistent data outside the
application directory, and avoid installing packages into the system Python
environment.

Windows 11 x64 is the primary Windows alpha target. Linux package-manager
recognition remains best effort rather than certification for every distribution,
derivative, release, mirror, architecture, or immutable image.

## Windows installation

Download:

```text
MIA-4.2.0-alpha.10-Windows-x64-Setup.exe
MIA-4.2.0-alpha.10-Windows-x64-SHA256.txt
```

Verify the installer hash, run the setup program, and open **MIA** from the Start
menu. The installer is per-user by default. It bundles the MIA Core runtime and
does not require a separate Python, Node.js, or Rust installation.

MIA stores Windows state under `%LOCALAPPDATA%\MIA` and configuration under
`%APPDATA%\MIA`. The initial native scanner group is `windows-core`: Maigret,
Sherlock, and Holehe. Unsupported tools are labelled unavailable instead of
being installed with Linux recipes.

The public alpha installer is unsigned. Do not disable Windows security globally;
verify the checksum and report any antivirus detection with the exact hash.

For build instructions and current limitations, see [`WINDOWS.md`](WINDOWS.md).

## Linux release installation


Download `MIA-Linux-Installer.run` from the GitHub release and run:

```console
bash MIA-Linux-Installer.run --yes --launch discover
```

The one-file installer contains the complete MIA source release. It extracts to
a temporary directory, runs the normal verified installer, creates the managed
runtime, and removes the temporary extraction afterward.

Install only MIA Core and the two interfaces:

```console
bash MIA-Linux-Installer.run --mia-only --yes
```

Skip application-menu shortcuts:

```console
bash MIA-Linux-Installer.run --mia-only --no-desktop --yes
```

A small `install-mia.sh` bootstrap script can download the latest installer from
the configured GitHub repository. When a release `SHA256SUMS.txt` file is
available, it verifies the downloaded installer before executing it. Review any
remote installer script before running it.

## Source-archive installation

```console
unzip MIA-v4.2.0-alpha.10.zip
cd mia-osint-4.2.0-alpha.10
bash install.sh
```

Preview changes first:

```console
bash install.sh --dry-run --yes
```

## Linux installation model

MIA separates the core application from optional OSINT commands:

1. the host package manager provides basic prerequisites when allowed;
2. MIA is installed in a user-owned virtual environment;
3. `mia pkg` installs optional Python, Go, Cargo, Git, or binary tools into
   managed roots where practical;
4. stable command links or wrappers are placed in `~/.local/bin` or an existing
   `~/bin` already present on `PATH`;
5. Discover and Workbench application-menu entries are created for the current
   Linux user unless `--no-desktop` is supplied;
6. system packages are recorded but preserved on ordinary uninstall.

## Default Linux installation

The default installs MIA and asks the package manager to install the `core`
scanner group:

```text
maigret, sherlock, holehe, spiderfoot, exiftool, whois
```

If one optional tool fails, the installer reports a warning and leaves MIA Core
and the remaining tools usable.

## Linux installer options

MIA only:

```console
bash install.sh --mia-only
```

Additional groups:

```console
bash install.sh --with username --with email
bash install.sh --with domain --include-mixed
```

Individual tools:

```console
bash install.sh --tool ghunt --tool shodan
```

Every local/passive catalog entry:

```console
bash install.sh --all-tools
```

Also include mixed/direct-request tools:

```console
bash install.sh --all-tools --include-mixed
```

Do not create desktop launchers:

```console
bash install.sh --no-desktop
```

Launch an interface after installation:

```console
bash install.sh --launch discover
bash install.sh --launch workbench
```

Non-interactive and dry-run modes:

```console
bash install.sh --yes
bash install.sh --dry-run --yes
```

## Upgrade safety

Before replacing the managed MIA environment, the installer moves the previous
environment to a temporary backup. If environment creation, package installation,
dependency validation, or exact version verification fails, the installer
restores the previous working environment.

Cases, reports, settings, secrets, package state, and optional-tool roots live
outside the extracted release directory and are not removed during an ordinary
upgrade.

## Linux desktop launchers

The default installation creates:

- **MIA Discover**
- **MIA Workbench**

They are stored under the current user's XDG data directory, normally:

```text
~/.local/share/applications/
~/.local/share/icons/hicolor/scalable/apps/
```

Manage them with:

```console
mia desktop status
mia desktop install
mia desktop remove
```

## Repair and diagnostics

Check MIA Core, packaged UI assets, the local database, plugin availability, and
desktop launchers:

```console
mia repair
```

Also reinstall or repair the recommended scanner group:

```console
mia repair --install-tools --yes
```

Additional diagnostics:

```console
mia doctor
mia pkg doctor
```

## Recognized Linux package managers

| Family | Manager | Typical distributions |
|---|---|---|
| Debian | `apt` | Debian, Ubuntu, Mint, Kali, Pop!_OS |
| Fedora/RHEL | `dnf` | Fedora and compatible derivatives |
| Arch | `pacman` | Arch, EndeavourOS, Manjaro |
| openSUSE | `zypper` | Tumbleweed, Leap, derivatives |
| Alpine | `apk` | Alpine |
| Homebrew Linux | `brew` | User-managed and some immutable hosts |
| Manual | `none` | Existing prerequisites only |

Forbid all system-package operations:

```console
bash install.sh --skip-system-packages
```

This requires Git, a suitable Python, certificates, and any Go, Cargo, or system
commands required by selected tools to exist already.

## Linux installed locations

```text
~/.local/bin/ or ~/bin/
├── mia
└── optional tool wrappers/links

~/.local/share/mia/
├── venv/                    MIA Core environment
├── package-state.json       MIA-managed package inventory
├── packages/<tool-id>/      isolated optional tool roots
├── package-backups/         replaced command backups
├── bootstrap/               uv bootstrap when needed
├── python/                  uv-managed Python runtimes
└── uv-cache/

~/.local/state/mia/
└── install.log
```

Environment overrides:

```console
MIA_VENV=/custom/venv
MIA_STATE_DIR=/custom/state
MIA_BIN_DIR=/custom/bin
MIA_PACKAGE_MANAGER=none
```

## Uninstallation

Remove MIA-managed optional tools, MIA Core, and MIA-managed desktop entries:

```console
bash uninstall.sh
```

Keep optional tools:

```console
bash uninstall.sh --keep-packages
```

Request removal of system packages installed through MIA:

```console
bash uninstall.sh --remove-system-packages
```

System-package removal is opt-in. Reports, configuration, and investigation
history are preserved unless explicitly removed.

## Windows repair and diagnostics

The Windows desktop package validates the bundled MIA Core sidecar at build time.
Inside Workbench, package status shows whether a tool is supported, installed, or
unavailable on Windows. Persistent user data is not removed by a normal app
upgrade or uninstall.

For a developer checkout, MIA Core can also be tested from PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python -m mia.desktop_backend --mode discover --port 0 --handshake "$env:TEMP\mia.json"
```

## Development installation on Linux

```console
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```
