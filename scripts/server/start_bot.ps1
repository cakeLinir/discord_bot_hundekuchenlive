$ErrorActionPreference = "Stop"

$Base = $env:HUNDEKUCHEN_BOT_BASE
if ([string]::IsNullOrWhiteSpace($Base)) {
    $Base = "C:\Bots\HundekuchenBot"
}

$Repo = Join-Path $Base "repo"
$Scripts = Join-Path $Base "scripts"
$Logs = Join-Path $Base "logs"
$PidFile = Join-Path $Base "bot.pid"
$EntryFile = Join-Path $Base "entry_module.txt"
$EnvFile = Join-Path $Repo "bot\.env"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$DefaultEntryModule = "bot.apps.discord_bot.main"

New-Item -ItemType Directory -Force $Logs | Out-Null

function Write-ControlLog {
    param([string]$Message)
    Add-Content "$Logs\bot-control.log" "[$(Get-Date)] $Message"
}

function Get-DotEnvValue {
    param(
        [string]$Name,
        [string]$Default = ""
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (![string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }

    if (!(Test-Path $EnvFile)) {
        return $Default
    }

    $pattern = "^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$"
    $line = Get-Content $EnvFile -ErrorAction SilentlyContinue |
        Where-Object { $_ -match $pattern } |
        Select-Object -First 1

    if (!$line) {
        return $Default
    }

    $value = ($line -replace $pattern, '$1').Trim()
    $value = $value.Trim('"').Trim("'")

    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }

    return $value
}

function Get-EntryModule {
    if (Test-Path $EntryFile) {
        $entry = (Get-Content $EntryFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()

        if (![string]::IsNullOrWhiteSpace($entry)) {
            if ($entry -notmatch "^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$") {
                throw "Ungültiges EntryModule in $EntryFile`: $entry"
            }

            return $entry
        }
    }

    return $DefaultEntryModule
}

function Test-LockPortActive {
    param([int]$Port)

    try {
        $conn = Get-NetTCPConnection `
            -LocalAddress 127.0.0.1 `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue

        return $null -ne $conn
    } catch {
        return $false
    }
}

Write-ControlLog "Start requested."

if (!(Test-Path $Repo)) {
    Write-ControlLog "Repo fehlt: $Repo"
    exit 1
}

if (!(Test-Path $Python)) {
    Write-ControlLog "Python venv fehlt: $Python"
    exit 1
}

$EntryModule = Get-EntryModule
$LockPortRaw = Get-DotEnvValue -Name "BOT_INSTANCE_LOCK_PORT" -Default "49291"

try {
    $LockPort = [int]$LockPortRaw
} catch {
    $LockPort = 49291
}

# Preflight vor Start
$Preflight = Join-Path $Scripts "preflight.ps1"
if (Test-Path $Preflight) {
    & $Preflight
    if ($LASTEXITCODE -ne 0) {
        Write-ControlLog "Preflight fehlgeschlagen. Bot wird nicht gestartet."
        exit 1
    }
}

# PID-Datei prüfen
if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-ControlLog "Bot läuft bereits laut PID-Datei mit PID $oldPid"
        exit 0
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# Lock-Port prüfen
if (Test-LockPortActive -Port $LockPort) {
    Write-ControlLog "Bot läuft bereits laut Lock-Port 127.0.0.1:$LockPort"
    exit 0
}

Set-Location $Repo

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BOT_RUNTIME = Get-DotEnvValue -Name "BOT_RUNTIME" -Default "production"

Write-ControlLog "Starte Bot EntryModule=$EntryModule Runtime=$env:BOT_RUNTIME"

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m $EntryModule" `
    -WorkingDirectory $Repo `
    -RedirectStandardOutput "$Logs\bot.out.log" `
    -RedirectStandardError "$Logs\bot.err.log" `
    -PassThru `
    -WindowStyle Hidden

$process.Id | Set-Content $PidFile

Write-ControlLog "Bot gestartet mit PID $($process.Id)"