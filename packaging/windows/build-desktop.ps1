param(
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "../..")
Set-Location $Root
$Version = "4.2.0-alpha.9"
$Target = "x86_64-pc-windows-msvc"
$BuildRoot = Join-Path $Root "build/windows"
$Venv = Join-Path $BuildRoot "venv"
$Python = Join-Path $Venv "Scripts/python.exe"
$BinaryDir = Join-Path $Root "desktop/src-tauri/binaries"
$ReleaseDir = Join-Path $Root "dist/windows"

Remove-Item -Recurse -Force $BuildRoot, $ReleaseDir, $BinaryDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $BuildRoot, $BinaryDir, $ReleaseDir | Out-Null

$BuilderPython = (Get-Command python -ErrorAction Stop).Source
& $BuilderPython -c "import sys; assert sys.version_info[:2] == (3, 11), f'Python 3.11 required, got {sys.version}'"
& $BuilderPython -m venv $Venv
& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]" pyinstaller

if (-not $SkipTests) {
  & $Python -m pytest -q
  & $Python -m ruff check src tests
}

npm --prefix frontend-discover ci
npm --prefix frontend-discover run build
npm --prefix frontend-workbench ci
npm --prefix frontend-workbench run build

& $Python -m PyInstaller packaging/windows/mia-core.spec `
  --workpath "$BuildRoot/pyinstaller/work" `
  --distpath "$BuildRoot/pyinstaller/dist" `
  --noconfirm

Copy-Item "$BuildRoot/pyinstaller/dist/mia-core.exe" "$BinaryDir/mia-core-$Target.exe" -Force
$Uv = (& $Python -c "import shutil; print(shutil.which('uv') or '')").Trim()
if (-not $Uv -or -not (Test-Path $Uv)) { throw "The uv.exe dependency was not found in the Windows build environment." }
Copy-Item $Uv "$BinaryDir/uv-$Target.exe" -Force

./packaging/windows/test-sidecar.ps1 -CoreExe "$BinaryDir/mia-core-$Target.exe" -Mode discover
./packaging/windows/test-sidecar.ps1 -CoreExe "$BinaryDir/mia-core-$Target.exe" -Mode workbench

npm --prefix desktop ci
npm --prefix desktop run build

$Setup = Get-ChildItem "desktop/src-tauri/target/release/bundle/nsis" -Filter "*.exe" | Select-Object -First 1
if (-not $Setup) { throw "Tauri did not produce an NSIS installer." }
$Destination = Join-Path $ReleaseDir "MIA-$Version-Windows-x64-Setup.exe"
Copy-Item $Setup.FullName $Destination -Force
Get-FileHash $Destination -Algorithm SHA256 | ForEach-Object {
  "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($Destination))"
} | Set-Content (Join-Path $ReleaseDir "MIA-$Version-Windows-x64-SHA256.txt") -Encoding ascii

Write-Host "Windows installer: $Destination"
