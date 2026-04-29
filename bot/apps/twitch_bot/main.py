from __future__ import annotations

import logging
import os
from pathlib import Path

from twitchio.ext import commands
from dotenv import load_dotenv

# .env laden
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("twitch_bot")


class HundekuchenTwitchBot(commands.Bot):
    def __init__(self):
        nick = os.getenv("TWITCH_BOT_NICK")
        token = os.getenv("TWITCH_BOT_TOKEN")
        initial_channels = [os.getenv("TWITCH_CHANNEL", "")]

        if not nick or not token or not initial_channels[0]:
            raise SystemExit("TWITCH_BOT_NICK / TWITCH_BOT_TOKEN / TWITCH_CHANNEL fehlen in .env")

        super().__init__(
            irc_token=token,
            nick=nick,
            prefix="!",
            initial_channels=initial_channels,
        )

        log.info(
            "Twitch-Bot init: nick=%s channels=%s",
            nick,
            initial_channels,
        )

        # Cogs/Module laden
        self.load_module("bot.apps.twitch_bot.modules.commands")
        # Platzhalter für später:
        # self.load_module("bot.apps.twitch_bot.modules.automod")
        # self.load_module("bot.apps.twitch_bot.modules.ai_chat")

    async def event_ready(self):
        log.info(f"Twitch-Bot verbunden als {self.nick}")


def main():
    bot = HundekuchenTwitchBot()
    bot.run()


if __name__ == "__main__":
    main()
