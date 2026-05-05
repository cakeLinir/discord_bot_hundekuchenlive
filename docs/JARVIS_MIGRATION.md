# JARVIS Integration / discord.py Migration Plan

This repository currently contains the legacy `nextcord` Discord bot. JARVIS will be
integrated in controlled stages instead of replacing the running bot in one risky step.

## Goals

- Keep the production bot deployable while migration work happens.
- Move from `nextcord` to `discord.py`.
- Keep existing functionality: moderation, embeds, selfroles, Satisfactory, 7DTD, LS25.
- Add a JARVIS bridge without giving JARVIS arbitrary command execution.
- Prepare the bot to become the Discord interface for JARVIS.

## Non-goals for the first patch

- Do not migrate every cog at once.
- Do not remove the existing `nextcord` entrypoint yet.
- Do not give JARVIS unrestricted shell/system access.
- Do not commit real `.env` values.

## Current legacy entrypoint

```text
bot.apps.discord_bot.main
```

This remains the default.

## New discord.py canary entrypoint

```text
bot.apps.discord_bot.main_discordpy
```

The canary loads only known discord.py-compatible extensions:

```text
discordpy_cogs.core
```

This gives us safe test commands:

```text
/jarvis_ping
/jarvis_status
/jarvis_migration_status
```

## Server-side switching

The improved server scripts read:

```text
C:\Bots\HundekuchenBot\entry_module.txt
```

Recommended values:

```text
bot.apps.discord_bot.main
bot.apps.discord_bot.main_discordpy
```

Use legacy mode for production until the migrated cogs are tested.

## Migration stages

### Stage 1: Safety and canary

- requirements: keep `nextcord` for legacy runtime and add `discord.py` for the canary
- add `main_discordpy.py`
- add minimal discord.py cogs
- add migration scan script
- add server script templates

### Stage 2: Public commands and audit logging

Migrate:

```text
cogs.commands -> discordpy_cogs.public_commands
cogs.audit_log -> discordpy_cogs.audit_log
```

Acceptance:

```text
/jarvis_ping works
/status equivalent works
command logging still writes to SQLite
```

### Stage 3: Admin and extension manager

Migrate:

```text
cogs.admin_slash -> discordpy_cogs.admin
```

Important discord.py changes:

```text
await bot.load_extension(...)
await bot.unload_extension(...)
await bot.reload_extension(...)
async def setup(bot)
await bot.add_cog(...)
```

### Stage 4: Embeds and selfroles

Migrate:

```text
cogs.embeds
cogs.selfroles_slash
```

Move hardcoded role IDs into `.env` or database configuration.

### Stage 5: Gameserver modules

Migrate:

```text
cogs.satisfactory_panel
cogs.sevendtd
cogs.sevendtd_monitor
cogs.ls25_panel
core.sevendtd_api
```

Keep the existing command allowlists. Do not replace them with arbitrary command
execution.

### Stage 6: JARVIS bridge

The bridge should accept only explicit capabilities, for example:

```json
{"type": "post_discord_status", "channel_id": "123", "message": "..."}
{"type": "refresh_gameserver_panel", "panel": "7dtd"}
```

Never accept:

```text
cmd
powershell
bash
subprocess
eval
exec
arbitrary URL fetches
unreviewed service restarts
```

## Local checks

```powershell
python scripts\migration\nextcord_to_discordpy_scan.py
python -m bot.apps.discord_bot.main_discordpy
```

## Server deployment checks

```powershell
C:\Bots\HundekuchenBot\scripts\preflight.ps1
C:\Bots\HundekuchenBot\scripts\switch_to_discordpy_canary.ps1
C:\Bots\HundekuchenBot\scripts\start_bot.ps1
```

## Rollback

```powershell
C:\Bots\HundekuchenBot\scripts\switch_to_legacy.ps1
C:\Bots\HundekuchenBot\scripts\weekly_update_restart.ps1
```

## Dependency rule

During the canary phase both libraries stay installed:

```text
nextcord
discord.py
```

Remove `nextcord` only after all cogs have been migrated and the legacy entrypoint is retired.
