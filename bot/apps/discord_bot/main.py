from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands, tasks

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

THIS_FILE = Path(__file__).resolve()

DISCORD_BOT_DIR = THIS_FILE.parent          # bot/apps/discord_bot
APPS_DIR = DISCORD_BOT_DIR.parent           # bot/apps
BOT_ROOT = APPS_DIR.parent                  # bot
PROJECT_ROOT = BOT_ROOT.parent              # repo root

ENV_PATH = BOT_ROOT / ".env"                # bot/.env
ENV_LOCAL_PATH = BOT_ROOT / ".env.local"    # bot/.env.local optional

for path in (DISCORD_BOT_DIR, BOT_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# ---------------------------------------------------------------------------
# Imports nach sys.path-Fix
# ---------------------------------------------------------------------------

from core.db import Database  # noqa: E402

try:
    from jarvis_client import JarvisClient  # noqa: E402
except Exception:  # Import darf den Discord-Bot nicht töten
    JarvisClient = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Config & Logging
# ---------------------------------------------------------------------------

# Wichtig:
# override=True verhindert, dass alte Windows-Environment-Werte deine .env blockieren.
load_dotenv(ENV_PATH, override=True)

# .env.local darf produktive/local Overrides setzen.
if ENV_LOCAL_PATH.exists():
    load_dotenv(ENV_LOCAL_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

log = logging.getLogger("discord_bot")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default

    return value in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        log.warning("Invalid int for %s=%r -> using %s", name, value, default)
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return float(value)
    except ValueError:
        log.warning("Invalid float for %s=%r -> using %s", name, value, default)
        return default


def env_csv_set(name: str) -> set[str]:
    value = os.getenv(name, "").strip()

    if not value:
        return set()

    return {item.strip() for item in value.split(",") if item.strip()}


# ---------------------------------------------------------------------------
# Fallback Jarvis Client
# ---------------------------------------------------------------------------

class DisabledJarvisClient:
    enabled = False

    def __init__(self, reason: str = "disabled") -> None:
        self.reason = reason

    @classmethod
    def from_env(cls) -> "DisabledJarvisClient":
        return cls("disabled")

    async def health(self) -> tuple[int, dict[str, Any]]:
        return 503, {"enabled": False, "reason": self.reason}


def build_jarvis_client() -> Any:
    if not env_bool("JARVIS_ENABLED", False):
        return DisabledJarvisClient("JARVIS_ENABLED=false")

    if JarvisClient is None:
        log.warning("JarvisClient import failed or is unavailable. JARVIS disabled.")
        return DisabledJarvisClient("JarvisClient import failed")

    try:
        return JarvisClient.from_env()
    except Exception:
        log.exception("JarvisClient initialization failed. JARVIS disabled.")
        return DisabledJarvisClient("JarvisClient initialization failed")


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

    except OSError as exc:
        sock.close()
        raise SystemExit(
            f"Bot läuft bereits oder Lock-Port ist belegt: 127.0.0.1:{port}"
        ) from exc


# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

intents = nextcord.Intents.default()

# Diagnose-/Minimalmodus:
# BOT_MINIMAL_INTENTS=true -> kein members/message_content.
if not env_bool("BOT_MINIMAL_INTENTS", False):
    intents.message_content = True
    intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    heartbeat_timeout=env_float("DISCORD_HEARTBEAT_TIMEOUT", 45.0),
    guild_ready_timeout=env_float("DISCORD_GUILD_READY_TIMEOUT", 5.0),
    max_messages=env_int("DISCORD_MAX_MESSAGES", 500),
)

bot.start_time = time.time()
bot.version = os.getenv("BOT_VERSION", "V1.0.1").strip() or "V1.0.1"
bot.event_loop_last_lag_ms = 0
bot.jarvis_health_checked = False


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

db_path = Path(os.getenv("DB_PATH", "data/bot_v101.sqlite3").strip())

if not db_path.is_absolute():
    db_path = (BOT_ROOT / db_path).resolve()

bot.db = Database(db_path)

bot.jarvis = build_jarvis_client()

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

    # Nur laden, wenn SEVENDTD_EVENT_MONITOR_ENABLED=true
    "cogs.sevendtd_monitor",

    "cogs.admin_slash",
    "cogs.satisfactory_panel",
    "cogs.sevendtd",
    "cogs.ls25_panel",

    # JARVIS Bridge
    "cogs.jarvis_control",
]


def should_load_extension(ext: str) -> bool:
    only_extensions = env_csv_set("BOT_ONLY_EXTENSIONS")
    disabled_extensions = env_csv_set("BOT_DISABLED_EXTENSIONS")

    if only_extensions and ext not in only_extensions:
        log.info("Skipped extension %s because BOT_ONLY_EXTENSIONS is active", ext)
        return False

    if ext in disabled_extensions:
        log.info("Skipped extension %s because it is listed in BOT_DISABLED_EXTENSIONS", ext)
        return False

    if ext == "cogs.sevendtd_monitor" and not env_bool("SEVENDTD_EVENT_MONITOR_ENABLED", False):
        log.info("Skipped extension %s because SEVENDTD_EVENT_MONITOR_ENABLED=false", ext)
        return False

    if ext == "cogs.jarvis_control" and not getattr(bot.jarvis, "enabled", False):
        log.info("Skipped extension %s because JARVIS is disabled", ext)
        return False

    return True


def load_extensions() -> None:
    only_extensions = env_csv_set("BOT_ONLY_EXTENSIONS")
    disabled_extensions = env_csv_set("BOT_DISABLED_EXTENSIONS")

    if only_extensions:
        log.warning("BOT_ONLY_EXTENSIONS active: %s", ", ".join(sorted(only_extensions)))

    if disabled_extensions:
        log.warning("BOT_DISABLED_EXTENSIONS active: %s", ", ".join(sorted(disabled_extensions)))

    for ext in INITIAL_EXTENSIONS:
        if not should_load_extension(ext):
            print(f"Skipped extension: {ext}")
            continue

        try:
            bot.load_extension(ext)

        except Exception:
            log.exception("Failed to load extension: %s", ext)

        else:
            log.info("Loaded extension: %s", ext)
            print(f"Loaded extension: {ext}")


# ---------------------------------------------------------------------------
# Optional API Bridge
# ---------------------------------------------------------------------------

async def start_api() -> None:
    """
    Startet optional eine lokale Bridge-API.

    Aktivierung:
        DISCORD_BOT_API_ENABLED=true

    Benötigte Pakete:
        fastapi
        uvicorn
    """
    if not env_bool("DISCORD_BOT_API_ENABLED", False):
        log.info("Discord bot API bridge disabled.")
        return

    try:
        import uvicorn
    except Exception:
        log.exception("DISCORD_BOT_API_ENABLED=true, but uvicorn is not installed.")
        return

    host = os.getenv("DISCORD_BOT_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = env_int("DISCORD_BOT_API_PORT", 8081)
    app_path = os.getenv("DISCORD_BOT_API_APP", "bot.apps.discord_bot.api:app").strip()

    config = uvicorn.Config(
        app_path,
        host=host,
        port=port,
        log_level=os.getenv("DISCORD_BOT_API_LOG_LEVEL", "info").strip() or "info",
    )

    server = uvicorn.Server(config)

    log.info("Starting Discord bot API bridge on %s:%s app=%s", host, port, app_path)

    try:
        await server.serve()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Discord bot API bridge crashed.")


def log_task_result(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Background task failed: %s", task.get_name())


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready() -> None:
    if bot.user is None:
        log.warning("Bot is ready, but bot.user is None.")
        return

    log.info("Logged in as %s (%s)", bot.user, bot.user.id)
    log.info("Version: %s", bot.version)

    log.info(
        "Runtime config: BOT_MINIMAL_INTENTS=%s BOT_ONLY_EXTENSIONS=%r "
        "BOT_DISABLED_EXTENSIONS=%r heartbeat_timeout=%s guild_ready_timeout=%s "
        "api_enabled=%s jarvis_enabled=%s",
        env_bool("BOT_MINIMAL_INTENTS", False),
        os.getenv("BOT_ONLY_EXTENSIONS", "").strip(),
        os.getenv("BOT_DISABLED_EXTENSIONS", "").strip(),
        os.getenv("DISCORD_HEARTBEAT_TIMEOUT", "45").strip(),
        os.getenv("DISCORD_GUILD_READY_TIMEOUT", "5").strip(),
        env_bool("DISCORD_BOT_API_ENABLED", False),
        getattr(bot.jarvis, "enabled", False),
    )

    if getattr(bot.jarvis, "enabled", False) and not bot.jarvis_health_checked:
        bot.jarvis_health_checked = True

        try:
            status, data = await bot.jarvis.health()
            log.info("JARVIS health: %s %s", status, data)

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

        log.info(
            "DB cleanup completed. affected_rows=%s command_logs=%s "
            "moderation_actions=%s user_notes=%s deletion_audit=%s",
            result.affected_rows,
            result.command_logs,
            result.moderation_actions,
            result.user_notes,
            result.deletion_audit,
        )

    except Exception:
        log.exception("DB cleanup failed")


@cleanup_old_user_data.before_loop
async def before_cleanup() -> None:
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Eventloop Lag Watchdog
# ---------------------------------------------------------------------------

async def event_loop_lag_watchdog() -> None:
    interval = env_float("EVENT_LOOP_LAG_INTERVAL_SECONDS", 10.0)
    warn_after = env_float("EVENT_LOOP_LAG_WARN_SECONDS", 2.0)

    loop = asyncio.get_running_loop()
    expected = loop.time() + interval

    while not bot.is_closed():
        await asyncio.sleep(interval)

        now = loop.time()
        lag = max(0.0, now - expected)

        bot.event_loop_last_lag_ms = int(lag * 1000)

        if lag >= warn_after:
            log.warning("Event loop lag detected: %.3fs", lag)

        expected = now + interval


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()

    if not token:
        raise SystemExit(f"DISCORD_TOKEN fehlt in {ENV_PATH}")

    lock: socket.socket | None = None
    api_task: asyncio.Task[Any] | None = None
    lag_watchdog_task: asyncio.Task[Any] | None = None

    try:
        lock = acquire_single_instance_lock()

        log.info("ENV path: %s", ENV_PATH)
        log.info("ENV local path: %s exists=%s", ENV_LOCAL_PATH, ENV_LOCAL_PATH.exists())
        log.info("Asyncio event loop: %s", type(asyncio.get_running_loop()).__name__)

        await bot.db.connect()
        await bot.db.setup_schema()

        log.info("DB ready: %s", bot.db.db_path)

        load_extensions()

        cleanup_interval_hours = env_int("RETENTION_CLEANUP_INTERVAL_HOURS", 24)
        cleanup_old_user_data.change_interval(hours=cleanup_interval_hours)

        if not cleanup_old_user_data.is_running():
            cleanup_old_user_data.start()

        lag_watchdog_task = asyncio.create_task(
            event_loop_lag_watchdog(),
            name="event_loop_lag_watchdog",
        )

        api_task = asyncio.create_task(
            start_api(),
            name="discord_bot_api",
        )
        api_task.add_done_callback(log_task_result)

        await bot.start(token)

    finally:
        if cleanup_old_user_data.is_running():
            cleanup_old_user_data.cancel()

        if api_task is not None:
            api_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await api_task

        if lag_watchdog_task is not None:
            lag_watchdog_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await lag_watchdog_task

        with contextlib.suppress(Exception):
            await bot.db.close()

        if lock is not None:
            lock.close()

        log.info("Bot shutdown complete")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())