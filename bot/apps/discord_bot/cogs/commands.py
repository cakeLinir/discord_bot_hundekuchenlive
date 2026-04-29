from __future__ import annotations

import datetime as dt
import time
from typing import Final

import nextcord
from nextcord.ext import commands

# ---------------------------------------------------------------------------
# Zentrale Links
# ---------------------------------------------------------------------------

SOCIAL_LINKS: Final[dict[str, str]] = {
    "Twitch": "https://twitch.tv/hundekuchenlive",
    "Discord": "https://discord.gg/WfTbuyhXcJ",
    "Twitter / X": "https://x.com/hundekuchenlive",
    "TikTok": "https://www.tiktok.com/@hundekuchenlive",
    "Instagram": "https://www.instagram.com/hundekuchenlive",
}

BRAND_COLOR: Final[int] = 0x00FFCC
GOLD_COLOR: Final[int] = 0xF1C40F
GREEN_COLOR: Final[int] = 0x2ECC71
RED_COLOR: Final[int] = 0xE74C3C
BLURPLE_COLOR: Final[int] = 0x5865F2


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class SocialsView(nextcord.ui.View):
    """Link-Buttons für Social-Media-Profile."""

    def __init__(self):
        super().__init__(timeout=180)

        button_labels = {
            "Twitch": "Twitch",
            "Discord": "Discord",
            "Twitter / X": "X / Twitter",
            "TikTok": "TikTok",
            "Instagram": "Instagram",
        }

        for name, url in SOCIAL_LINKS.items():
            self.add_item(
                nextcord.ui.Button(
                    label=button_labels.get(name, name),
                    url=url,
                    style=nextcord.ButtonStyle.link,
                )
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class Commands(commands.Cog):
    """Öffentliche Slash-Commands für allgemeine Bot-Informationen."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        if not hasattr(bot, "start_time"):
            bot.start_time = time.time()

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #

    def _format_uptime(self) -> str:
        uptime_seconds = int(time.time() - getattr(self.bot, "start_time", time.time()))

        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m {seconds}s"

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"

        if minutes > 0:
            return f"{minutes}m {seconds}s"

        return f"{seconds}s"

    def _guild_user_count(self) -> int:
        return sum(guild.member_count or 0 for guild in self.bot.guilds)

    def _base_embed(
        self,
        *,
        title: str,
        description: str | None = None,
        color: int = BRAND_COLOR,
    ) -> nextcord.Embed:
        embed = nextcord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )

        if self.bot.user:
            embed.set_footer(
                text=f"hundekuchenlive Bot • {self.bot.user}",
                icon_url=self.bot.user.display_avatar.url,
            )

        return embed

    def _build_ping_embed(self) -> nextcord.Embed:
        latency_ms = round(self.bot.latency * 1000)

        if latency_ms <= 100:
            quality = "Sehr gut"
            color = GREEN_COLOR
        elif latency_ms <= 250:
            quality = "Okay"
            color = GOLD_COLOR
        else:
            quality = "Hoch"
            color = RED_COLOR

        embed = self._base_embed(
            title="Bot-Latenz",
            description="Verbindungstest erfolgreich.",
            color=color,
        )

        embed.add_field(
            name="Latenz",
            value=f"`{latency_ms} ms`",
            inline=True,
        )
        embed.add_field(
            name="Bewertung",
            value=f"`{quality}`",
            inline=True,
        )

        return embed

    def _build_status_embed(self) -> nextcord.Embed:
        latency_ms = round(self.bot.latency * 1000)
        guild_count = len(self.bot.guilds)
        user_count = self._guild_user_count()

        embed = self._base_embed(
            title="Bot Status",
            description="Aktueller Systemstatus und Laufzeitinformationen.",
            color=GREEN_COLOR,
        )

        embed.add_field(
            name="Status",
            value="`Online`",
            inline=True,
        )
        embed.add_field(
            name="Latenz",
            value=f"`{latency_ms} ms`",
            inline=True,
        )
        embed.add_field(
            name="Uptime",
            value=f"`{self._format_uptime()}`",
            inline=True,
        )
        embed.add_field(
            name="Server",
            value=f"`{guild_count}`",
            inline=True,
        )
        embed.add_field(
            name="Benutzer ungefähr",
            value=f"`{user_count}`",
            inline=True,
        )
        embed.add_field(
            name="Version",
            value="`V1.0.1`",
            inline=True,
        )

        return embed

    def _build_socials_embed(self) -> nextcord.Embed:
        embed = self._base_embed(
            title="hundekuchenlive – Socials",
            description=(
                "Alle offiziellen Links kompakt an einem Ort.\n"
                "Nutze die Buttons unter dem Embed, um direkt zur jeweiligen Plattform zu springen."
            ),
            color=BLURPLE_COLOR,
        )

        embed.add_field(
            name="Livestream",
            value=f"[Twitch]({SOCIAL_LINKS['Twitch']})",
            inline=True,
        )
        embed.add_field(
            name="Community",
            value=f"[Discord]({SOCIAL_LINKS['Discord']})",
            inline=True,
        )
        embed.add_field(
            name="Kurzvideos",
            value=f"[TikTok]({SOCIAL_LINKS['TikTok']})",
            inline=True,
        )
        embed.add_field(
            name="Updates",
            value=f"[X / Twitter]({SOCIAL_LINKS['Twitter / X']})",
            inline=True,
        )
        embed.add_field(
            name="Bilder & Clips",
            value=f"[Instagram]({SOCIAL_LINKS['Instagram']})",
            inline=True,
        )

        return embed

    def _build_help_embed(self) -> nextcord.Embed:
        embed = self._base_embed(
            title="hundekuchenlive – Command Center",
            description=(
                "Übersicht der wichtigsten Slash-Commands.\n"
                "Einige Befehle sind nur für Mods oder Admins nutzbar."
            ),
            color=GOLD_COLOR,
        )

        embed.add_field(
            name="Allgemein",
            value=(
                "`/ping`\n"
                "Zeigt die aktuelle Bot-Latenz.\n\n"
                "`/status`\n"
                "Zeigt Uptime, Serveranzahl und Systemstatus.\n\n"
                "`/socials`\n"
                "Zeigt offizielle Links mit Button-Menü.\n\n"
                "`/hilfe`\n"
                "Öffnet dieses Command Center."
            ),
            inline=False,
        )

        embed.add_field(
            name="Bot-Verwaltung",
            value=(
                "`/bot ping`\n"
                "Admin-Ping des Bots.\n\n"
                "`/bot info`\n"
                "Technische Bot-Informationen.\n\n"
                "`/bot extension_list`\n"
                "Zeigt geladene und verfügbare Cogs.\n\n"
                "`/bot extension_load`\n"
                "Lädt eine Extension.\n\n"
                "`/bot extension_unload`\n"
                "Entlädt eine Extension.\n\n"
                "`/bot extension_reload`\n"
                "Lädt eine Extension neu.\n\n"
                "`/bot shutdown`\n"
                "Fährt den Bot herunter. Nur Owner."
            ),
            inline=False,
        )

        embed.add_field(
            name="Datenbank / Datenschutz",
            value=(
                "`/bot db_status`\n"
                "Zeigt Datenbankstatus und Tabellenanzahl.\n\n"
                "`/bot db_cleanup`\n"
                "Löscht alte Userdaten nach Retention-Regel.\n\n"
                "`/bot db_user_summary`\n"
                "Zeigt gespeicherte Daten zu einem User.\n\n"
                "`/bot db_user_delete`\n"
                "Löscht gespeicherte Userdaten manuell.\n\n"
                "`/bot db_modlog_filter`\n"
                "Filtert gespeicherte Moderationslogs.\n\n"
                "`/bot db_modlog_delete`\n"
                "Löscht einen einzelnen Moderationslog.\n\n"
                "`/bot db_commandlog_filter`\n"
                "Filtert gespeicherte Commandlogs.\n\n"
                "`/bot db_note_add`\n"
                "Speichert eine Moderationsnotiz."
            ),
            inline=False,
        )

        embed.add_field(
            name="Moderation",
            value=(
                "`/mod warn`\n"
                "User verwarnen und Strike hinzufügen.\n\n"
                "`/mod timeout`\n"
                "Timeout setzen.\n\n"
                "`/mod untimeout`\n"
                "Timeout entfernen.\n\n"
                "`/mod kick`\n"
                "User kicken.\n\n"
                "`/mod ban`\n"
                "User bannen.\n\n"
                "`/mod clear`\n"
                "Nachrichten löschen.\n\n"
                "`/mod strikes`\n"
                "Aktive Strikes anzeigen.\n\n"
                "`/mod strike_add`\n"
                "Strike manuell hinzufügen.\n\n"
                "`/mod strike_clear`\n"
                "Strikes eines Users löschen.\n\n"
                "`/mod badword_add`\n"
                "Badword hinzufügen.\n\n"
                "`/mod badword_remove`\n"
                "Badword entfernen.\n\n"
                "`/mod badword_list`\n"
                "Badword-Liste anzeigen."
            ),
            inline=False,
        )

        embed.add_field(
            name="Embeds",
            value=(
                "`/embed preview`\n"
                "Zeigt eine private Embed-Vorschau.\n\n"
                "`/embed send`\n"
                "Sendet ein Embed in einen Channel.\n\n"
                "`/embed edit`\n"
                "Bearbeitet ein bestehendes Bot-Embed."
            ),
            inline=False,
        )

        embed.add_field(
            name="Selfroles",
            value=(
                "`/selfrole fixed_panel`\n"
                "Erstellt oder aktualisiert das feste Regelwerk/Twitch/YouTube-Panel.\n\n"
                "`/selfrole create`\n"
                "Erstellt ein dynamisches Selfrole-Panel.\n\n"
                "`/selfrole add`\n"
                "Fügt einem Panel eine Rolle hinzu.\n\n"
                "`/selfrole remove`\n"
                "Entfernt eine Rolle aus einem Panel.\n\n"
                "`/selfrole list`\n"
                "Listet gespeicherte Selfrole-Konfigurationen.\n\n"
                "`/selfrole delete_config`\n"
                "Löscht eine Selfrole-Konfiguration."
            ),
            inline=False,
        )

        embed.add_field(
            name="Hinweis",
            value=(
                "Die meisten Verwaltungs-, Datenbank- und Moderationsbefehle "
                "sind nur mit entsprechenden Serverrechten nutzbar."
            ),
            inline=False,
        )

        return embed

    # ------------------------------------------------------------------ #
    # Slash-Commands
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="ping",
        description="Zeigt die aktuelle Latenz des Bots an.",
    )
    async def ping_slash(self, interaction: nextcord.Interaction) -> None:
        embed = self._build_ping_embed()

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="status",
        description="Zeigt den Status des Bots an.",
    )
    async def status_slash(self, interaction: nextcord.Interaction):
        started = time.perf_counter()
        await interaction.response.defer(ephemeral=True)

        uptime_seconds = int(time.time() - self.bot.start_time)
        uptime_str = time.strftime("%H:%M:%S", time.gmtime(uptime_seconds))

        websocket_latency_ms = round(self.bot.latency * 1000)
        command_response_ms = round((time.perf_counter() - started) * 1000)

        if websocket_latency_ms < 0:
            latency_label = "unbekannt"
            latency_status = "⚪ unbekannt"
        elif websocket_latency_ms <= 300:
            latency_label = f"{websocket_latency_ms} ms"
            latency_status = "🟢 normal"
        elif websocket_latency_ms <= 1500:
            latency_label = f"{websocket_latency_ms} ms"
            latency_status = "🟡 erhöht"
        elif websocket_latency_ms <= 60_000:
            latency_label = f"{websocket_latency_ms} ms"
            latency_status = "🟠 kritisch"
        else:
            latency_label = f"{websocket_latency_ms} ms"
            latency_status = "🔴 Gateway hängt"

        embed = nextcord.Embed(
            title="Bot Status",
            description="Aktueller Systemstatus und Laufzeitinformationen.",
            color=(
                nextcord.Color.green()
                if websocket_latency_ms <= 1500
                else nextcord.Color.orange()
            ),
        )

        embed.add_field(name="Status", value="`Online`", inline=True)
        embed.add_field(name="Gateway", value=f"`{latency_status}`", inline=True)
        embed.add_field(
            name="WebSocket-Latenz", value=f"`{latency_label}`", inline=True
        )

        embed.add_field(
            name="Command Response", value=f"`{command_response_ms} ms`", inline=True
        )
        embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="Version", value="`V1.0.1`", inline=True)

        embed.add_field(name="Server", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(
            name="Benutzer ungefähr",
            value=f"`{sum(g.member_count or 0 for g in self.bot.guilds)}`",
            inline=True,
        )

        if websocket_latency_ms > 60_000:
            embed.add_field(
                name="Hinweis",
                value=(
                    "Die WebSocket-Latenz ist extrem hoch. Das ist kein normaler Ping, "
                    "sondern ein Hinweis auf blockierte Discord-Heartbeats oder einen hängenden Eventloop."
                ),
                inline=False,
            )

        if self.bot.user:
            embed.set_footer(
                text=f"hundekuchenlive Bot • {self.bot.user}",
                icon_url=self.bot.user.display_avatar.url,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @nextcord.slash_command(
        name="socials",
        description="Zeigt alle Social-Media-Links von hundekuchenlive an.",
    )
    async def socials_slash(self, interaction: nextcord.Interaction) -> None:
        embed = self._build_socials_embed()
        view = SocialsView()

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="hilfe",
        description="Zeigt eine Übersicht der wichtigsten Bot-Befehle.",
    )
    async def hilfe_slash(self, interaction: nextcord.Interaction) -> None:
        embed = self._build_help_embed()

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="commands",
        description="Öffnet das stylische Command Center.",
    )
    async def commands_slash(self, interaction: nextcord.Interaction) -> None:
        embed = self._build_help_embed()

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Commands(bot))
