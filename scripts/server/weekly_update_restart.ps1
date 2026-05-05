$ErrorActionPreference = "Continue"

$Base = "C:\Bots\HundekuchenBot"
$Repo = Join-Path $Base "repo"
$Scripts = Join-Path $Base "scripts"
$Logs = Join-Path $Base "logs"
$Branch = "main"

New-Item -ItemType Directory -Force $Logs | Out-Null

Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Weekly Update gestartet."

& "$Scripts\stop_bot.ps1"

if (!(Test-Path $Repo)) {
    Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Repo fehlt: $Repo"
    exit 1
}

Set-Location $Repo

Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] git fetch..."
git fetch origin $Branch *> "$Logs\weekly-git-fetch.log"

if ($LASTEXITCODE -ne 0) {
    Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Git fetch fehlgeschlagen. Starte Bot mit vorhandenem Code."
    & "$Scripts\start_bot.ps1"
    exit 1
}

Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] git merge --ff-only origin/$Branch..."
git merge --ff-only "origin/$Branch" *> "$Logs\weekly-git-merge.log"

if ($LASTEXITCODE -ne 0) {
    Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Git merge fehlgeschlagen. Starte Bot mit vorhandenem Code."
    & "$Scripts\start_bot.ps1"
    exit 1
}

if (Test-Path "$Repo\requirements.txt") {
    Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Aktualisiere Python Dependencies..."
    & "$Repo\.venv\Scripts\pip.exe" install -r "$Repo\requirements.txt" *> "$Logs\weekly-pip-install.log"

    if ($LASTEXITCODE -ne 0) {
        Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] pip install fehlgeschlagen. Starte Bot trotzdem mit aktuellem Stand."
    }
}

Remove-Item "$Base\pending_update.flag" -Force -ErrorAction SilentlyContinue

& "$Scripts\start_bot.ps1"

Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] Weekly Update abgeschlossen."
