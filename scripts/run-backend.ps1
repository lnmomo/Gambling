$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeDir = Join-Path $projectRoot "data\runtime"
$logPath = Join-Path $runtimeDir "backend-service.log"
$stdoutPath = Join-Path $runtimeDir "backend-service.stdout.log"
$stderrPath = Join-Path $runtimeDir "backend-service.stderr.log"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found: $python"
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Set-Location -LiteralPath $projectRoot

# Clear any stale process still bound to port 8000 before starting. The
# scheduler's IgnoreNew guard prevents the healthy instance from being killed;
# this only reaps leftover python.exe that failed to release the port.
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

"[$([DateTimeOffset]::Now.ToString('o'))] backend service starting" | Add-Content -LiteralPath $logPath
$process = Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "football_agents.cli", "serve", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru `
    -Wait
$exitCode = $process.ExitCode
"[$([DateTimeOffset]::Now.ToString('o'))] backend service exited with code $exitCode" | Add-Content -LiteralPath $logPath
exit $exitCode
