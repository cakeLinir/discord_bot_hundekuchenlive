$ErrorActionPreference = "Continue"

$Base = $env:HUNDEKUCHEN_BOT_BASE
if ([string]::IsNullOrWhiteSpace($Base)) {
    $Base = "C:\Bots\HundekuchenBot"
}

$Repo = Join-Path $Base "repo"
$Logs = Join-Path $Base "logs"
$PidFile = Join-Path $Base "bot.pid"
$EntryFile = Join-Path $Base "entry_module.txt"
$DefaultEntryModule = "bot.apps.discord_bot.main"

New-Item -ItemType Directory -Force $Logs | Out-Null

function Write-ControlLog {
    param([string]$Message)
    Add-Content "$Logs\bot-control.log" "[$(Get-Date)] $Message"
}

function Get-EntryModule {
    if (Test-Path $EntryFile) {
        $entry = (Get-Content $EntryFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if (![string]::IsNullOrWhiteSpace($entry)) {
            return $entry
        }
    }

    return $DefaultEntryModule
}

Write-ControlLog "Stop requested."

$EntryModule = Get-EntryModule

# 1) PID-Datei stoppen
if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($pidValue) {
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue

        if ($proc) {
            Write-ControlLog "Stoppe Bot per PID-Datei: PID $pidValue"
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        } else {
            Write-ControlLog "PID-Datei vorhanden, Prozess läuft nicht mehr: PID $pidValue"
        }
    }
} else {
    Write-ControlLog "Keine PID-Datei gefunden."
}

# 2) Fallback: alle Prozesse stoppen, die exakt das EntryModule starten
$botProcesses = Get-CimInstance Win32_Process |
Where-Object {
    $_.Name -in @("python.exe", "py.exe") -and
    $_.CommandLine -like "*-m $EntryModule*"
}

foreach ($p in $botProcesses) {
    Write-ControlLog "Stoppe Bot-Fallback PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue

Write-ControlLog "Bot gestoppt."