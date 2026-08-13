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

# The scheduled task is a watchdog. Never terminate an arbitrary process that
# happens to own the configured port. A healthy project backend needs no work;
# any other listener is an explicit configuration error.
$listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" `
        -ErrorAction SilentlyContinue
    $commandLine = [string]$owner.CommandLine
    if ($commandLine -match 'football_agents\.cli serve' -and $commandLine -match '--port 8000') {
        "[$([DateTimeOffset]::Now.ToString('o'))] backend already healthy (PID $($listener.OwningProcess))" |
            Add-Content -LiteralPath $logPath
        exit 0
    }
    throw "Port 8000 is occupied by PID $($listener.OwningProcess); refusing to stop an unrelated process."
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
