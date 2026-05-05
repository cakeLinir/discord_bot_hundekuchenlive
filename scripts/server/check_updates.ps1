$ErrorActionPreference = "Continue"

$Base = "C:\Bots\HundekuchenBot"
$Repo = Join-Path $Base "repo"
$Logs = Join-Path $Base "logs"
$PendingFlag = Join-Path $Base "pending_update.flag"
$Branch = "main"

New-Item -ItemType Directory -Force $Logs | Out-Null

if (!(Test-Path $Repo)) {
    Add-Content "$Logs\git-check.log" "[$(Get-Date)] Repo fehlt: $Repo"
    exit 1
}

Set-Location $Repo

Add-Content "$Logs\git-check.log" "[$(Get-Date)] Prüfe GitHub Updates..."

git fetch origin $Branch *> "$Logs\git-fetch-last.log"

if ($LASTEXITCODE -ne 0) {
    Add-Content "$Logs\git-check.log" "[$(Get-Date)] git fetch fehlgeschlagen. Siehe git-fetch-last.log"
    exit 1
}

$local = git rev-parse HEAD
$remote = git rev-parse "origin/$Branch"

if ($local -ne $remote) {
    "Update verfügbar: local=$local remote=$remote checked=$(Get-Date)" | Set-Content $PendingFlag
    Add-Content "$Logs\git-check.log" "[$(Get-Date)] Update verfügbar."
} else {
    Remove-Item $PendingFlag -Force -ErrorAction SilentlyContinue
    Add-Content "$Logs\git-check.log" "[$(Get-Date)] Kein Update verfügbar."
}
