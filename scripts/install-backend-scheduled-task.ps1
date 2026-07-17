param(
    [string]$TaskName = "FootballAgentsBackend",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run-backend.ps1"
$hiddenLauncher = Join-Path $PSScriptRoot "run-backend-hidden.vbs"
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Backend runner was not found: $runner"
}
if (-not (Test-Path -LiteralPath $hiddenLauncher)) {
    throw "Hidden backend launcher was not found: $hiddenLauncher"
}

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "//B //Nologo `"$hiddenLauncher`"" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$task = New-ScheduledTask -Action $action -Trigger @($trigger, $watchdogTrigger) `
    -Principal $principal -Settings $settings `
    -Description "Runs the football research API continuously; a minutely trigger restores failed collection."
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath
