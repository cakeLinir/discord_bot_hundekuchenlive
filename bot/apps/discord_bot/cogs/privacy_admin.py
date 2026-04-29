from __future__ import annotations

import os

import nextcord
from nextcord.ext import commands, tasks


ACTION_CHOICES = {
    "warn": "warn",
    "mute": "mute",
    "timeout": "timeout",
    "kick": "kick",
    "ban": "ban",
    "unmute": "unmute",
    "untimeout": "untimeout",
    "unban": "unban",
    "note": "note",
    "other": "other",
}


def _is_mod(interaction: nextcord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, nextcord.Member):
        return False

    permissions = user.guild_permissions
    return bool(
        permissions.manage_guild
        or permissions.manage_messages
        or permissions.moderate_members
        or permissions.kick_members
        or permissions.ban_members
        or permissions.administrator
    )


def _format_mod_rows(rows: list[dict]) -> str:
    if not rows:
        return "Keine Einträge gefunden."

    lines: list[str] = []
    for row in rows:
        created = row.get("created_at_iso") or row.get("created_at")
        reason = row.get("reason") or "-"
        lines.append(
            f"ID `{row['id']}` | `{row['action_type']}` | "
            f"User `{row['target_user_id']}` | Mod `{row['moderator_user_id']}` | "
            f"{created} | Grund: {reason}"
        )

    text = "\n".join(lines)
    return text[:1900]


def _format_command_rows(rows: list[dict]) -> str:
    if not rows:
        return "Keine Einträge gefunden."

    lines: list[str] = []
    for row in rows:
        created = row.get("created_at_iso") or row.get("created_at")
        status = "OK" if row.get("success") else "ERR"
        lines.append(
            f"ID `{row['id']}` | `{row['command_name']}` | "
            f"User `{row['user_id']}` | `{row['command_type']}` | {status} | {created}"
        )

    text = "\n".join(lines)
    return text[:1900]


class PrivacyAdmin(commands.Cog):
    """
    Admin/Moderator commands for stored user data.

    Commands:
    - /userdata summary
    - /userdata delete
    - /modlog filter
    - /modlog delete
    - /commandlog filter
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.retention_days = int(os.getenv("RETENTION_DAYS", "30"))
        self.cleanup_interval_hours = int(os.getenv("RETENTION_CLEANUP_INTERVAL_HOURS", "24"))
        self.cleanup_old_data.change_interval(hours=self.cleanup_interval_hours)
        self.cleanup_old_data.start()

    def cog_unload(self) -> None:
        self.cleanup_old_data.cancel()

    @tasks.loop(hours=24)
    async def cleanup_old_data(self) -> None:
        if not hasattr(self.bot, "db"):
            return

        result = await self.bot.db.delete_old_user_data(
            retention_days=self.retention_days,
        )
        print(
            "[Privacy] Auto-cleanup completed: "
            f"{result.affected_rows} rows deleted."
        )

    @cleanup_old_data.before_loop
    async def before_cleanup_old_data(self) -> None:
        await self.bot.wait_until_ready()

    @nextcord.slash_command(
        name="userdata",
        description="Gespeicherte Userdaten verwalten",
    )
    async def userdata(self, interaction: nextcord.Interaction) -> None:
        pass

    @userdata.subcommand(
        name="summary",
        description="Zeigt gespeicherte Daten-Zusammenfassung für einen User",
    )
    async def userdata_summary(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
    ) -> None:
        if not _is_mod(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        summary = await self.bot.db.get_user_summary(
            guild_id=interaction.guild.id,
            user_id=user.id,
        )

        text = (
            f"**Userdaten für {user.mention}**\n"
            f"Commands: `{summary['commands']}`\n"
            f"Warns: `{summary['warn']}`\n"
            f"Mutes: `{summary['mute']}`\n"
            f"Timeouts: `{summary['timeout']}`\n"
            f"Kicks: `{summary['kick']}`\n"
            f"Bans: `{summary['ban']}`\n"
            f"Notes: `{summary['notes']}`\n"
            f"Moderation gesamt: `{summary['moderation_total']}`"
        )

        await interaction.response.send_message(text, ephemeral=True)

    @userdata.subcommand(
        name="delete",
        description="Löscht gespeicherte Daten eines Users manuell",
    )
    async def userdata_delete(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        include_as_moderator: bool = False,
        global_delete: bool = False,
    ) -> None:
        if not _is_mod(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        result = await self.bot.db.delete_user_data(
            user_id=user.id,
            moderator_user_id=interaction.user.id,
            guild_id=None if global_delete else interaction.guild.id,
            include_as_moderator=include_as_moderator,
        )

        await interaction.response.send_message(
            (
                f"Gelöscht: `{result.affected_rows}` Datensätze für {user.mention}.\n"
                f"- Command-Logs: `{result.command_logs}`\n"
                f"- Moderationsaktionen: `{result.moderation_actions}`\n"
                f"- User-Notes: `{result.user_notes}`"
            ),
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="modlog",
        description="Moderationsdaten durchsuchen und verwalten",
    )
    async def modlog(self, interaction: nextcord.Interaction) -> None:
        pass

    @modlog.subcommand(
        name="filter",
        description="Filtert gespeicherte Moderationsaktionen",
    )
    async def modlog_filter(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = None,
        moderator: nextcord.Member | None = None,
        action_type: str | None = nextcord.SlashOption(
            required=False,
            choices=ACTION_CHOICES,
        ),
        limit: int = 20,
    ) -> None:
        if not _is_mod(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        rows = await self.bot.db.filter_moderation_actions(
            guild_id=interaction.guild.id,
            target_user_id=user.id if user else None,
            moderator_user_id=moderator.id if moderator else None,
            action_type=action_type,
            limit=limit,
        )

        await interaction.response.send_message(
            _format_mod_rows(rows),
            ephemeral=True,
        )

    @modlog.subcommand(
        name="delete",
        description="Löscht einen einzelnen Moderationslog-Eintrag per ID",
    )
    async def modlog_delete(
        self,
        interaction: nextcord.Interaction,
        action_id: int,
    ) -> None:
        if not _is_mod(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        deleted = await self.bot.db.delete_moderation_action_by_id(
            action_id=action_id,
            moderator_user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )

        await interaction.response.send_message(
            f"Gelöschte Moderationslog-Einträge: `{deleted}`",
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="commandlog",
        description="Command-Logs durchsuchen",
    )
    async def commandlog(self, interaction: nextcord.Interaction) -> None:
        pass

    @commandlog.subcommand(
        name="filter",
        description="Filtert gespeicherte Command-Logs",
    )
    async def commandlog_filter(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = None,
        command_name: str | None = None,
        only_errors: bool = False,
        limit: int = 20,
    ) -> None:
        if not _is_mod(interaction):
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        rows = await self.bot.db.filter_command_logs(
            guild_id=interaction.guild.id,
            user_id=user.id if user else None,
            command_name=command_name,
            success=False if only_errors else None,
            limit=limit,
        )

        await interaction.response.send_message(
            _format_command_rows(rows),
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(PrivacyAdmin(bot))