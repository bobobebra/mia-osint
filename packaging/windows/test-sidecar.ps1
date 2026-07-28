param(
  [Parameter(Mandatory = $true)][string]$CoreExe,
  [ValidateSet("discover", "workbench")][string]$Mode = "discover"
)

$ErrorActionPreference = "Stop"
$Handshake = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.json"
Remove-Item $Handshake -Force -ErrorAction SilentlyContinue
$Process = Start-Process -FilePath $CoreExe -ArgumentList @(
  "--mode", $Mode,
  "--port", "0",
  "--handshake", $Handshake
) -PassThru -WindowStyle Hidden

try {
  $Deadline = (Get-Date).AddSeconds(45)
  while ((Get-Date) -lt $Deadline -and -not (Test-Path $Handshake)) {
    if ($Process.HasExited) { throw "MIA Core exited before creating its handshake file." }
    Start-Sleep -Milliseconds 200
  }
  if (-not (Test-Path $Handshake)) { throw "MIA Core did not create a handshake within 45 seconds." }
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
  Remove-Item $Handshake -Force -ErrorAction SilentlyContinue
}
