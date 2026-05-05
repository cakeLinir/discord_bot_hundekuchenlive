from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from pathlib import Path

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands, tasks

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()

DISCORD_BOT_DIR = THIS_FILE.parent
APPS_DIR = DISCORD_BOT_DIR.parent
BOT_ROOT = APPS_DIR.parent

ENV_PATH = BOT_ROOT / ".env"
ENV_LOCAL_PATH = BOT_ROOT / ".env.local"

for path in (DISCORD_BOT_DIR, BOT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# ---------------------------------------------------------------------------
# Imports (nach sys.path fix)
# ---------------------------------------------------------------------------

from core.db import Database  # noqa: E402
from jarvis_client import JarvisClient  # noqa: E402

# ---------------------------------------------------------------------------
# Config & Logging
# ---------------------------------------------------------------------------

load_dotenv(ENV_PATH, override=False)
load_dotenv(ENV_LOCAL_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

log = logging.getLogger("discord_bot")

# ---------------------------------------------------------------------------
# Env Helper (minimal)
# ---------------------------------------------------------------------------

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"} if value else default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        log.warning("Invalid int for %s=%r → using %s", name, value, default)
        return default


# ---------------------------------------------------------------------------
# Single Instance Lock
# ---------------------------------------------------------------------------

def acquire_single_instance_lock() -> socket.socket:
    port = env_int("BOT_INSTANCE_LOCK_PORT", 49291)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return sock
    except OSError:
        raise SystemExit(f"Bot läuft bereits (Lock-Port {port})")


# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

intents = nextcord.Intents.default()

if not env_bool("BOT_MINIMAL_INTENTS", False):
    intents.message_content = True
    intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

bot.start_time = time.time()
bot.version = os.getenv("BOT_VERSION", "dev")

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

# DB
db_path = Path(os.getenv("DB_PATH", "data/bot.sqlite3"))
if not db_path.is_absolute():
    db_path = (BOT_ROOT / db_path).resolve()

bot.db = Database(db_path)

# JARVIS
bot.jarvis = JarvisClient.from_env()

# zentrale Service Registry (für Cogs)
bot.services = {
    "db": bot.db,
    "jarvis": bot.jarvis,
}

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

INITIAL_EXTENSIONS = [
    "cogs.audit_log",
    "cogs.commands",
    "cogs.moderation",
    "cogs.embeds",
    "cogs.selfroles_slash",
    "cogs.sevendtd_monitor",
    "cogs.admin_slash",
    "cogs.satisfactory_panel",
    "cogs.sevendtd",
    "cogs.ls25_panel",
    "cogs.jarvis_control",
]

def load_extensions() -> None:
    for ext in INITIAL_EXTENSIONS:
        if ext == "cogs.sevendtd_monitor" and not env_bool("SEVENDTD_EVENT_MONITOR_ENABLED"):
            continue

        try:
            bot.load_extension(ext)
            log.info("Loaded extension: %s", ext)
        except Exception:
            log.exception("Failed to load extension: %s", ext)

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready() -> None:
    if not bot.user:
        return

    log.info("Logged in as %s (%s)", bot.user, bot.user.id)
    log.info("Version: %s", bot.version)

    # JARVIS Health Check
    if bot.jarvis.enabled:
        try:
            status, data = await bot.jarvis.health()
            log.info("JARVIS: %s %s", status, data)
        except Exception:
            log.exception("JARVIS health failed")


# ---------------------------------------------------------------------------
# DB Cleanup Task
# ---------------------------------------------------------------------------

@tasks.loop(hours=24)
async def cleanup_old_user_data() -> None:
    try:
        result = await bot.db.delete_old_user_data(
            retention_days=env_int("RETENTION_DAYS", 30),
        )
        log.info("DB cleanup: %s rows", result.affected_rows)
    except Exception:
        log.exception("DB cleanup failed")


@cleanup_old_user_data.before_loop
async def before_cleanup() -> None:
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    lock = acquire_single_instance_lock()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN fehlt")

    try:
        await bot.db.connect()
        await bot.db.setup_schema()

        log.info("DB ready: %s", bot.db.db_path)

        load_extensions()

        if not cleanup_old_user_data.is_running():
            cleanup_old_user_data.start()

        await bot.start(token)

    finally:
        if cleanup_old_user_data.is_running():
            cleanup_old_user_data.cancel()

        await bot.db.close()
        lock.close()

        log.info("Bot shutdown complete")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())