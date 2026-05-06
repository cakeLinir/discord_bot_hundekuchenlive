$ErrorActionPreference = "Continue"

$Base = $env:HUNDEKUCHEN_BOT_BASE
if ([string]::IsNullOrWhiteSpace($Base)) {
    $Base = "C:\Bots\HundekuchenBot"
}

$Repo = Join-Path $Base "repo"
$Scripts = Join-Path $Base "scripts"
$Logs = Join-Path $Base "logs"
$PendingFlag = Join-Path $Base "pending_update.flag"
$Branch = $env:HUNDEKUCHEN_BOT_BRANCH
if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = "main"
}

New-Item -ItemType Directory -Force $Logs | Out-Null

function Write-WeeklyLog {
    param([string]$Message)
    Add-Content "$Logs\weekly-update.log" "[$(Get-Date)] $Message"
}

function Start-BotSafe {
    & "$Scripts\start_bot.ps1"
    if ($LASTEXITCODE -ne 0) {
        Write-WeeklyLog "Bot-Start fehlgeschlagen. ExitCode=$LASTEXITCODE"
        exit $LASTEXITCODE
    }
}

Write-WeeklyLog "Weekly Restart/Update gestartet. Branch=$Branch"

if (!(Test-Path $Repo)) {
    Write-WeeklyLog "Repo fehlt: $Repo"
    exit 1
}

git -C $Repo rev-parse --is-inside-work-tree *> $null

if ($LASTEXITCODE -ne 0) {
    Write-WeeklyLog "Kein gültiges Git-Repository: $Repo"
    exit 1
}

Write-WeeklyLog "git fetch..."
git -C $Repo fetch origin $Branch *> "$Logs\weekly-git-fetch.log"

$fetchOk = $LASTEXITCODE -eq 0

$updateAvailable = $false

if ($fetchOk) {
    $local = (git -C $Repo rev-parse HEAD).Trim()
    $remote = (git -C $Repo rev-parse "origin/$Branch").Trim()

    if ($local -ne $remote) {
        $updateAvailable = $true
        Write-WeeklyLog "Update verfügbar. local=$local remote=$remote"
    } else {
        Write-WeeklyLog "Kein Update verfügbar. HEAD=$local"
    }
} else {
    Write-WeeklyLog "git fetch fehlgeschlagen. Weekly Restart läuft ohne Update weiter."
}

# Weekly Restart passiert immer
& "$Scripts\stop_bot.ps1"

if ($updateAvailable) {
    $dirty = git -C $Repo status --porcelain

    if ($dirty) {
        Write-WeeklyLog "Repo hat lokale Änderungen. Merge wird nicht ausgeführt."
        Write-WeeklyLog "Lokale Änderungen:"
        $dirty | ForEach-Object { Write-WeeklyLog $_ }

        Start-BotSafe
        exit 1
    }

    Write-WeeklyLog "git merge --ff-only origin/$Branch..."
    git -C $Repo merge --ff-only "origin/$Branch" *> "$Logs\weekly-git-merge.log"

    if ($LASTEXITCODE -ne 0) {
        Write-WeeklyLog "Git merge fehlgeschlagen. Starte Bot mit vorhandenem Code."
        Start-BotSafe
        exit 1
    }

    Remove-Item $PendingFlag -Force -ErrorAction SilentlyContinue

    if (Test-Path "$Repo\requirements.txt") {
        $Python = Join-Path $Repo ".venv\Scripts\python.exe"

        if (Test-Path $Python) {
            Write-WeeklyLog "Aktualisiere Python Dependencies..."
            & $Python -m pip install -r "$Repo\requirements.txt" *> "$Logs\weekly-pip-install.log"

            if ($LASTEXITCODE -ne 0) {
                Write-WeeklyLog "pip install fehlgeschlagen. Starte Bot trotzdem."
            }
        } else {
            Write-WeeklyLog "Python venv fehlt. Dependencies werden nicht aktualisiert."
        }
    }
}

$Preflight = Join-Path $Scripts "preflight.ps1"

if (Test-Path $Preflight) {
    Write-WeeklyLog "Preflight..."
    & $Preflight *> "$Logs\weekly-preflight.log"

    if ($LASTEXITCODE -ne 0) {
        Write-WeeklyLog "Preflight fehlgeschlagen. Bot wird nicht gestartet."
        exit 1
    }
}

Start-BotSafe

Write-WeeklyLog "Weekly Restart/Update abgeschlossen."
exit 0