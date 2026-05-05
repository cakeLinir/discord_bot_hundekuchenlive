$ErrorActionPreference = "Stop"

$Base = "C:\Bots\HundekuchenBot"
$EntryFile = Join-Path $Base "entry_module.txt"

"bot.apps.discord_bot.main" | Set-Content $EntryFile

Write-Host "EntryModule gesetzt: bot.apps.discord_bot.main"
Write-Host "Starte danach neu mit: C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1"
