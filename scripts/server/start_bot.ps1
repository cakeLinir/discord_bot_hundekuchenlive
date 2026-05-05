$ErrorActionPreference = "Stop"

$Base = "C:\Bots\HundekuchenBot"
$Repo = Join-Path $Base "repo"
$Logs = Join-Path $Base "logs"
$PidFile = Join-Path $Base "bot.pid"
$EntryFile = Join-Path $Base "entry_module.txt"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force $Logs | Out-Null

if (!(Test-Path $Repo)) {
    Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Repo fehlt: $Repo"
    exit 1
}

if (!(Test-Path $Python)) {
    Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Python venv fehlt: $Python"
    exit 1
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Bot läuft bereits mit PID $oldPid"
        exit 0
    }
}

$EntryModule = $env:BOT_ENTRY_MODULE

if ([string]::IsNullOrWhiteSpace($EntryModule) -and (Test-Path $EntryFile)) {
    $EntryModule = (Get-Content $EntryFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
}

if ([string]::IsNullOrWhiteSpace($EntryModule)) {
    $EntryModule = "bot.apps.discord_bot.main"
}

Set-Location $Repo

Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Starte Bot EntryModule=$EntryModule"

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m $EntryModule" `
    -WorkingDirectory $Repo `
    -RedirectStandardOutput "$Logs\bot.out.log" `
    -RedirectStandardError "$Logs\bot.err.log" `
    -PassThru `
    -WindowStyle Hidden

$process.Id | Set-Content $PidFile

Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Bot gestartet mit PID $($process.Id)"
