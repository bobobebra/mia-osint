# PyInstaller specification for the MIA Core sidecar used by Tauri on Windows.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hiddenimports = []
for package in ("keyring.backends", "uvicorn", "websockets", "multipart"):
    hiddenimports.extend(collect_submodules(package))

datas = collect_data_files("mia", include_py_files=False)
for package in ("keyring", "uvicorn", "fastapi", "starlette", "pydantic"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

a = Analysis(
    ["src/mia/desktop_backend.py"],
    pathex=["src", "."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mia-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
