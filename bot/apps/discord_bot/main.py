from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import socket
from pathlib import Path

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands, tasks

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()

# apps/discord_bot/main.py
DISCORD_BOT_DIR = THIS_FILE.parent  # bot/apps/discord_bot
APPS_DIR = DISCORD_BOT_DIR.parent  # bot/apps
BOT_ROOT = APPS_DIR.parent  # bot
ENV_PATH = BOT_ROOT / ".env"  # bot/.env

# Wichtig:
# - DISCORD_BOT_DIR für "cogs.*"
# - BOT_ROOT für "core.db"
for path in (DISCORD_BOT_DIR, BOT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from core.db import Database  # noqa: E402

# ---------------------------------------------------------------------------
# Grundkonfiguration
# ---------------------------------------------------------------------------

load_dotenv(ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

log = logging.getLogger("discord_bot")
def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}

# ---------------------------------------------------------------------------
# Bot-Setup
# ---------------------------------------------------------------------------

intents = nextcord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

bot.start_time = time.time()

# ---------------------------------------------------------------------------
# Datenbank V1.0.1
# ---------------------------------------------------------------------------

db_path_raw = os.getenv("DB_PATH", "data/bot_v101.sqlite3")
db_path = Path(db_path_raw)

if not db_path.is_absolute():
    db_path = (BOT_ROOT / db_path).resolve()

bot.db = Database(db_path)

# ---------------------------------------------------------------------------
# Cogs
# ---------------------------------------------------------------------------

INITIAL_EXTENSIONS = [
    # DB-/Audit-Logging zuerst laden
    "cogs.audit_log",

    # Bestehende Cogs
    "cogs.commands",
    "cogs.moderation",
    "cogs.embeds",
    "cogs.selfroles_slash",
    "cogs.sevendtd_monitor",

    # Admin-Slash mit den neuen DB-Commands
    "cogs.admin_slash",
    
    # Gameserver-Panels
    "cogs.satisfactory_panel",
    "cogs.sevendtd",
    "cogs.ls25_panel",
]

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@bot.event
async def on_ready():
    if bot.user is None:
        log.warning("Bot is ready, but bot.user is None.")
        return

    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    log.info("Bot is ready. Version: V1.0.1")


# ---------------------------------------------------------------------------
# Automatische DB-Löschung nach X Tagen
# ---------------------------------------------------------------------------


@tasks.loop(hours=24)
async def cleanup_old_user_data():
    retention_days = int(os.getenv("RETENTION_DAYS", "30"))

    try:
        result = await bot.db.delete_old_user_data(
            retention_days=retention_days,
        )

        log.info(
            "DB cleanup completed. retention_days=%s affected_rows=%s "
            "command_logs=%s moderation_actions=%s user_notes=%s deletion_audit=%s",
            retention_days,
            result.affected_rows,
            result.command_logs,
            result.moderation_actions,
            result.user_notes,
            result.deletion_audit,
        )

    except Exception:
        log.exception("DB cleanup failed.")


@cleanup_old_user_data.before_loop
async def before_cleanup_old_user_data():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Cogs laden
# ---------------------------------------------------------------------------


def load_extensions():
    for ext in INITIAL_EXTENSIONS:
        if ext == "cogs.sevendtd_monitor" and not env_bool("SEVENDTD_EVENT_MONITOR_ENABLED", False):
            log.info("Skipped extension %s because SEVENDTD_EVENT_MONITOR_ENABLED=false", ext)
            print(f"Skipped extension: {ext}")
            continue

        try:
            bot.load_extension(ext)
        except Exception as exc:
            log.exception("Failed to load extension %s: %s", ext, exc)
        else:
            log.info("Loaded extension: %s", ext)
            print(f"Loaded extension: {ext}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def acquire_single_instance_lock() -> socket.socket:
    """
    Verhindert, dass der Bot zweimal auf demselben System läuft.

    Nutzt einen lokalen TCP-Port als Prozess-Lock.
    Wenn der Port bereits belegt ist, läuft schon eine Bot-Instanz.
    """
    lock_port = int(os.getenv("BOT_INSTANCE_LOCK_PORT", "49291"))

    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

    try:
        lock_socket.bind(("127.0.0.1", lock_port))
        lock_socket.listen(1)
        return lock_socket

    except OSError:
        raise SystemExit(
            f"Bot läuft bereits oder Lock-Port ist belegt: 127.0.0.1:{lock_port}"
        )

async def main():
    instance_lock = acquire_single_instance_lock()
    log.info("Asyncio event loop: %s", type(asyncio.get_running_loop()).__name__)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN is not set in %s", ENV_PATH)
        instance_lock.close()
        raise SystemExit("Missing DISCORD_TOKEN in bot/.env.")

    try:
        await bot.db.connect()
        await bot.db.setup_schema()
        log.info("Database initialized at: %s", bot.db.db_path)

        load_extensions()

        cleanup_interval_hours = int(
            os.getenv("RETENTION_CLEANUP_INTERVAL_HOURS", "24")
        )
        cleanup_old_user_data.change_interval(hours=cleanup_interval_hours)

        if not cleanup_old_user_data.is_running():
            cleanup_old_user_data.start()

        await bot.start(token)

    finally:
        if cleanup_old_user_data.is_running():
            cleanup_old_user_data.cancel()

        await bot.db.close()
        instance_lock.close()
        log.info("Database connection closed.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
