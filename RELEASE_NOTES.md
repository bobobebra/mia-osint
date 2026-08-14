# MIA 4.2.0 alpha 10 release notes

## Read this first

MIA remains an **early, substantially AI-assisted public alpha**. It has not
received a professional security audit or independent accuracy validation.
Automated OSINT results and AI summaries are leads, not proof of identity,
ownership, intent, compromise, or wrongdoing.

## Complete, verified installer release

Alpha 10 publishes one complete prerelease only after all supported artifacts
finish building. The release contains the Windows x64 NSIS setup, its dedicated
SHA-256 file, the self-extracting Linux installer, the small Linux bootstrapper,
the Python wheel and source distribution, the source ZIP, and one checksum file
covering the complete set.

The Windows job now runs the generated setup silently in a temporary directory,
checks that the desktop application, MIA Core sidecar, `uv`, and uninstaller were
actually installed, and then runs the uninstaller. Discover and Workbench
sidecars are still health-checked before the setup is built. A missing or empty
artifact prevents the GitHub prerelease from being published.

## Native Windows port

Alpha 9 is the first release whose shared MIA Core is designed to run natively
on Windows. It adds:

- Windows application-data and configuration paths;
- hidden scanner processes without flashing console windows;
- process-tree timeout and cancellation handling;
- Windows virtual-environment and executable discovery;
- managed `.cmd` wrappers instead of POSIX symlinks;
- optional `winget` prerequisite handling;
- a Windows capability status for each catalog tool;
- a conservative `windows-core` starter group;
- a PyInstaller MIA Core sidecar;
- a Tauri launcher for Discover and Workbench;
- a current-user NSIS installer configuration;
- a Windows build and smoke-test workflow.

The Windows installer launches MIA Core on an available random loopback port.
The desktop shell learns that port through a short-lived handshake file and
rejects non-loopback destinations. Discover and Workbench continue to use the
same backend, data model, verification, storage, and package manager.

## Windows user experience

The intended release asset is:

```text
MIA-4.2.0-alpha.10-Windows-x64-Setup.exe
```

A user installs it normally, opens **MIA**, and chooses:

- **MIA Discover** for guided selector and public-account searches;
- **MIA Workbench** for cases, evidence graphs, review queues, packages, and
  advanced analysis.

Python, FastAPI, Uvicorn, the frontends, and the `uv` tool runtime are bundled.
The application stores persistent data under `%LOCALAPPDATA%\MIA` and user
configuration under `%APPDATA%\MIA`.

The Windows artifact remains unsigned and is distributed with a SHA-256 file.
Windows 11 x64 is the primary alpha target. See `docs/WINDOWS.md`.

## Initial Windows tool coverage

The `windows-core` group includes Maigret, Sherlock, and Holehe. MIA's internal
page verification, parsers, account correlation, evidence graph, reports, and
assistant controls are built in. Catalog entries without a verified Windows
installation path are marked unsupported rather than attempted.

This release does not claim complete parity with the Linux 40-tool catalogue.
WSL-backed integrations are deferred until a separate bridge is implemented and
tested.

## Linux remains supported

Alpha 8's one-file Linux installer, application-menu launchers, transactional
upgrade behavior, and `mia repair` command remain intact. The Windows work is a
platform layer and packaging addition, not a separate fork.

## Build the Windows installer

On a Windows development machine:

```powershell
./packaging/windows/build-desktop.ps1
```

Or publish a matching version tag and let the **Release** Actions workflow build
the complete asset set. It builds the exact PyInstaller sidecar, smoke-tests
Discover and Workbench, installs and uninstalls the generated NSIS setup, and
publishes it only after the portable assets are also ready.
