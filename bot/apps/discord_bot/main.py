from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

THIS_FILE = Path(__file__).resolve()

DISCORD_BOT_DIR = THIS_FILE.parent       # bot/apps/discord_bot
APPS_DIR = DISCORD_BOT_DIR.parent        # bot/apps
BOT_ROOT = APPS_DIR.parent               # bot
REPO_ROOT = BOT_ROOT.parent              # repo

ENV_PATH = BOT_ROOT / ".env"
ENV_LOCAL_PATH = BOT_ROOT / ".env.local"

# Wichtig für direkten Start per Datei:
# python bot/apps/discord_bot/main.py
for path in (REPO_ROOT, BOT_ROOT, DISCORD_BOT_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

load_dotenv(ENV_PATH, override=False)
load_dotenv(ENV_LOCAL_PATH, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)

log = logging.getLogger("discord_bot.entrypoint")


def get_runtime() -> str:
    runtime = os.getenv("BOT_RUNTIME", "legacy").strip().lower()

    aliases = {
        "legacy": "legacy",
        "nextcord": "legacy",
        "old": "legacy",
        "discordpy": "discordpy",
        "discord.py": "discordpy",
        "canary": "discordpy",
        "new": "discordpy",
    }

    if runtime not in aliases:
        allowed = ", ".join(sorted(aliases))
        raise SystemExit(f"Invalid BOT_RUNTIME={runtime!r}. Allowed values: {allowed}")

    return aliases[runtime]


def import_runtime_module(runtime: str):
    if runtime == "legacy":
        return importlib.import_module("bot.apps.discord_bot.legacy_nextcord")

    if runtime == "discordpy":
        return importlib.import_module("bot.apps.discord_bot.discordpy_canary")

    raise SystemExit(f"Unsupported runtime: {runtime}")


async def main() -> None:
    runtime = get_runtime()
    runtime_module = import_runtime_module(runtime)

    log.info(
        "Starting HundekuchenBot runtime=%s module=%s",
        runtime,
        runtime_module.__name__,
    )

    await runtime_module.main()


if __name__ == "__main__":
    asyncio.run(main())