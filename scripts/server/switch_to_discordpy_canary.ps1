$ErrorActionPreference = "Stop"

$Base = "C:\Bots\HundekuchenBot"
$EntryFile = Join-Path $Base "entry_module.txt"

"bot.apps.discord_bot.main_discordpy" | Set-Content $EntryFile

Write-Host "EntryModule gesetzt: bot.apps.discord_bot.main_discordpy"
Write-Host "Starte danach neu mit: C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1"
