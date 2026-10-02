$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OperatorDir = Join-Path $RepoRoot "local_operator"
$ConfigPath = Join-Path $OperatorDir "operator_config.json"
$StateDir = Join-Path $env:USERPROFILE ".white_space\operator"
$TaskName = "WHITE_SPACE Local Operator"

$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) {
    $Python = (Get-Command py -ErrorAction SilentlyContinue)
}
if (-not $Python) {
    throw "Python 3 is required."
}

$Gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $Gh) {
    throw "GitHub CLI (gh) is required."
}
& $Gh.Source auth status | Out-Null

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

if (-not (Test-Path $ConfigPath)) {
    $Config = [ordered]@{
        repository = "anakindark/WHITE_SPACE_6.0"
        issue_number = 4
        allowed_authors = @("anakindark")
        host_id = $env:COMPUTERNAME
        poll_seconds = 30
        state_dir = $StateDir
    }
    $Config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8
}

$LauncherPath = Join-Path $StateDir "run_operator.cmd"
$StdoutLog = Join-Path $StateDir "operator.stdout.log"
$StderrLog = Join-Path $StateDir "operator.stderr.log"
$PythonExe = $Python.Source
$ScriptPath = Join-Path $OperatorDir "ws_local_operator.py"

@"
@echo off
cd /d "$RepoRoot"
"$PythonExe" -u "$ScriptPath" --config "$ConfigPath" 1>>"$StdoutLog" 2>>"$StderrLog"
"@ | Set-Content -Path $LauncherPath -Encoding ASCII

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/d /c `"$LauncherPath`"" -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "WHITE_SPACE local operator installed and started."
Write-Host "Config: $ConfigPath"
Write-Host "Logs: $StateDir"
