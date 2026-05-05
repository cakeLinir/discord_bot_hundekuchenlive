# Windows Server Scripts

These scripts are intended for the server folder:

```text
C:\Bots\HundekuchenBot\scripts
```

The repository copy is the source of truth. Copy them to the server with:

```powershell
Copy-Item .\scripts\server\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
```

The scripts use:

```text
C:\Bots\HundekuchenBot\repo
C:\Bots\HundekuchenBot\logs
C:\Bots\HundekuchenBot\bot.pid
C:\Bots\HundekuchenBot\pending_update.flag
C:\Bots\HundekuchenBot\entry_module.txt
```

`entry_module.txt` decides which Python module starts:

```text
bot.apps.discord_bot.main
bot.apps.discord_bot.main_discordpy
```
