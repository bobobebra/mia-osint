# MIA Windows desktop shell

This directory contains the native Windows launcher for **MIA Discover** and
**MIA Workbench**. It is a thin Tauri shell around the shared Python **MIA Core**;
no investigation logic is duplicated in Rust or JavaScript.

## Runtime sequence

1. The user opens MIA and chooses Discover or Workbench.
2. Tauri starts the bundled `mia-core` sidecar with a random localhost port.
3. MIA Core writes a short-lived JSON handshake when FastAPI is ready.
4. The shell validates that the URL is loopback-only and navigates to it.
5. Closing MIA terminates the sidecar process.

The bundled sidecars must use Tauri's target-triple naming convention:

```text
src-tauri/binaries/
├── mia-core-x86_64-pc-windows-msvc.exe
└── uv-x86_64-pc-windows-msvc.exe
```

## Build

Run from the repository root on Windows:

```powershell
./packaging/windows/build-desktop.ps1
```

That script builds and tests the Python sidecar before invoking:

```powershell
npm --prefix desktop ci
npm --prefix desktop run build
```

See [`../docs/WINDOWS.md`](../docs/WINDOWS.md) for prerequisites, output names,
data paths, limitations, and the GitHub Actions workflow.
