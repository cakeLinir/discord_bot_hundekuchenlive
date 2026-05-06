$ErrorActionPreference = "Continue"

$Base = $env:HUNDEKUCHEN_BOT_BASE
if ([string]::IsNullOrWhiteSpace($Base)) {
    $Base = "C:\Bots\HundekuchenBot"
}

$Repo = Join-Path $Base "repo"
$Scripts = Join-Path $Base "scripts"
$Logs = Join-Path $Base "logs"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Repo "bot\.env"
$EntryFile = Join-Path $Base "entry_module.txt"
$DefaultEntryModule = "bot.apps.discord_bot.main"

New-Item -ItemType Directory -Force $Logs | Out-Null

$ok = $true

function Fail {
    param([string]$Message)
    Write-Warning "[FEHLT/FEHLER] $Message"
    $script:ok = $false
}

function Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Ok {
    param([string]$Message)
    Write-Host "[OK] $Message"
}

function Check-Path {
    param(
        [string]$Label,
        [string]$Path
    )

    if (Test-Path $Path) {
        Ok "$Label $Path"
    } else {
        Fail "$Label $Path"
    }
}

function Get-DotEnvValue {
    param(
        [string]$Name,
        [string]$Default = ""
    )

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
            return $entry
        }
    }

    return $DefaultEntryModule
}

Check-Path "Base:" $Base
Check-Path "Repo:" $Repo
Check-Path "Scripts:" $Scripts
Check-Path "Logs:" $Logs
Check-Path "Python:" $Python
Check-Path "Env:" $EnvFile
Check-Path "Start-Script:" (Join-Path $Scripts "start_bot.ps1")
Check-Path "Stop-Script:" (Join-Path $Scripts "stop_bot.ps1")

if (Test-Path $Repo) {
    git -C $Repo rev-parse --is-inside-work-tree *> $null

    if ($LASTEXITCODE -eq 0) {
        Ok "Git-Repository gültig."

        $branch = (git -C $Repo branch --show-current).Trim()
        Info "Git Branch: $branch"

        $remote = (git -C $Repo remote -v | Select-Object -First 1)
        Info "Git Remote: $remote"
    } else {
        Fail "Repo ist kein gültiges Git-Repository."
    }
}

$EntryModule = Get-EntryModule
Ok "EntryModule: $EntryModule"

$ModulePath = Join-Path $Repo (($EntryModule -replace "\.", "\") + ".py")

if (Test-Path $ModulePath) {
    Ok "EntryModule-Datei gefunden: $ModulePath"
} else {
    Fail "EntryModule-Datei fehlt: $ModulePath"
}

if (Test-Path $EnvFile) {
    $token = Get-DotEnvValue -Name "DISCORD_TOKEN"

    if ([string]::IsNullOrWhiteSpace($token)) {
        Fail "DISCORD_TOKEN ist nicht gesetzt."
    } else {
        Ok "DISCORD_TOKEN ist gesetzt. Wert wird nicht ausgegeben."
    }

    $heartbeat = Get-DotEnvValue -Name "DISCORD_HEARTBEAT_TIMEOUT" -Default "45"

    if ($heartbeat -ne "45") {
        Info "DISCORD_HEARTBEAT_TIMEOUT=$heartbeat. Stabiler bekannter Wert war 45."
    } else {
        Ok "DISCORD_HEARTBEAT_TIMEOUT=45"
    }

    $apiEnabled = Get-DotEnvValue -Name "DISCORD_BOT_API_ENABLED" -Default "false"
    if ($apiEnabled -in @("1", "true", "yes", "on")) {
        $apiFile = Join-Path $Repo "bot\apps\discord_bot\api.py"

        if (Test-Path $apiFile) {
            Ok "DISCORD_BOT_API_ENABLED=true und api.py existiert."
        } else {
            Fail "DISCORD_BOT_API_ENABLED=true, aber api.py fehlt."
        }
    }

    $jarvisEnabled = Get-DotEnvValue -Name "JARVIS_ENABLED" -Default "false"
    if ($jarvisEnabled -in @("1", "true", "yes", "on")) {
        $jarvisClient = Join-Path $Repo "bot\apps\discord_bot\jarvis_client.py"

        if (Test-Path $jarvisClient) {
            Ok "JARVIS_ENABLED=true und jarvis_client.py existiert."
        } else {
            Fail "JARVIS_ENABLED=true, aber jarvis_client.py fehlt."
        }
    }
}

if (Test-Path (Join-Path $Repo "requirements.txt")) {
    Ok "requirements.txt gefunden."
} else {
    Info "requirements.txt fehlt. Falls Dependencies manuell verwaltet werden, ist das okay."
}

if ($ok) {
    Write-Host "Preflight bestanden."
    exit 0
}

Write-Warning "Preflight fehlgeschlagen."
exit 1