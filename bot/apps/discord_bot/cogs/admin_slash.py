from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import nextcord
from nextcord.ext import commands

# Owner-ID aus .env lesen
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

BASE_DIR = Path(__file__).resolve().parents[1]
COGS_DIR = BASE_DIR / "cogs"

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

# cogs.admin ist die alte Prefix-Admin-Cog und soll nicht mehr geladen werden.
DENIED_LOAD_EXTENSIONS = {
    "cogs.admin",
}

# Diese Extension sollte nicht per Slash-Command entladen werden,
# sonst entfernst du dir dein eigenes Admin-Panel.
PROTECTED_UNLOAD_EXTENSIONS = {
    "cogs.admin_slash",
}


class AdminSlash(commands.Cog):
    """Slash-Commands zur Bot-Verwaltung inkl. Extension-Manager und V1.0.1-DB-Administration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------- #
    # Hilfsfunktionen
    # ------------------------------------------------------------- #

    def _is_owner(self, user_id: int) -> bool:
        """Prüft, ob der aufrufende User der Bot-Owner ist."""
        return OWNER_ID != 0 and user_id == OWNER_ID

    def _is_admin_or_owner(self, interaction: nextcord.Interaction) -> bool:
        """Prüft Owner/Admin/Moderationsrechte."""
        if self._is_owner(interaction.user.id):
            return True

        user = interaction.user
        if not isinstance(user, nextcord.Member):
            return False

        permissions = user.guild_permissions
        return bool(
            permissions.administrator
            or permissions.manage_guild
            or permissions.manage_messages
            or permissions.moderate_members
            or permissions.kick_members
            or permissions.ban_members
        )

    async def _deny(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.send_message(
            "Keine Berechtigung.",
            ephemeral=True,
        )

    def _has_db(self) -> bool:
        """Prüft, ob bot.db verfügbar ist."""
        return hasattr(self.bot, "db") and self.bot.db is not None

    async def _ensure_db(self, interaction: nextcord.Interaction) -> bool:
        """Antwortet sauber, falls die DB nicht initialisiert ist."""
        if self._has_db():
            return True

        await interaction.response.send_message(
            "Die Datenbank ist nicht initialisiert. Prüfe `bot.db` in deiner `main.py`.",
            ephemeral=True,
        )
        return False

    def _available_extensions(self) -> list[str]:
        """Ermittle alle Python-Dateien im Cogs-Verzeichnis als mögliche Extensions."""
        exts: list[str] = []

        for path in COGS_DIR.glob("*.py"):
            if path.name == "__init__.py":
                continue

            ext = f"cogs.{path.stem}"

            if ext in DENIED_LOAD_EXTENSIONS:
                continue

            exts.append(ext)

        return sorted(exts)

    @staticmethod
    def _normalize_extension_name(ext: str) -> str:
        """Erlaubt Eingaben wie `moderation` oder `cogs.moderation`."""
        ext = ext.strip()

        if not ext:
            return ext

        if not ext.startswith("cogs."):
            ext = f"cogs.{ext}"

        return ext

    def _extension_status_embed(self) -> nextcord.Embed:
        available = self._available_extensions()
        loaded = set(self.bot.extensions.keys())

        loaded_count = sum(1 for ext in available if ext in loaded)
        total_count = len(available)

        embed = nextcord.Embed(
            title="Extension Manager",
            description=f"Status: `{loaded_count}/{total_count}` Extensions geladen",
            color=nextcord.Color.blurple(),
        )

        if available:
            lines = []
            for ext in available:
                status = "✅" if ext in loaded else "⬜"
                protected = " 🔒" if ext in PROTECTED_UNLOAD_EXTENSIONS else ""
                lines.append(f"{status} `{ext}`{protected}")

            embed.add_field(
                name="Extensions",
                value="\n".join(lines)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="Extensions",
                value="Keine Extensions gefunden.",
                inline=False,
            )

        embed.add_field(
            name="Slash-Commands",
            value=(
                "`/bot extension_list`\n"
                "`/bot extension_load`\n"
                "`/bot extension_unload`\n"
                "`/bot extension_reload`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Hinweis",
            value=(
                "`cogs.admin` ist deaktiviert, weil `cogs.admin_slash` die Prefix-Admin-Cog ersetzt.\n"
                "`cogs.admin_slash` kann nicht per Slash-Command entladen werden."
            ),
            inline=False,
        )

        return embed

    @staticmethod
    def _format_rows(rows: list[dict[str, Any]], mode: str) -> str:
        """Formatiert DB-Zeilen Discord-kompatibel."""
        if not rows:
            return "Keine Einträge gefunden."

        lines: list[str] = []

        if mode == "modlog":
            for row in rows:
                created = row.get("created_at_iso") or row.get("created_at")
                reason = row.get("reason") or "-"
                lines.append(
                    f"ID `{row['id']}` | `{row['action_type']}` | "
                    f"User `{row['target_user_id']}` | Mod `{row['moderator_user_id']}` | "
                    f"{created} | Grund: {reason}"
                )

        elif mode == "commandlog":
            for row in rows:
                created = row.get("created_at_iso") or row.get("created_at")
                status = "OK" if row.get("success") else "ERR"
                error = row.get("error") or "-"
                lines.append(
                    f"ID `{row['id']}` | `{row['command_name']}` | "
                    f"User `{row['user_id']}` | `{row['command_type']}` | "
                    f"{status} | {created} | Fehler: {error}"
                )

        text = "\n".join(lines)
        return text[:1900]

    async def _count_table(self, table: str) -> int:
        """Zählt Einträge in erlaubten Tabellen."""
        allowed_tables = {
            "command_logs",
            "moderation_actions",
            "user_notes",
            "deletion_audit",
        }

        if table not in allowed_tables:
            raise ValueError(f"Nicht erlaubte Tabelle: {table}")

        db = self.bot.db.require_conn()

        async with db.execute(f"SELECT COUNT(*) AS count FROM {table}") as cursor:
            row = await cursor.fetchone()

        return int(row["count"] if row else 0)

    # ------------------------------------------------------------- #
    # /bot Gruppe
    # ------------------------------------------------------------- #

    @nextcord.slash_command(
        name="bot",
        description="Bot-Verwaltung.",
    )
    async def bot_group(self, interaction: nextcord.Interaction):
        pass

    # ------------------------------------------------------------- #
    # /bot ping
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="ping",
        description="Zeigt die aktuelle Latenz des Bots an.",
    )
    async def bot_ping(self, interaction: nextcord.Interaction):
        latency_ms = round(self.bot.latency * 1000)

        embed = nextcord.Embed(
            title="Pong!",
            description=f"Latenz: `{latency_ms} ms`",
            color=nextcord.Color.green(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------- #
    # /bot info
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="info",
        description="Zeigt Informationen über den Bot an.",
    )
    async def bot_info(self, interaction: nextcord.Interaction):
        uptime_seconds = int(time.time() - getattr(self.bot, "start_time", time.time()))
        uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m"

        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count or 0 for g in self.bot.guilds)

        embed = nextcord.Embed(
            title="Bot-Info",
            color=nextcord.Color.blurple(),
        )

        embed.add_field(name="Name", value=str(self.bot.user), inline=True)
        embed.add_field(name="ID", value=str(self.bot.user.id), inline=True)
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Server", value=str(guild_count), inline=True)
        embed.add_field(name="Benutzer ungefähr", value=str(user_count), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------- #
    # /bot shutdown
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="shutdown",
        description="Fährt den Bot herunter. Nur Owner.",
    )
    async def bot_shutdown(self, interaction: nextcord.Interaction):
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Du bist nicht als Owner konfiguriert. Zugriff verweigert.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Bot wird heruntergefahren...",
            ephemeral=True,
        )

        await self.bot.close()

    # ------------------------------------------------------------- #
    # Extension Manager
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="extension_list",
        description="Zeigt alle verfügbaren Extensions und deren Status.",
    )
    async def bot_extension_list(self, interaction: nextcord.Interaction):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        embed = self._extension_status_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot_group.subcommand(
        name="extension_load",
        description="Lädt eine Extension. Beispiel: moderation oder cogs.moderation",
    )
    async def bot_extension_load(
        self,
        interaction: nextcord.Interaction,
        ext: str,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        ext = self._normalize_extension_name(ext)
        available = self._available_extensions()
        loaded = set(self.bot.extensions.keys())

        if ext in DENIED_LOAD_EXTENSIONS:
            await interaction.response.send_message(
                f"`{ext}` ist deaktiviert. Nutze `cogs.admin_slash`.",
                ephemeral=True,
            )
            return

        if ext not in available:
            await interaction.response.send_message(
                "Unbekannte Extension. Nutze `/bot extension_list` für die Liste.",
                ephemeral=True,
            )
            return

        if ext in loaded:
            await interaction.response.send_message(
                f"`{ext}` ist bereits geladen. Nutze `/bot extension_reload`.",
                ephemeral=True,
            )
            return

        try:
            self.bot.load_extension(ext)
        except Exception as exc:
            await interaction.response.send_message(
                f"Laden fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )
            raise

        await interaction.response.send_message(
            f"Geladen: `{ext}`",
            ephemeral=True,
        )

    @bot_group.subcommand(
        name="extension_unload",
        description="Entlädt eine Extension. Beispiel: moderation oder cogs.moderation",
    )
    async def bot_extension_unload(
        self,
        interaction: nextcord.Interaction,
        ext: str,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        ext = self._normalize_extension_name(ext)

        if ext in PROTECTED_UNLOAD_EXTENSIONS:
            await interaction.response.send_message(
                f"`{ext}` ist geschützt und kann nicht per Slash-Command entladen werden.",
                ephemeral=True,
            )
            return

        if ext not in self.bot.extensions:
            await interaction.response.send_message(
                f"`{ext}` ist nicht geladen.",
                ephemeral=True,
            )
            return

        try:
            self.bot.unload_extension(ext)
        except Exception as exc:
            await interaction.response.send_message(
                f"Entladen fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )
            raise

        await interaction.response.send_message(
            f"Entladen: `{ext}`",
            ephemeral=True,
        )

    @bot_group.subcommand(
        name="extension_reload",
        description="Lädt eine geladene Extension neu. Beispiel: moderation oder cogs.moderation",
    )
    async def bot_extension_reload(
        self,
        interaction: nextcord.Interaction,
        ext: str,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        ext = self._normalize_extension_name(ext)

        if ext in DENIED_LOAD_EXTENSIONS:
            await interaction.response.send_message(
                f"`{ext}` ist deaktiviert. Entlade es mit `/bot extension_unload`, falls es noch geladen ist.",
                ephemeral=True,
            )
            return

        if ext == "cogs.admin_slash":
            await interaction.response.send_message(
                "`cogs.admin_slash` bitte über einen Bot-Neustart aktualisieren, damit du dich nicht selbst aussperrst.",
                ephemeral=True,
            )
            return

        if ext not in self.bot.extensions:
            await interaction.response.send_message(
                f"`{ext}` ist nicht geladen. Nutze zuerst `/bot extension_load`.",
                ephemeral=True,
            )
            return

        try:
            self.bot.reload_extension(ext)
        except Exception as exc:
            await interaction.response.send_message(
                f"Reload fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )
            raise

        await interaction.response.send_message(
            f"Neu geladen: `{ext}`",
            ephemeral=True,
        )

    # ------------------------------------------------------------- #
    # /bot db_status
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_status",
        description="Zeigt Status und Tabellenanzahl der Bot-Datenbank.",
    )
    async def bot_db_status(self, interaction: nextcord.Interaction):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        try:
            command_logs = await self._count_table("command_logs")
            moderation_actions = await self._count_table("moderation_actions")
            user_notes = await self._count_table("user_notes")
            deletion_audit = await self._count_table("deletion_audit")

            db_path = getattr(self.bot.db, "db_path", "unbekannt")

            embed = nextcord.Embed(
                title="Datenbankstatus",
                color=nextcord.Color.green(),
            )
            embed.add_field(name="DB-Datei", value=f"`{db_path}`", inline=False)
            embed.add_field(name="Command-Logs", value=f"`{command_logs}`", inline=True)
            embed.add_field(name="Moderationsaktionen", value=f"`{moderation_actions}`", inline=True)
            embed.add_field(name="User-Notes", value=f"`{user_notes}`", inline=True)
            embed.add_field(name="Lösch-Audit", value=f"`{deletion_audit}`", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as exc:
            await interaction.response.send_message(
                f"DB-Status konnte nicht gelesen werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    # ------------------------------------------------------------- #
    # /bot db_cleanup
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_cleanup",
        description="Löscht gespeicherte Userdaten älter als X Tage.",
    )
    async def bot_db_cleanup(
        self,
        interaction: nextcord.Interaction,
        retention_days: int = 30,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if retention_days < 1:
            await interaction.response.send_message(
                "retention_days muss mindestens `1` sein.",
                ephemeral=True,
            )
            return

        if retention_days > 365:
            await interaction.response.send_message(
                "retention_days darf maximal `365` sein.",
                ephemeral=True,
            )
            return

        result = await self.bot.db.delete_old_user_data(
            retention_days=retention_days,
        )

        await interaction.response.send_message(
            (
                f"DB-Cleanup abgeschlossen für Daten älter als `{retention_days}` Tage.\n"
                f"Gelöscht gesamt: `{result.affected_rows}`\n"
                f"- Command-Logs: `{result.command_logs}`\n"
                f"- Moderationsaktionen: `{result.moderation_actions}`\n"
                f"- User-Notes: `{result.user_notes}`\n"
                f"- Lösch-Audit: `{result.deletion_audit}`"
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------- #
    # /bot db_user_summary
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_user_summary",
        description="Zeigt gespeicherte Daten-Zusammenfassung für einen User.",
    )
    async def bot_db_user_summary(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        summary = await self.bot.db.get_user_summary(
            guild_id=interaction.guild.id,
            user_id=user.id,
        )

        embed = nextcord.Embed(
            title="Userdaten-Zusammenfassung",
            description=f"Gespeicherte Daten für {user.mention}",
            color=nextcord.Color.blurple(),
        )

        embed.add_field(name="Commands", value=f"`{summary['commands']}`", inline=True)
        embed.add_field(name="Warns", value=f"`{summary['warn']}`", inline=True)
        embed.add_field(name="Mutes", value=f"`{summary['mute']}`", inline=True)
        embed.add_field(name="Timeouts", value=f"`{summary['timeout']}`", inline=True)
        embed.add_field(name="Kicks", value=f"`{summary['kick']}`", inline=True)
        embed.add_field(name="Bans", value=f"`{summary['ban']}`", inline=True)
        embed.add_field(name="Notes", value=f"`{summary['notes']}`", inline=True)
        embed.add_field(name="Moderation gesamt", value=f"`{summary['moderation_total']}`", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------- #
    # /bot db_user_delete
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_user_delete",
        description="Löscht gespeicherte Daten eines Users manuell.",
    )
    async def bot_db_user_delete(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        include_as_moderator: bool = False,
        global_delete: bool = False,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        result = await self.bot.db.delete_user_data(
            user_id=user.id,
            moderator_user_id=interaction.user.id,
            guild_id=None if global_delete else interaction.guild.id,
            include_as_moderator=include_as_moderator,
        )

        await interaction.response.send_message(
            (
                f"Gespeicherte Daten für {user.mention} wurden gelöscht.\n"
                f"Gelöscht gesamt: `{result.affected_rows}`\n"
                f"- Command-Logs: `{result.command_logs}`\n"
                f"- Moderationsaktionen: `{result.moderation_actions}`\n"
                f"- User-Notes: `{result.user_notes}`"
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------- #
    # /bot db_modlog_filter
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_modlog_filter",
        description="Filtert gespeicherte Moderationsaktionen.",
    )
    async def bot_db_modlog_filter(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = None,
        moderator: nextcord.Member | None = None,
        action_type: str | None = nextcord.SlashOption(
            required=False,
            choices=ACTION_CHOICES,
        ),
        limit: int = 20,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        limit = max(1, min(limit, 100))

        rows = await self.bot.db.filter_moderation_actions(
            guild_id=interaction.guild.id,
            target_user_id=user.id if user else None,
            moderator_user_id=moderator.id if moderator else None,
            action_type=action_type,
            limit=limit,
        )

        await interaction.response.send_message(
            self._format_rows(rows, mode="modlog"),
            ephemeral=True,
        )

    # ------------------------------------------------------------- #
    # /bot db_modlog_delete
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_modlog_delete",
        description="Löscht einen einzelnen Moderationslog-Eintrag per ID.",
    )
    async def bot_db_modlog_delete(
        self,
        interaction: nextcord.Interaction,
        action_id: int,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
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

    # ------------------------------------------------------------- #
    # /bot db_commandlog_filter
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_commandlog_filter",
        description="Filtert gespeicherte Command-Logs.",
    )
    async def bot_db_commandlog_filter(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member | None = None,
        command_name: str | None = None,
        only_errors: bool = False,
        limit: int = 20,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        limit = max(1, min(limit, 100))

        rows = await self.bot.db.filter_command_logs(
            guild_id=interaction.guild.id,
            user_id=user.id if user else None,
            command_name=command_name,
            success=False if only_errors else None,
            limit=limit,
        )

        await interaction.response.send_message(
            self._format_rows(rows, mode="commandlog"),
            ephemeral=True,
        )

    # ------------------------------------------------------------- #
    # /bot db_note_add
    # ------------------------------------------------------------- #

    @bot_group.subcommand(
        name="db_note_add",
        description="Speichert eine Moderationsnotiz zu einem User.",
    )
    async def bot_db_note_add(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member,
        note: str,
    ):
        if not self._is_admin_or_owner(interaction):
            await self._deny(interaction)
            return

        if not await self._ensure_db(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        if len(note.strip()) < 3:
            await interaction.response.send_message(
                "Die Notiz ist zu kurz.",
                ephemeral=True,
            )
            return

        note_id = await self.bot.db.add_user_note(
            guild_id=interaction.guild.id,
            user_id=user.id,
            moderator_user_id=interaction.user.id,
            note=note.strip(),
        )

        await interaction.response.send_message(
            f"Notiz für {user.mention} gespeichert. Note-ID: `{note_id}`",
            ephemeral=True,
        )


def setup(bot: commands.Bot):
    bot.add_cog(AdminSlash(bot))