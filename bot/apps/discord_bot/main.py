from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

THIS_FILE = Path(__file__).resolve()
DISCORD_BOT_DIR = THIS_FILE.parent       # bot/apps/discord_bot
APPS_DIR = DISCORD_BOT_DIR.parent        # bot/apps
BOT_ROOT = APPS_DIR.parent               # bot
ENV_PATH = BOT_ROOT / ".env"             # bot/.env
ENV_LOCAL_PATH = BOT_ROOT / ".env.local" # bot/.env.local

# Wichtig:
# - DISCORD_BOT_DIR für "cogs.*"
# - BOT_ROOT für "core.db"
for path in (DISCORD_BOT_DIR, BOT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

ENV_PATH = BOT_ROOT / ".env"
ENV_LOCAL_PATH = BOT_ROOT / ".env.local"


# ---------------------------------------------------------------------------
# Grundkonfiguration
# ---------------------------------------------------------------------------

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


async def main() -> None:
    runtime = get_runtime()

    if runtime == "legacy":
        from . import legacy_nextcord as runtime_module
    elif runtime == "discordpy":
        from . import discordpy_canary as runtime_module
    else:
        raise SystemExit(f"Unsupported runtime: {runtime}")

    log.info("Starting HundekuchenBot runtime=%s module=%s", runtime, runtime_module.__name__)

    await runtime_module.main()


if __name__ == "__main__":
    asyncio.run(main())