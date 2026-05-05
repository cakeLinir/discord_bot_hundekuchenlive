from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Final

import discord
from discord.ext import commands
from dotenv import load_dotenv

THIS_FILE = Path(__file__).resolve()
DISCORD_BOT_DIR = THIS_FILE.parent       # bot/apps/discord_bot
APPS_DIR = DISCORD_BOT_DIR.parent        # bot/apps
BOT_ROOT = APPS_DIR.parent               # bot
ENV_PATH = BOT_ROOT / ".env"

for path in (DISCORD_BOT_DIR, BOT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from jarvis_client import JarvisClient  # noqa: E402

load_dotenv(ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

log = logging.getLogger("discord_bot.discordpy")


DEFAULT_EXTENSIONS: Final[list[str]] = [
    "discordpy_cogs.core",
]


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
        log.warning("Invalid integer for %s=%r. Using default=%s", name, value, default)
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        log.warning("Invalid float for %s=%r. Using default=%s", name, value, default)
        return default


def env_csv_set(name: str) -> set[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def acquire_single_instance_lock() -> socket.socket:
    lock_port = env_int("BOT_INSTANCE_LOCK_PORT", 49291)

    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

    try:
        lock_socket.bind(("127.0.0.1", lock_port))
        lock_socket.listen(1)
        return lock_socket
    except OSError as exc:
        raise SystemExit(
            f"Bot läuft bereits oder Lock-Port ist belegt: 127.0.0.1:{lock_port}"
        ) from exc


class HundekuchenDiscordPyBot(commands.Bot):
    """discord.py canary bot for the JARVIS migration.

    This entrypoint intentionally loads only discord.py-compatible extensions.
    Existing nextcord cogs remain untouched until they are migrated one by one.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()

        if not env_bool("BOT_MINIMAL_INTENTS", False):
            intents.message_content = True
            intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            heartbeat_timeout=env_float("DISCORD_HEARTBEAT_TIMEOUT", 45.0),
            guild_ready_timeout=env_float("DISCORD_GUILD_READY_TIMEOUT", 5.0),
            max_messages=env_int("DISCORD_MAX_MESSAGES", 500),
        )

        self.start_time = time.time()
        self.version = "JARVIS-migration-canary"
        self.event_loop_last_lag_ms = 0
        self.jarvis_client = JarvisClient.from_env()

    async def setup_hook(self) -> None:
        await self._load_configured_extensions()
        await self._sync_application_commands()

    async def _load_configured_extensions(self) -> None:
        only_extensions = env_csv_set("BOT_ONLY_EXTENSIONS")
        disabled_extensions = env_csv_set("BOT_DISABLED_EXTENSIONS")

        for ext in DEFAULT_EXTENSIONS:
            if only_extensions and ext not in only_extensions:
                log.info("Skipped extension %s because BOT_ONLY_EXTENSIONS is active", ext)
                continue

            if ext in disabled_extensions:
                log.info("Skipped extension %s because BOT_DISABLED_EXTENSIONS is active", ext)
                continue

            try:
                await self.load_extension(ext)
            except Exception:
                log.exception("Failed to load extension: %s", ext)
            else:
                log.info("Loaded extension: %s", ext)

    async def _sync_application_commands(self) -> None:
        guild_id = os.getenv("DISCORDPY_SYNC_GUILD_ID", "").strip()

        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %s application commands to guild %s", len(synced), guild_id)
            return

        synced = await self.tree.sync()
        log.info("Synced %s global application commands", len(synced))


async def event_loop_lag_watchdog(bot: HundekuchenDiscordPyBot) -> None:
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


async def main() -> None:
    instance_lock = acquire_single_instance_lock()
    lag_watchdog_task: asyncio.Task[None] | None = None

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        instance_lock.close()
        raise SystemExit(f"Missing DISCORD_TOKEN in {ENV_PATH}")

    bot = HundekuchenDiscordPyBot()

    try:
        async with bot:
            lag_watchdog_task = asyncio.create_task(event_loop_lag_watchdog(bot))
            await bot.start(token)
    finally:
        if lag_watchdog_task is not None:
            lag_watchdog_task.cancel()
            try:
                await lag_watchdog_task
            except asyncio.CancelledError:
                pass

        instance_lock.close()


if __name__ == "__main__":
    asyncio.run(main())
