# Bot V1.0.1 Patch: Datenbank, Retention, Modlogs

## Inhalt

Dieser Patch ergänzt deinen Bot um:

- SQLite-Datenbank über `aiosqlite`
- automatische Löschung gespeicherter Userdaten nach 30 Tagen
- Logging verwendeter Commands
- Logging von Warns, Mutes, Timeouts, Kicks, Bans und weiteren Moderationsaktionen
- Filter-Commands für Modlogs und Commandlogs
- manuelle Löschbefehle für Userdaten und einzelne Moderationslog-Einträge

## Neue Dateien

```text
core/db.py
apps/discord_bot/cogs/audit_log.py
apps/discord_bot/cogs/privacy_admin.py
apps/discord_bot/cogs/moderation_db_helpers.py
apps/discord_bot/main_v101_integration_example.py
data/migrations/001_v101_audit.sql
requirements-v1.0.1.txt
.env.v1.0.1.example
```

## Installation

```bash
pip install -r requirements-v1.0.1.txt
```

## .env ergänzen

Deine `.env` liegt laut Projektangabe unter:

```text
bot/apps/.env
```

Dort ergänzen:

```env
DB_PATH=../../data/bot_v101.sqlite3
RETENTION_DAYS=30
RETENTION_CLEANUP_INTERVAL_HOURS=24
```

## main.py Integration

In deiner bestehenden `apps/discord_bot/main.py` brauchst du:

```python
from core.db import Database
```

Nach dem Laden der `.env`:

```python
db_path = os.getenv("DB_PATH", "../../data/bot_v101.sqlite3")
bot.db = Database((APPS_DIR / db_path).resolve())
```

Vor `bot.start(...)`:

```python
await bot.db.connect()
await bot.db.setup_schema()
```

Extensions laden:

```python
bot.load_extension("apps.discord_bot.cogs.audit_log")
bot.load_extension("apps.discord_bot.cogs.privacy_admin")
```

Beim Shutdown:

```python
await bot.db.close()
```

## Moderationscommands anbinden

In bestehenden Warn/Mute/Timeout/Kick/Ban-Commands nach erfolgreicher Aktion ergänzen:

```python
await self.bot.db.log_moderation_action(
    guild_id=interaction.guild.id,
    target_user_id=user.id,
    moderator_user_id=interaction.user.id,
    action_type="warn",
    reason=reason,
)
```

Für Timeouts/Mutes zusätzlich:

```python
duration_seconds=duration_seconds,
expires_at=expires_at_timestamp,
```

Alternativ kannst du die fertigen Helper aus `moderation_db_helpers.py` nutzen.

## Neue Slash-Commands

```text
/userdata summary
/userdata delete
/modlog filter
/modlog delete
/commandlog filter
```

## Datenschutz-/Retention-Verhalten

`privacy_admin.py` startet eine Background-Task und ruft automatisch alle 24 Stunden:

```python
delete_old_user_data(retention_days=30)
```

Das löscht:

- command_logs
- moderation_actions
- user_notes
- alte deletion_audit-Einträge

## Wichtiger Hinweis

Da der direkte Inhalt deiner bestehenden `.py`-Dateien aus Drive nicht zuverlässig lesbar war, ist dieser Patch bewusst modular. Er ersetzt deine bestehenden Commands nicht blind, sondern ergänzt Datenbank- und Admin-Logik.