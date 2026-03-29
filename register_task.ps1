param(
    [string]$TaskName = "WealthIntelligenceMonitor15m",
    [string]$PythonPath = "python",
    [string]$ProjectRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $ProjectRoot "run_cycle.py"

$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$scriptPath`""
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs the market monitor every 15 minutes." `
    -Force

Write-Host "Registered scheduled task: $TaskName"

