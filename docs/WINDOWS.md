# Windows desktop build and support

MIA 4.2.0 alpha 10 includes the native Windows port introduced in alpha 9. It keeps one shared
**MIA Core** and packages **MIA Discover** and **MIA Workbench** in a Tauri desktop
shell. The normal Windows user does not need to install Python, Node.js, Rust, or
open a terminal.

## User installation

The Windows release asset is:

```text
MIA-4.2.0-alpha.10-Windows-x64-Setup.exe
```

1. Download the setup executable and its SHA-256 file from the same GitHub release.
2. Verify the checksum when possible.
3. Run the installer.
4. Open **MIA** from the Start menu.
5. Choose **MIA Discover** or **MIA Workbench**.

Alpha installers are initially unsigned. Windows SmartScreen may therefore show
an unknown-publisher warning. Do not run a file whose hash differs from the
published checksum.

The installer is per-user by default and does not require administrator access.
MIA Core starts on a random localhost port, communicates only with the desktop
window, and stops when the application closes.

## Windows data locations

MIA stores application state outside the installation directory so upgrades do
not remove cases or settings.

```text
%LOCALAPPDATA%\MIA\
├── cases\
├── reports\
├── logs\
├── plugins\
├── tools\
├── bin\
├── mia.db
├── knowledge.db
└── cache.db

%APPDATA%\MIA\
└── config.yaml
```

Secrets are stored through the operating-system keyring when a supported
keyring backend is available.

## Initial native tool set

The Windows package manager classifies tools before installation. The starter
`windows-core` group contains:

- Maigret;
- Sherlock;
- Holehe.

MIA's built-in HTTP verification, profile parsing, normalization, correlation,
case storage, reports, and both interfaces are also available. Unsupported
Linux-only tools are shown as unavailable instead of being attempted silently.
Future releases can add native, bundled, or WSL-backed integrations after each
one has dedicated tests.

## Building the installer on Windows

Prerequisites for contributors:

- Windows 11 or a current Windows Server runner;
- Python 3.11 available as `python` on `PATH`;
- Node.js 22 and npm;
- a stable Rust MSVC toolchain;
- Microsoft C++ Build Tools and WebView2 prerequisites required by Tauri.

From a PowerShell prompt at the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./packaging/windows/build-desktop.ps1
```

The script:

1. creates an isolated Python 3.11 build environment;
2. runs the Python and Ruff checks;
3. builds Discover and Workbench;
4. freezes MIA Core with PyInstaller;
5. bundles `uv.exe` as a managed tool-runtime sidecar;
6. smoke-tests both sidecar modes on random localhost ports;
7. builds the Tauri NSIS installer;
8. silently installs it and checks the bundled desktop, Core, `uv`, and
   uninstaller executables;
9. silently uninstalls it;
10. writes the installer and SHA-256 file to `dist/windows/`.

Skip the repeated Python test suite during local packaging only when it already
passed in the same checkout:

```powershell
./packaging/windows/build-desktop.ps1 -SkipTests
```

## GitHub Actions

The workflow `.github/workflows/windows-desktop.yml` runs on a Windows x64
runner. It can be started manually, runs automatically when Windows desktop
sources change on `main`, and runs for version tags. The artifact is explicitly
named `unsigned` until a trusted code-signing process is configured.

## Architecture

```text
MIA.exe (Tauri)
├── launcher window
├── Discover mode
├── Workbench mode
└── mia-core-x86_64-pc-windows-msvc.exe (PyInstaller sidecar)
    ├── FastAPI / Uvicorn on 127.0.0.1:<random-port>
    ├── shared scanners and parsers
    ├── package manager
    └── local case and settings storage
```

The Tauri shell and MIA Core exchange a short-lived handshake file containing
the selected local URL. The shell rejects non-loopback URLs. No fixed desktop
port is assumed.

## Current alpha limitations

- Only x86-64 Windows is packaged initially.
- The release workflow produces an unsigned installer until code signing is set up.
- Linux-only tools are not automatically translated through WSL.
- The installer has to be produced on a Windows build machine or Windows CI.
- Windows 10 is classified as best-effort until tested on a clean supported image;
  Windows 11 is the primary alpha target.
- Antivirus reputation may be poor for new, unsigned PyInstaller/Tauri binaries.
  Report detections with the exact file hash and vendor name; never disable
  protection globally to install MIA.
