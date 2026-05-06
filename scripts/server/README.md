# HundekuchenBot – Windows Server Scripts

Diese Scripts steuern den Discord-Bot auf dem Windows VPS.

Die Scripts im Repository sind die **Source of Truth**.  
Die produktive Kopie liegt auf dem Server unter:

```text
C:\Bots\HundekuchenBot\scripts
```

---

## 1. Zielstruktur auf dem VPS

```text
C:\Bots\HundekuchenBot
├─ repo
│  └─ bot
│     ├─ .env
│     ├─ .env.local                optional
│     └─ apps\discord_bot
├─ scripts
│  ├─ start_bot.ps1
│  ├─ stop_bot.ps1
│  ├─ check_updates.ps1
│  ├─ weekly_update_restart.ps1
│  ├─ preflight.ps1
│  └─ README.md
├─ logs
│  ├─ bot-control.log
│  ├─ bot.out.log
│  ├─ bot.err.log
│  ├─ git-check.log
│  └─ weekly-update.log
├─ bot.pid
├─ pending_update.flag
└─ entry_module.txt                optional
```

---

## 2. Repository-Pfad

Produktives Repo auf dem VPS:

```text
C:\Bots\HundekuchenBot\repo
```

Lokaler Entwicklungsstand:

```text
C:\Users\hunde\Desktop\discord_bot_hundekuchenlive
```

---

## 3. Scripts auf den VPS kopieren

Vom Repository-Root aus:

```powershell
Copy-Item .\scripts\server\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
Copy-Item .\scripts\server\README.md C:\Bots\HundekuchenBot\scripts\README.md -Force
```

Falls die Scripts direkt unter `scripts` liegen, entsprechend:

```powershell
Copy-Item .\scripts\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
Copy-Item .\scripts\README.md C:\Bots\HundekuchenBot\scripts\README.md -Force
```

---

## 4. Entry Module

Der Bot wird über Python-Modulstart ausgeführt:

```powershell
python -m bot.apps.discord_bot.main
```

Optional kann das Startmodul über diese Datei gesteuert werden:

```text
C:\Bots\HundekuchenBot\entry_module.txt
```

Standardinhalt:

```text
bot.apps.discord_bot.main
```

Nur verwenden, wenn das Zielmodul wirklich existiert.

Beispiele:

```text
bot.apps.discord_bot.main
bot.apps.discord_bot.main_discordpy
```

---

## 5. Script-Übersicht

### `preflight.ps1`

Prüft vor dem Start:

- Basisordner
- Repo-Pfad
- Python-venv
- `.env`
- Git-Repository
- Entry Module
- optionale Bridge-Dateien
- kritische Environment-Werte

Ausführen:

```powershell
C:\Bots\HundekuchenBot\scripts\preflight.ps1
```

---

### `start_bot.ps1`

Startet den Bot.

Aufgaben:

- Preflight ausführen
- PID-Datei prüfen
- Single-Instance-Lock prüfen
- Bot über `.venv\Scripts\python.exe -m <EntryModule>` starten
- `bot.pid` schreiben
- Logs nach `C:\Bots\HundekuchenBot\logs` schreiben

Ausführen:

```powershell
C:\Bots\HundekuchenBot\scripts\start_bot.ps1
```

---

### `stop_bot.ps1`

Stoppt den Bot.

Aufgaben:

- Prozess aus `bot.pid` stoppen
- Fallback: Bot-Prozesse anhand der CommandLine stoppen
- PID-Datei entfernen

Ausführen:

```powershell
C:\Bots\HundekuchenBot\scripts\stop_bot.ps1
```

---

### `check_updates.ps1`

Prüft, ob auf GitHub neue Commits vorhanden sind.

Aufgaben:

- `git fetch origin main`
- lokalen und Remote-Commit vergleichen
- bei Update `pending_update.flag` setzen
- keine Updates direkt einspielen

Ausführen:

```powershell
C:\Bots\HundekuchenBot\scripts\check_updates.ps1
```

Empfohlene Nutzung:

- täglich per Windows Aufgabenplanung

---

### `weekly_update_restart.ps1`

Führt den geplanten Weekly-Restart aus.

Aufgaben:

- GitHub aktualisieren
- Bot stoppen
- bei Update `git merge --ff-only origin/main`
- Dependencies aus `requirements.txt` aktualisieren
- Preflight ausführen
- Bot neu starten

Ausführen:

```powershell
C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1
```

Empfohlene Nutzung:

- wöchentlich per Windows Aufgabenplanung

---

## 6. Empfohlene `.env`-Werte

Datei:

```text
C:\Bots\HundekuchenBot\repo\bot\.env
```

Stabiler Grundbetrieb:

```env
DISCORD_HEARTBEAT_TIMEOUT=45
DISCORD_GUILD_READY_TIMEOUT=5
DISCORD_MAX_MESSAGES=500

BOT_INSTANCE_LOCK_PORT=49291

BOT_MINIMAL_INTENTS=false
BOT_ONLY_EXTENSIONS=
BOT_DISABLED_EXTENSIONS=

RETENTION_DAYS=30
RETENTION_CLEANUP_INTERVAL_HOURS=24

SEVENDTD_EVENT_MONITOR_ENABLED=false

JARVIS_ENABLED=false
DISCORD_BOT_API_ENABLED=false
```

Wichtig:

```env
DISCORD_HEARTBEAT_TIMEOUT=45
```

Dieser Wert war auf dem VPS stabil und verhindert, dass die Discord-Gateway-Latenz dauerhaft hängen bleibt.

---

## 7. Jarvis Bridge

Neue Bridge-Dateien:

```text
bot/apps/discord_bot/jarvis_client.py
bot/apps/discord_bot/cogs/jarvis_control.py
```

Jarvis ist standardmäßig deaktiviert:

```env
JARVIS_ENABLED=false
```

Aktivieren:

```env
JARVIS_ENABLED=true
```

Nur aktivieren, wenn:

- `jarvis_client.py` vorhanden ist
- Zielprojekt erreichbar ist
- benötigte Environment-Werte gesetzt sind

---

## 8. Lokale API Bridge

Die lokale API Bridge ist optional.

Standard:

```env
DISCORD_BOT_API_ENABLED=false
```

Aktivieren:

```env
DISCORD_BOT_API_ENABLED=true
DISCORD_BOT_API_HOST=127.0.0.1
DISCORD_BOT_API_PORT=8081
DISCORD_BOT_API_APP=bot.apps.discord_bot.api:app
```

Voraussetzungen:

```text
bot/apps/discord_bot/api.py
```

und Dependencies:

```text
fastapi
uvicorn
```

Wenn `api.py` fehlt, muss `DISCORD_BOT_API_ENABLED=false` bleiben.

---

## 9. Git-Workflow

Lokale Änderungen prüfen:

```powershell
cd C:\Users\hunde\Desktop\discord_bot_hundekuchenlive
git status --short
```

Änderungen committen:

```powershell
git add scripts\server
git add bot\apps\discord_bot
git add requirements.txt
git commit -m "Update server scripts and bot bridge files"
git push origin main
```

Auf dem VPS aktualisieren:

```powershell
cd C:\Bots\HundekuchenBot\repo
git fetch origin main
git merge --ff-only origin/main
```

Bei hartem Sync auf Remote-Stand:

```powershell
git reset --hard origin/main
```

Vor `reset --hard` sicherstellen, dass `.env`, Datenbank und Runtime-Dateien nicht versehentlich im Repo liegen.

---

## 10. Deployment nach Script-Änderungen

Auf dem VPS:

```powershell
cd C:\Bots\HundekuchenBot\repo

git fetch origin main
git merge --ff-only origin/main

Copy-Item .\scripts\server\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
Copy-Item .\scripts\server\README.md C:\Bots\HundekuchenBot\scripts\README.md -Force

C:\Bots\HundekuchenBot\scripts\preflight.ps1
C:\Bots\HundekuchenBot\scripts\stop_bot.ps1
C:\Bots\HundekuchenBot\scripts\start_bot.ps1
```

Falls die Scripts direkt unter `scripts` liegen:

```powershell
Copy-Item .\scripts\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
Copy-Item .\scripts\README.md C:\Bots\HundekuchenBot\scripts\README.md -Force
```

---

## 11. Logs prüfen

```powershell
Get-Content C:\Bots\HundekuchenBot\logs\bot-control.log -Tail 80
Get-Content C:\Bots\HundekuchenBot\logs\bot.out.log -Tail 120
Get-Content C:\Bots\HundekuchenBot\logs\bot.err.log -Tail 120
```

Wichtige erwartete Logwerte:

```text
heartbeat_timeout=45
api_enabled=False
jarvis_enabled=False
```

Wenn Jarvis/API bewusst aktiviert sind:

```text
api_enabled=True
jarvis_enabled=True
```

---

## 12. Windows Aufgabenplanung

### Täglicher Update-Check

Script:

```text
C:\Bots\HundekuchenBot\scripts\check_updates.ps1
```

Empfehlung:

```text
Täglich, z. B. 04:00 Uhr
```

### Wöchentlicher Update-Restart

Script:

```text
C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1
```

Empfehlung:

```text
Wöchentlich, z. B. Montag 04:30 Uhr
```

---

## 13. Fehlerbehebung

### Bot startet nicht

Prüfen:

```powershell
C:\Bots\HundekuchenBot\scripts\preflight.ps1
Get-Content C:\Bots\HundekuchenBot\logs\bot.err.log -Tail 120
```

### Bot läuft bereits

Prüfen:

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 49291 -State Listen -ErrorAction SilentlyContinue
Get-Content C:\Bots\HundekuchenBot\bot.pid -ErrorAction SilentlyContinue
```

### Gateway-Latenz extrem hoch

Prüfen:

```powershell
Get-Content C:\Bots\HundekuchenBot\logs\bot.err.log -Tail 120
```

Stabiler Wert:

```env
DISCORD_HEARTBEAT_TIMEOUT=45
```

### Cogs fehlen nach Git Pull

Auf lokalem PC prüfen:

```powershell
git ls-files bot/apps/discord_bot/cogs
git status --short
```

Auf VPS prüfen:

```powershell
cd C:\Bots\HundekuchenBot\repo
git fetch origin main
git ls-tree -r origin/main --name-only | findstr /i "bot/apps/discord_bot/cogs"
git reset --hard origin/main
```

### `api.py` fehlt

Wenn diese Datei fehlt:

```text
bot/apps/discord_bot/api.py
```

muss gesetzt sein:

```env
DISCORD_BOT_API_ENABLED=false
```

---

## 14. Sicherheitsregeln

Nicht ins Git committen:

```text
bot/.env
bot/.env.local
bot/data/*.sqlite3
bot/data/*.db
*.log
```

Ins Git committen:

```text
bot/apps/discord_bot/main.py
bot/apps/discord_bot/jarvis_client.py
bot/apps/discord_bot/cogs/*.py
scripts/server/*.ps1
scripts/server/README.md
requirements.txt
```

---

## 15. Kurzablauf für sichere Updates

```powershell
cd C:\Bots\HundekuchenBot\repo

git fetch origin main
git merge --ff-only origin/main

Copy-Item .\scripts\server\*.ps1 C:\Bots\HundekuchenBot\scripts -Force
Copy-Item .\scripts\server\README.md C:\Bots\HundekuchenBot\scripts\README.md -Force

C:\Bots\HundekuchenBot\scripts\preflight.ps1
C:\Bots\HundekuchenBot\scripts\stop_bot.ps1
C:\Bots\HundekuchenBot\scripts\start_bot.ps1
```