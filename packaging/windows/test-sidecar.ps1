param(
  [Parameter(Mandatory = $true)][string]$CoreExe,
  [Parameter(Mandatory = $true)][string]$ExpectedVersion,
  [ValidateSet("discover", "workbench")][string]$Mode = "discover"
)

$ErrorActionPreference = "Stop"
$Handshake = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.json"
$Stdout = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.stdout.log"
$Stderr = Join-Path $env:TEMP "mia-sidecar-$Mode-$PID.stderr.log"
Remove-Item $Handshake, $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
$SelfTest = Start-Process -FilePath $CoreExe -ArgumentList @(
  "--self-test",
  "--handshake", $Handshake
) -PassThru -Wait -WindowStyle Hidden
if ($SelfTest.ExitCode -ne 0) {
  $Failure = if (Test-Path $Handshake) {
    (Get-Content $Handshake -Raw | ConvertFrom-Json).error
  } else {
    "MIA Core did not create a self-test result."
  }
  throw "MIA Core plugin self-test failed: $Failure"
}
$SelfTestResult = Get-Content $Handshake -Raw | ConvertFrom-Json
if ($SelfTestResult.status -ne "ok" -or $SelfTestResult.plugin_count -lt 1) {
  throw "MIA Core plugin self-test returned an invalid result."
}
if ($SelfTestResult.version -ne $ExpectedVersion) {
  throw "Expected $ExpectedVersion, got $($SelfTestResult.version)."
}
Write-Host "$Mode packaged plugin discovery passed with $($SelfTestResult.plugin_count) plugins."
Remove-Item $Handshake -Force

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
  if ($Health.version -ne $ExpectedVersion) { throw "Expected $ExpectedVersion, got $($Health.version)." }
  Write-Host "$Mode sidecar smoke test passed at $($Ready.url)."
}
finally {
  if (-not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $Handshake, $Stdout, $Stderr -Force -ErrorAction SilentlyContinue
}
