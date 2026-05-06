$ErrorActionPreference = "Continue"

$Base = $env:HUNDEKUCHEN_BOT_BASE
if ([string]::IsNullOrWhiteSpace($Base)) {
    $Base = "C:\Bots\HundekuchenBot"
}

$Repo = Join-Path $Base "repo"
$Logs = Join-Path $Base "logs"
$PendingFlag = Join-Path $Base "pending_update.flag"
$Branch = $env:HUNDEKUCHEN_BOT_BRANCH
if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = "main"
}

New-Item -ItemType Directory -Force $Logs | Out-Null

function Write-UpdateLog {
    param([string]$Message)
    Add-Content "$Logs\git-check.log" "[$(Get-Date)] $Message"
}

Write-UpdateLog "Prüfe GitHub Updates. Branch=$Branch"

if (!(Test-Path $Repo)) {
    Write-UpdateLog "Repo fehlt: $Repo"
    exit 1
}

git -C $Repo rev-parse --is-inside-work-tree *> $null

if ($LASTEXITCODE -ne 0) {
    Write-UpdateLog "Kein gültiges Git-Repository: $Repo"
    exit 1
}

git -C $Repo fetch origin $Branch *> "$Logs\git-fetch-last.log"

if ($LASTEXITCODE -ne 0) {
    Write-UpdateLog "git fetch fehlgeschlagen. Siehe git-fetch-last.log"
    exit 1
}

$local = (git -C $Repo rev-parse HEAD).Trim()
$remote = (git -C $Repo rev-parse "origin/$Branch").Trim()

if ([string]::IsNullOrWhiteSpace($local) -or [string]::IsNullOrWhiteSpace($remote)) {
    Write-UpdateLog "Konnte local/remote Hash nicht bestimmen. local=$local remote=$remote"
    exit 1
}

if ($local -ne $remote) {
    @"
Update verfügbar
checked=$(Get-Date)
branch=$Branch
local=$local
remote=$remote
"@ | Set-Content $PendingFlag -Encoding UTF8

    Write-UpdateLog "Update verfügbar. local=$local remote=$remote"
    exit 0
}

Remove-Item $PendingFlag -Force -ErrorAction SilentlyContinue
Write-UpdateLog "Kein Update verfügbar. HEAD=$local"
exit 0