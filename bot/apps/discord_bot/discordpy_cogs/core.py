from __future__ import annotations

import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands


def _format_uptime(start_time: float) -> str:
    uptime_seconds = int(time.time() - start_time)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


class MigrationCore(commands.Cog):
    """Small discord.py command set used to verify the migration safely."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="jarvis_ping",
        description="Migrationstest: prüft die Discord-Gateway-Latenz.",
    )
    async def jarvis_ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong. Gateway-Latenz: `{latency_ms} ms`",
            ephemeral=True,
        )

    @app_commands.command(
        name="jarvis_status",
        description="Migrationstest: zeigt Bot- und JARVIS-Status.",
    )
    async def jarvis_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        start_time = float(getattr(self.bot, "start_time", time.time()))
        version = str(getattr(self.bot, "version", "unknown"))
        event_loop_last_lag_ms = int(getattr(self.bot, "event_loop_last_lag_ms", 0))
        jarvis_client = getattr(self.bot, "jarvis_client", None)

        jarvis_line = "JARVIS bridge: `not configured`"
        if jarvis_client is not None:
            try:
                status, body = await jarvis_client.health()
                body_text = _short_json_like(body)
                jarvis_line = f"JARVIS bridge: HTTP `{status}` `{body_text}`"
            except Exception as exc:
                jarvis_line = f"JARVIS bridge: `{type(exc).__name__}: {exc}`"

        embed = discord.Embed(
            title="JARVIS Discord Migration Status",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Version", value=f"`{version}`", inline=True)
        embed.add_field(
            name="Gateway-Latenz",
            value=f"`{round(self.bot.latency * 1000)} ms`",
            inline=True,
        )
        embed.add_field(
            name="Eventloop Lag",
            value=f"`{event_loop_last_lag_ms} ms`",
            inline=True,
        )
        embed.add_field(name="Uptime", value=f"`{_format_uptime(start_time)}`", inline=True)
        embed.add_field(name="Server", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="JARVIS", value=jarvis_line[:1024], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="jarvis_migration_status",
        description="Zeigt, dass der discord.py-Canary aktiv ist.",
    )
    async def jarvis_migration_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "discord.py-Canary läuft. Bestehende nextcord-Cogs sind noch nicht geladen.",
            ephemeral=True,
        )


def _short_json_like(value: Any, *, limit: int = 180) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MigrationCore(bot))
