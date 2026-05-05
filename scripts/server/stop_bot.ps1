$ErrorActionPreference = "Continue"

$Base = "C:\Bots\HundekuchenBot"
$Logs = Join-Path $Base "logs"
$PidFile = Join-Path $Base "bot.pid"

New-Item -ItemType Directory -Force $Logs | Out-Null

if (!(Test-Path $PidFile)) {
    Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Keine PID-Datei gefunden."
    exit 0
}

$pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue

if ($pidValue) {
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) {
        Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Stoppe Bot PID $pidValue"
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    } else {
        Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Prozess aus PID-Datei läuft nicht mehr: $pidValue"
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Add-Content "$Logs\bot-control.log" "[$(Get-Date)] Bot gestoppt."
