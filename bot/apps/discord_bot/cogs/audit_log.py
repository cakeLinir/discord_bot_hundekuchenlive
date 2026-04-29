from __future__ import annotations

import traceback

import nextcord
from nextcord.ext import commands


def _interaction_command_name(interaction: nextcord.Interaction) -> str:
    command = getattr(interaction, "application_command", None)
    if command is None:
        return "unknown"

    qualified_name = getattr(command, "qualified_name", None)
    if qualified_name:
        return str(qualified_name)

    name = getattr(command, "name", None)
    return str(name or "unknown")


class AuditLog(commands.Cog):
    """
    Logs used prefix commands and application commands.

    Requires:
    - bot.db with Database instance from core.db
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        if not hasattr(self.bot, "db"):
            return

        await self.bot.db.log_command(
            guild_id=ctx.guild.id if ctx.guild else None,
            channel_id=ctx.channel.id if ctx.channel else None,
            user_id=ctx.author.id,
            command_name=ctx.command.qualified_name if ctx.command else "unknown",
            command_type="prefix",
            success=True,
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        if hasattr(self.bot, "db"):
            await self.bot.db.log_command(
                guild_id=ctx.guild.id if ctx.guild else None,
                channel_id=ctx.channel.id if ctx.channel else None,
                user_id=ctx.author.id,
                command_name=ctx.command.qualified_name if ctx.command else "unknown",
                command_type="prefix",
                success=False,
                error=type(error).__name__,
            )

        traceback.print_exception(type(error), error, error.__traceback__)

    @commands.Cog.listener()
    async def on_application_command_completion(
        self,
        interaction: nextcord.Interaction,
    ) -> None:
        if not hasattr(self.bot, "db"):
            return

        await self.bot.db.log_command(
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=interaction.channel.id if interaction.channel else None,
            user_id=interaction.user.id,
            command_name=_interaction_command_name(interaction),
            command_type="slash",
            success=True,
        )

    @commands.Cog.listener()
    async def on_application_command_error(
        self,
        interaction: nextcord.Interaction,
        error: Exception,
    ) -> None:
        if hasattr(self.bot, "db"):
            await self.bot.db.log_command(
                guild_id=interaction.guild.id if interaction.guild else None,
                channel_id=interaction.channel.id if interaction.channel else None,
                user_id=interaction.user.id,
                command_name=_interaction_command_name(interaction),
                command_type="slash",
                success=False,
                error=type(error).__name__,
            )

        traceback.print_exception(type(error), error, error.__traceback__)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AuditLog(bot))