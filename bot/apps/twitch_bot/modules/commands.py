from __future__ import annotations

from twitchio.ext import commands

SOCIAL_LINKS = {
    "Twitch": "https://twitch.tv/hundekuchenlive",
    "Discord": "https://discord.gg/DEIN_INVITE_HIER",
    "Twitter / X": "https://x.com/hundekuchenlive",
    "TikTok": "https://www.tiktok.com/@hundekuchenlive",
    "Instagram": "https://www.instagram.com/hundekuchenlive",
}


class GeneralCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # !ping
    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        await ctx.send("Pong!")

    # !socials
    @commands.command(name="socials")
    async def socials(self, ctx: commands.Context):
        parts = [f"{name}: {url}" for name, url in SOCIAL_LINKS.items()]
        text = " | ".join(parts)
        await ctx.send(text)

    # !hilfe
    @commands.command(name="hilfe")
    async def hilfe(self, ctx: commands.Context):
        await ctx.send(
            "Verfügbare Commands: !ping, !socials, !hilfe (weitere folgen)."
        )


def prepare(bot: commands.Bot):
    # twitchio erwartet eine prepare-Funktion in Modul-Cogs
    bot.add_cog(GeneralCommands(bot))
