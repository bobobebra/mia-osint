param(
  [Parameter(Mandatory = $true)][string]$CoreExe,
  [ValidateSet("discover", "workbench")][string]$Mode = "discover"
)

$ErrorActionPreference = "Stop"
$Handshake = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.json"
$Stdout = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.stdout.log"
$Stderr = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.stderr.log"
Remove-Item $Handshake, $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
$Process = Start-Process -FilePath $CoreExe -ArgumentList @(
  "--mode", $Mode,
  "--port", "0",
  "--handshake", $Handshake
) -PassThru -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr

function Get-SidecarDiagnostics {
  $Parts = @()
  if (Test-Path $Stdout) {
    $Parts += "stdout: $((Get-Content $Stdout -Raw -ErrorAction SilentlyContinue).Trim())"
  }
  if (Test-Path $Stderr) {
    $Parts += "stderr: $((Get-Content $Stderr -Raw -ErrorAction SilentlyContinue).Trim())"
  }
  return ($Parts -join [Environment]::NewLine)
}

try {
  $Deadline = (Get-Date).AddSeconds(120)
  while ((Get-Date) -lt $Deadline -and -not (Test-Path $Handshake)) {
    if ($Process.HasExited) {
      throw "MIA Core exited before creating its handshake file.$([Environment]::NewLine)$(Get-SidecarDiagnostics)"
    }
    Start-Sleep -Milliseconds 200
  }
  if (-not (Test-Path $Handshake)) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue
    throw "MIA Core did not create a handshake within 120 seconds.$([Environment]::NewLine)$(Get-SidecarDiagnostics)"
  }
  $Ready = Get-Content $Handshake -Raw | ConvertFrom-Json
  if ($Ready.status -ne "ready") { throw "MIA Core startup failed: $($Ready.error)" }
  $Health = Invoke-RestMethod -Uri "$($Ready.url)/api/health" -TimeoutSec 15
  if ($Health.status -ne "ok") { throw "Unexpected health response." }
  if ($Health.version -ne "4.2.0a9") { throw "Expected 4.2.0a9, got $($Health.version)." }
  Write-Host "$Mode sidecar smoke test passed at $($Ready.url)."
}
finally {
  if (-not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $Handshake, $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
}
