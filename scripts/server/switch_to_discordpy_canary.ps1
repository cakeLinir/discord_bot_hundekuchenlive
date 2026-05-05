$ErrorActionPreference = "Stop"

$Base = "C:\Bots\HundekuchenBot"
$RuntimeFile = Join-Path $Base "runtime_mode.txt"
$EntryFile = Join-Path $Base "entry_module.txt"

"discordpy" | Set-Content $RuntimeFile
"bot.apps.discord_bot.main" | Set-Content $EntryFile

Write-Host "BOT_RUNTIME gesetzt: discordpy"
Write-Host "EntryModule gesetzt: bot.apps.discord_bot.main"
Write-Host "Starte danach neu mit: C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1"