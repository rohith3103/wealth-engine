param(
    [string]$PythonPath = "python",
    [int]$IntervalMinutes = 15,
    [string]$ProjectRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $ProjectRoot "run_cycle.py"

while ($true) {
    & $PythonPath $scriptPath
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}

