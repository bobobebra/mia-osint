param(
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "../..")
Set-Location $Root
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
$PackageVersion = (& $BuilderPython -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
$Version = $PackageVersion -replace 'a(\d+)$', '-alpha.$1'
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
$Uv = Join-Path $Venv "Scripts/uv.exe"
if (-not (Test-Path $Uv)) { throw "The uv.exe dependency was not found in the Windows build environment." }
Copy-Item $Uv "$BinaryDir/uv-$Target.exe" -Force

./packaging/windows/test-sidecar.ps1 -CoreExe "$BinaryDir/mia-core-$Target.exe" -ExpectedVersion $PackageVersion -Mode discover
./packaging/windows/test-sidecar.ps1 -CoreExe "$BinaryDir/mia-core-$Target.exe" -ExpectedVersion $PackageVersion -Mode workbench

npm --prefix desktop ci
npm --prefix desktop run build

$Setup = Get-ChildItem "desktop/src-tauri/target/release/bundle/nsis" -Filter "*.exe" | Select-Object -First 1
if (-not $Setup) { throw "Tauri did not produce an NSIS installer." }

if (-not $SkipTests) {
  $InstallRoot = Join-Path $BuildRoot "installed"
  $Installer = Start-Process -FilePath $Setup.FullName `
    -ArgumentList @("/S", "/D=$InstallRoot") `
    -PassThru -Wait -WindowStyle Hidden
  if ($Installer.ExitCode -ne 0) { throw "NSIS installer exited with code $($Installer.ExitCode)." }

  $ExpectedInstalledFiles = @("mia-desktop.exe", "mia-core.exe", "uv.exe", "uninstall.exe")
  try {
    foreach ($Name in $ExpectedInstalledFiles) {
      $InstalledFile = Join-Path $InstallRoot $Name
      if (-not (Test-Path $InstalledFile)) { throw "Installed application is missing $Name." }
    }
    Write-Host "Windows silent install smoke test passed."
  }
  finally {
    $Uninstaller = Join-Path $InstallRoot "uninstall.exe"
    if (Test-Path $Uninstaller) {
      $Uninstall = Start-Process -FilePath $Uninstaller `
        -ArgumentList "/S" `
        -PassThru -Wait -WindowStyle Hidden
      if ($Uninstall.ExitCode -ne 0) { throw "NSIS uninstaller exited with code $($Uninstall.ExitCode)." }
    }
  }
}

$Destination = Join-Path $ReleaseDir "MIA-$Version-Windows-x64-Setup.exe"
Copy-Item $Setup.FullName $Destination -Force
Get-FileHash $Destination -Algorithm SHA256 | ForEach-Object {
  "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($Destination))"
} | Set-Content (Join-Path $ReleaseDir "MIA-$Version-Windows-x64-SHA256.txt") -Encoding ascii

Write-Host "Windows installer: $Destination"
