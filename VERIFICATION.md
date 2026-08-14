# Release verification record

This records checks for **MIA 4.2.0 alpha 10**. It is not a security audit,
accuracy certification, antivirus guarantee, or certification of every
third-party tool.

## Checks completed in the source environment

- Python version metadata reports `4.2.0a10`.
- The complete test collection contained 181 tests: 180 passed on Linux and the one Windows-only `.cmd` execution test was skipped as intended.
- Ruff passed for `src` and `tests`.
- Python source compiled successfully.
- Windows path, virtual-environment, `.cmd` wrapper, tool capability, and
  `windows-core` regression tests passed.
- Existing CLI, process, desktop, and package-manager regression groups passed
  after the cross-platform changes.
- The dedicated MIA Core sidecar started both Discover and Workbench on dynamic
  localhost ports and returned the expected health version.
- Tauri CLI accepts the alpha 10 configuration schema and recognizes both
  external sidecars and the NSIS target.
- Both existing React applications remain packaged by MIA Core rather than being
  duplicated in the desktop shell.

## Checks performed by the release workflow

`.github/workflows/release.yml` is configured to perform the following on a
Windows x64 runner:

- run the complete Python suite and Ruff;
- build both React applications;
- freeze `mia-core.exe` with PyInstaller;
- bundle the target-triple `uv.exe` sidecar;
- start and health-check Discover and Workbench from the frozen executable;
- compile the Rust/Tauri desktop shell;
- produce a current-user NSIS installer;
- silently install it and verify the four bundled executables;
- silently uninstall it;
- create a SHA-256 file;
- publish it only after the Linux installer, Python packages, and source archive
  have also completed and passed the final asset checks.

## Environment limitation

The final `.exe` cannot be produced or executed in the Linux packaging
environment used for this source release. PyInstaller freezes applications for
the operating system on which it runs, and the Windows NSIS/Tauri build requires
a Windows toolchain. The included Windows CI workflow is therefore the release
builder of record for the executable.

The alpha 9 installer was also downloaded from GitHub, its published SHA-256 was
verified, and its silent install/uninstall cycle completed on Windows with
`mia-desktop.exe`, `mia-core.exe`, `uv.exe`, and `uninstall.exe` present. The
alpha 10 artifact must still be tested manually on clean Windows 11 systems with
Defender and SmartScreen enabled before broad promotion. Code signing, ARM64,
WSL tool integration, and broad Windows 10 validation remain future work.
