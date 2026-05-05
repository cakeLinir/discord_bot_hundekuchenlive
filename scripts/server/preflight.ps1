$ErrorActionPreference = "Continue"

$Base = "C:\Bots\HundekuchenBot"
$Repo = Join-Path $Base "repo"
$Logs = Join-Path $Base "logs"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Repo "bot\.env"
$EntryFile = Join-Path $Base "entry_module.txt"

New-Item -ItemType Directory -Force $Logs | Out-Null

$ok = $true

function Check-Path {
    param(
        [string]$Label,
        [string]$Path
    )

    if (Test-Path $Path) {
        Write-Host "[OK] $Label $Path"
    } else {
        Write-Warning "[FEHLT] $Label $Path"
        $script:ok = $false
    }
}

Check-Path "Repo:" $Repo
Check-Path "Python:" $Python
Check-Path "Env:" $EnvFile

if (Test-Path $EntryFile) {
    $entry = (Get-Content $EntryFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    Write-Host "[OK] EntryModule: $entry"
} else {
    Write-Host "[INFO] Kein entry_module.txt. Default wird genutzt: bot.apps.discord_bot.main"
}

if (Test-Path $EnvFile) {
    $content = Get-Content $EnvFile -ErrorAction SilentlyContinue
    $tokenLine = $content | Where-Object { $_ -match "^\s*DISCORD_TOKEN\s*=" } | Select-Object -First 1

    if ([string]::IsNullOrWhiteSpace($tokenLine) -or $tokenLine.Trim() -eq "DISCORD_TOKEN=") {
        Write-Warning "[FEHLT] DISCORD_TOKEN ist nicht gesetzt."
        $ok = $false
    } else {
        Write-Host "[OK] DISCORD_TOKEN ist gesetzt. Wert wird nicht ausgegeben."
    }
}

if ($ok) {
    Write-Host "Preflight bestanden."
    exit 0
}

Write-Warning "Preflight fehlgeschlagen."
exit 1
