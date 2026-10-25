# One-time machine setup for unattended recording. Run from an elevated
# (Administrator) PowerShell after moving the checkout to a new PC:
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_machine.ps1
#
# Installs the bundled Redis (tools/redis, RDB saves disabled) as a Windows
# service and registers StockRecordStart/StockRecordStop. Safe to re-run:
# existing tasks are replaced, an existing Redis service is left alone.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this from an elevated PowerShell (right-click > Run as administrator)."
    exit 1
}

# --- Redis service -----------------------------------------------------
$redisDir = Join-Path $root "tools\redis"
if (-not (Get-Service -Name Redis -ErrorAction SilentlyContinue)) {
    & (Join-Path $redisDir "redis-server.exe") --service-install `
        (Join-Path $redisDir "redis.windows-service.conf") --loglevel verbose
}
Start-Service -Name Redis

# --- Scheduled tasks ---------------------------------------------------
# S4U: runs whether or not the user is logged on. StartWhenAvailable: a run
# missed because the PC was off/asleep fires once it is back (9/25 incident).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

$tasks = @(
    @{ Name = "StockRecordStart"; Script = "record_market_open.ps1"; At = "08:55" },
    @{ Name = "StockRecordStop"; Script = "stop_record.ps1"; At = "20:05" }
)
foreach ($t in $tasks) {
    $scriptPath = Join-Path $PSScriptRoot $t.Script
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
        -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At $t.At
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
}

# Task Scheduler history, used to diagnose missed runs.
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
# Never sleep on AC power, so the 08:55 trigger fires on time.
powercfg /change standby-timeout-ac 0

Get-ScheduledTask -TaskName "StockRecordStart", "StockRecordStop" |
    Select-Object TaskName, State, @{ n = "Next"; e = { (Get-ScheduledTaskInfo $_).NextRunTime } }
Get-Service -Name Redis
