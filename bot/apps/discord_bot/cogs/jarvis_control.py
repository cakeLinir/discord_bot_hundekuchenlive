# jarvis_control.py - Discord Cog for controlling and monitoring the JARVIS agent via slash commands in the existing HundekuchenBot.
from __future__ import annotations

import os
from typing import Any

import nextcord
from nextcord import SlashOption
from nextcord.ext import commands

ALLOWED_APPS = ("obs", "todo", "vscode", "discord", "spotify", "whatsapp")


def _guild_ids() -> list[int] | None:
    raw = os.getenv("JARVIS_ALLOWED_GUILD_ID", "").strip()
    if not raw:
        return None

    try:
        return [int(raw)]
    except ValueError:
        return None


def _role_ids(interaction: nextcord.Interaction) -> list[str]:
    roles = getattr(interaction.user, "roles", None)
    if not roles:
        return []

    result: list[str] = []
    for role in roles:
        role_id = getattr(role, "id", None)
        role_name = getattr(role, "name", "")
        if role_id and role_name != "@everyone":
            result.append(str(role_id))

    return result


def _shorten(message: str, limit: int = 1900) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 24] + "\n... gekürzt"


def _safe_body(body: Any) -> str:
    return _shorten(str(body), limit=700)


def _fmt_status(data: dict[str, Any]) -> str:
    status = data.get("status")
    if not status:
        return "JARVIS-Agent hat noch keinen Status ans Backend gesendet."

    return (
        "**JARVIS Agent-Status**\n"
        f"Agent: `{status.get('agentName', 'unbekannt')}`\n"
        f"Host: `{status.get('hostname', 'unbekannt')}`\n"
        f"Status: `{status.get('status', 'unbekannt')}`\n"
        f"Agent-Zeit: `{status.get('timestamp', 'unbekannt')}`\n"
        f"Backend-Empfang: `{status.get('receivedAt', 'unbekannt')}`"
    )


def _fmt_morning_log(data: dict[str, Any]) -> str:
    log = data.get("morningLog")
    if not log:
        return "Es liegt noch kein JARVIS-Morning-Log vor."

    started = ", ".join(log.get("startedApps", [])) or "Keine"
    failed = ", ".join(log.get("failedApps", [])) or "Keine"
    todos = log.get("todos", [])
    todo_text = "\n".join(f"- {item}" for item in todos[:10]) if todos else "Keine offenen TODOs."

    return (
        "**JARVIS Morning-Log**\n"
        f"Agent-Zeit: `{log.get('timestamp', 'unbekannt')}`\n"
        f"Backend-Empfang: `{log.get('receivedAt', 'unbekannt')}`\n\n"
        f"**Gestartet:** {started}\n"
        f"**Fehlgeschlagen:** {failed}\n\n"
        f"**TODOs:**\n{todo_text}\n\n"
        f"**Projekt:**\n{log.get('projectSummary', 'Keine Projektzusammenfassung vorhanden.')}"
    )


class JarvisControl(commands.Cog):
    """Discord bridge to the JARVIS backend inside the existing HundekuchenBot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _jarvis(self):
        return getattr(self.bot, "jarvis", None)

    async def _deny_if_disabled(self, interaction: nextcord.Interaction) -> bool:
        jarvis = self._jarvis()
        if not jarvis or not getattr(jarvis, "enabled", False):
            await interaction.response.send_message(
                "JARVIS Bridge ist deaktiviert. Setze `JARVIS_ENABLED=true` und `JARVIS_BRIDGE_ENABLED=true` in der Bot-.env.",
                ephemeral=True,
            )
            return True
        return False

    @nextcord.slash_command(
        name="jarvis",
        description="Steuert JARVIS über den bestehenden HundekuchenBot.",
        guild_ids=_guild_ids(),
    )
    async def jarvis_group(self, interaction: nextcord.Interaction) -> None:
        pass

    @jarvis_group.subcommand(name="status", description="Prüft Backend und Agent-Status.")
    async def jarvis_status(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)
        jarvis = self._jarvis()

        try:
            health_code, health = await jarvis.health()
            agent_code, agent = await jarvis.agent_status()

            health_data = health if isinstance(health, dict) else {}
            agent_data = agent if isinstance(agent, dict) else {}

            message = (
                "**JARVIS Backend**\n"
                f"Health HTTP: `{health_code}`\n"
                f"Status: `{health_data.get('status', health_data.get('error', 'unbekannt'))}`\n\n"
                + _fmt_status(agent_data)
            )

            if health_code >= 400 or agent_code >= 400:
                message += f"\n\nBackend-Antwort Agent HTTP `{agent_code}`: `{_safe_body(agent)}`"

            await interaction.followup.send(_shorten(message), ephemeral=True)

        except Exception as exc:
            await interaction.followup.send(f"JARVIS Status fehlgeschlagen: `{exc}`", ephemeral=True)

    @jarvis_group.subcommand(name="morning", description="Startet die JARVIS-Morgenroutine nach Bestätigung.")
    async def jarvis_morning(
        self,
        interaction: nextcord.Interaction,
        confirm_code: str = SlashOption(
            description="Zum Start exakt START eingeben.",
            required=False,
        ),
    ) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        if not confirm_code or confirm_code.strip().upper() != "START":
            await interaction.followup.send(
                "**Bestätigung erforderlich.**\n"
                "Dieser Befehl erstellt einen Backend-Command, den dein lokaler JARVIS-Agent ausführt.\n\n"
                "Führe den Befehl erneut aus mit `confirm_code: START`.",
                ephemeral=True,
            )
            return

        jarvis = self._jarvis()
        status, body = await jarvis.create_command(
            "morning_routine",
            requested_by=str(interaction.user),
            discord_user_id=str(interaction.user.id),
            discord_role_ids=_role_ids(interaction),
            payload={
                "source": "discord",
                "guildId": str(interaction.guild_id) if interaction.guild_id else None,
                "channelId": str(interaction.channel_id) if interaction.channel_id else None,
            },
        )

        if status >= 400:
            await interaction.followup.send(
                f"JARVIS Command abgelehnt HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        command_id = body.get("command", {}).get("id", "unbekannt") if isinstance(body, dict) else "unbekannt"

        await interaction.followup.send(
            f"**JARVIS Morning-Command erstellt.**\nCommand-ID: `{command_id}`",
            ephemeral=True,
        )

    @jarvis_group.subcommand(name="stop", description="Sendet einen lokalen Not-Aus-Command an JARVIS.")
    async def jarvis_stop(
        self,
        interaction: nextcord.Interaction,
        confirm_code: str = SlashOption(
            description="Zum Stop exakt STOP eingeben.",
            required=False,
        ),
    ) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        if not confirm_code or confirm_code.strip().upper() != "STOP":
            await interaction.followup.send(
                "**Bestätigung erforderlich.**\n"
                "Dieser Befehl sendet einen Stop-Command an den lokalen JARVIS-Agent.\n\n"
                "Führe den Befehl erneut aus mit `confirm_code: STOP`.",
                ephemeral=True,
            )
            return

        jarvis = self._jarvis()
        status, body = await jarvis.create_command(
            "system_stop",
            requested_by=str(interaction.user),
            discord_user_id=str(interaction.user.id),
            discord_role_ids=_role_ids(interaction),
            payload={
                "source": "discord",
                "guildId": str(interaction.guild_id) if interaction.guild_id else None,
                "channelId": str(interaction.channel_id) if interaction.channel_id else None,
            },
        )

        if status >= 400:
            await interaction.followup.send(
                f"JARVIS Stop-Command abgelehnt HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        command_id = body.get("command", {}).get("id", "unbekannt") if isinstance(body, dict) else "unbekannt"

        await interaction.followup.send(
            f"**JARVIS Stop-Command erstellt.**\nCommand-ID: `{command_id}`",
            ephemeral=True,
        )

    @jarvis_group.subcommand(name="log", description="Zeigt das letzte JARVIS-Morning-Log.")
    async def jarvis_log(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.morning_log()

        if status >= 400:
            await interaction.followup.send(
                f"Morning-Log konnte nicht gelesen werden HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            _shorten(_fmt_morning_log(body if isinstance(body, dict) else {})),
            ephemeral=True,
        )

    @jarvis_group.subcommand(name="news", description="Ruft aktuelle Dev-News aus dem JARVIS Backend ab.")
    async def jarvis_news(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.dev_news()

        if status >= 400 or not isinstance(body, dict):
            await interaction.followup.send(
                f"Dev-News fehlgeschlagen HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        items = body.get("items", [])
        errors = body.get("errors", [])

        if not items:
            error_text = "\n".join(f"- {item}" for item in errors[:5]) if errors else "Keine Fehler gemeldet."
            await interaction.followup.send(
                _shorten(f"**JARVIS Dev-News**\nKeine News geladen.\n\n**Fehler:**\n{error_text}"),
                ephemeral=True,
            )
            return

        lines = ["**JARVIS Dev-News**", f"Stand: `{body.get('fetchedAt', 'unbekannt')}`", ""]

        for item in items[:5]:
            lines.append(
                f"- **{item.get('title', 'Ohne Titel')}**\n"
                f"  Quelle: `{item.get('source', 'unbekannt')}` | Datum: `{item.get('date', 'unbekannt')}`\n"
                f"  {item.get('link', '')}"
            )

        await interaction.followup.send(_shorten("\n".join(lines)), ephemeral=True)

    @jarvis_group.subcommand(name="launch", description="Startet eine erlaubte App auf dem lokalen JARVIS-Agent.")
    async def jarvis_launch(
        self,
        interaction: nextcord.Interaction,
        app: str = SlashOption(
            description="App auswählen.",
            required=True,
            choices=list(ALLOWED_APPS),
        ),
    ) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        app_key = app.strip().lower()

        status, body = await jarvis.create_command(
            "app_open",
            requested_by=str(interaction.user),
            discord_user_id=str(interaction.user.id),
            discord_role_ids=_role_ids(interaction),
            payload={"source": "discord", "app": app_key},
        )

        if status >= 400:
            await interaction.followup.send(
                f"App-Command abgelehnt HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        command_id = body.get("command", {}).get("id", "unbekannt") if isinstance(body, dict) else "unbekannt"

        await interaction.followup.send(
            f"JARVIS App-Command erstellt: `{app_key}` | `{command_id}`",
            ephemeral=True,
        )

    @jarvis_group.subcommand(name="commands", description="Zeigt die letzten JARVIS Backend-Commands.")
    async def jarvis_commands(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.recent_commands()

        if status >= 400 or not isinstance(body, dict):
            await interaction.followup.send(
                f"Commands konnten nicht gelesen werden HTTP `{status}`: `{_safe_body(body)}`",
                ephemeral=True,
            )
            return

        commands_list = body.get("commands", [])

        if not commands_list:
            await interaction.followup.send("Keine JARVIS Commands vorhanden.", ephemeral=True)
            return

        lines = ["**Letzte JARVIS Commands**"]

        for command in commands_list[:10]:
            lines.append(
                f"- `{command.get('id')}` | `{command.get('type')}` | `{command.get('status')}` | {command.get('requestedBy')}"
            )

        await interaction.followup.send(_shorten("\n".join(lines)), ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(JarvisControl(bot))