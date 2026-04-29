from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import nextcord
from nextcord import SlashOption
from nextcord.ext import commands

from core.sevendtd_api import (
    SevenDTDAPI,
    SevenDTDAPIError,
    SevenDTDCommandBlockedError,
    extract_data,
    extract_list,
    flatten_key_value_list,
    extract_player_count,
)


# ---------------------------------------------------------------------------
# Env / IDs
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    if not value.isdigit():
        return default
    return int(value)


OWNER_ID = _env_int("BOT_OWNER_ID", 0)
MOD_ROLE_ID = _env_int("MOD_ROLE_ID", 0)


# ---------------------------------------------------------------------------
# Panel State
# ---------------------------------------------------------------------------

BOT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = BOT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEVENDTD_PANEL_STATE_FILE = DATA_DIR / "sevendtd_panel_state.json"


def load_panel_state() -> dict[str, Any]:
    if not SEVENDTD_PANEL_STATE_FILE.exists():
        return {}

    try:
        data = json.loads(SEVENDTD_PANEL_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_panel_state(state: dict[str, Any]) -> None:
    SEVENDTD_PANEL_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Sicherheit
# ---------------------------------------------------------------------------

DANGEROUS_RAW_BLOCKLIST = {
    "shutdown",
    "webtokens",
    "webpermission",
    "commandpermission",
    "admin",
    "config",
    "setgamepref",
    "setgamestat",
    "settime",
    "give",
    "giveself",
    "givexp",
    "kill",
    "killall",
    "spawnentity",
    "spawnentityat",
    "debugmenu",
    "creativemenu",
    "regionreset",
    "chunkreset",
}


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class DashboardView(nextcord.ui.View):
    """Temporärer Dashboard-Link für Slash-Antworten."""

    def __init__(self, dashboard_url: str):
        super().__init__(timeout=180)

        self.add_item(
            nextcord.ui.Button(
                label="7DTD Dashboard öffnen",
                url=dashboard_url,
                style=nextcord.ButtonStyle.link,
            )
        )


class SevenDTDPanelView(nextcord.ui.View):
    """Persistente Buttons für das 7DTD Live-Panel."""

    def __init__(self, bot: commands.Bot, dashboard_url: str):
        super().__init__(timeout=None)
        self.bot = bot

        self.add_item(
            nextcord.ui.Button(
                label="Dashboard öffnen",
                url=dashboard_url,
                style=nextcord.ButtonStyle.link,
            )
        )

    def _cog(self) -> "SevenDTD | None":
        cog = self.bot.get_cog("SevenDTD")
        return cog if isinstance(cog, SevenDTD) else None

    @nextcord.ui.button(
        label="Aktualisieren",
        style=nextcord.ButtonStyle.primary,
        custom_id="7dtd_panel:refresh",
    )
    async def btn_refresh(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        cog = self._cog()
        if cog is None:
            await interaction.followup.send("7DTD-Cog nicht geladen.", ephemeral=True)
            return

        if interaction.message is None:
            await interaction.followup.send(
                "Panel-Nachricht nicht gefunden.", ephemeral=True
            )
            return

        try:
            embed = await cog._build_status_embed(panel_mode=True)
            await interaction.message.edit(embed=embed, view=self)

            await interaction.followup.send("7DTD Panel aktualisiert.", ephemeral=True)

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel refresh",
                success=True,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Aktualisierung fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel refresh",
                success=False,
                error=type(exc).__name__,
            )

    @nextcord.ui.button(
        label="Spieler",
        style=nextcord.ButtonStyle.secondary,
        custom_id="7dtd_panel:players",
    )
    async def btn_players(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        cog = self._cog()
        if cog is None:
            await interaction.followup.send("7DTD-Cog nicht geladen.", ephemeral=True)
            return

        try:
            embed = await cog._build_players_embed()
            await interaction.followup.send(embed=embed, ephemeral=True)

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel players",
                success=True,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Spielerliste fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel players",
                success=False,
                error=type(exc).__name__,
            )

    @nextcord.ui.button(
        label="Saveworld",
        style=nextcord.ButtonStyle.success,
        custom_id="7dtd_panel:saveworld",
    )
    async def btn_saveworld(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        cog = self._cog()
        if cog is None:
            await interaction.response.send_message(
                "7DTD-Cog nicht geladen.", ephemeral=True
            )
            return

        if not cog._is_mod_or_admin(interaction):
            await cog._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            body = await cog.api.save_world()
            result = cog._format_command_result(body)

            await interaction.followup.send(
                f"`saveworld` wurde ausgeführt.\nAntwort: `{result[:1500] or 'Keine Ausgabe.'}`",
                ephemeral=True,
            )

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel saveworld",
                success=True,
            )

        except SevenDTDCommandBlockedError as exc:
            await interaction.followup.send(
                f"Command blockiert: `{exc}`",
                ephemeral=True,
            )

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel saveworld",
                success=False,
                error=type(exc).__name__,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Saveworld fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await cog._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel saveworld",
                success=False,
                error=type(exc).__name__,
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class SevenDTD(commands.Cog):
    """7 Days to Die WebAPI-Integration für den Discord-Bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = SevenDTDAPI.from_env()
        self._panel_view_registered = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._panel_view_registered:
            return

        self.bot.add_view(
            SevenDTDPanelView(
                self.bot,
                self._dashboard_url(),
            )
        )

        self._panel_view_registered = True

    # ------------------------------------------------------------------ #
    # Permissions
    # ------------------------------------------------------------------ #

    def _is_owner(self, user_id: int) -> bool:
        return OWNER_ID != 0 and user_id == OWNER_ID

    def _is_mod_or_admin(self, interaction: nextcord.Interaction) -> bool:
        if self._is_owner(interaction.user.id):
            return True

        if not isinstance(interaction.user, nextcord.Member):
            return False

        perms = interaction.user.guild_permissions

        if (
            perms.administrator
            or perms.manage_guild
            or perms.manage_messages
            or perms.moderate_members
            or perms.kick_members
            or perms.ban_members
        ):
            return True

        if MOD_ROLE_ID:
            return any(role.id == MOD_ROLE_ID for role in interaction.user.roles)

        return False

    async def _deny(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.send_message(
            "Keine Berechtigung.",
            ephemeral=True,
        )

    async def _log_command_to_db(
        self,
        *,
        interaction: nextcord.Interaction,
        command_name: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        db = getattr(self.bot, "db", None)
        if db is None:
            return

        try:
            await db.log_command(
                guild_id=interaction.guild.id if interaction.guild else None,
                channel_id=interaction.channel.id if interaction.channel else None,
                user_id=interaction.user.id,
                command_name=command_name,
                command_type="slash",
                success=success,
                error=error,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Formatting / Helpers
    # ------------------------------------------------------------------ #

    def _dashboard_url(self) -> str:
        value = os.getenv(
            "SEVENDTD_API_BASE_URL",
            "https://dashboard.hundekuchenlive.de/",
        ).strip()

        return value or "https://dashboard.hundekuchenlive.de/"

    def _base_embed(
        self,
        *,
        title: str,
        description: str | None = None,
        color: int = 0xD94B2B,
    ) -> nextcord.Embed:
        embed = nextcord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )

        if self.bot.user:
            embed.set_footer(
                text="hundekuchenlive Bot • 7 Days to Die",
                icon_url=self.bot.user.display_avatar.url,
            )

        return embed

    @staticmethod
    def _short(value: Any, limit: int = 900) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    @staticmethod
    def _command_first_word(command: str) -> str:
        return command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""

    @staticmethod
    def _format_game_time(stats: Any) -> str:
        if not isinstance(stats, dict):
            return "n/a"

        game_time = stats.get("gameTime")
        if not isinstance(game_time, dict):
            return "n/a"

        days = game_time.get("days", 0)
        hours = game_time.get("hours", 0)
        minutes = game_time.get("minutes", 0)

        return f"Tag {days}, {hours:02}:{minutes:02} Uhr"

    @staticmethod
    def _info_value(info: dict[str, Any], *keys: str, default: str = "n/a") -> str:
        for key in keys:
            value = info.get(key)
            if value is not None and str(value).strip():
                return str(value)
        return default

    @staticmethod
    def _first_env_value(*names: str, default: str = "") -> str:
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return default

    @staticmethod
    def _env_value(name: str, default: str = "n/a") -> str:
        value = os.getenv(name, "").strip()
        return value or default

    def _player_name(self, player: Any) -> str:
        if not isinstance(player, dict):
            return str(player)

        for key in (
            "name",
            "Name",
            "playerName",
            "PlayerName",
            "entityName",
            "EntityName",
            "displayName",
            "DisplayName",
        ):
            value = player.get(key)
            if value:
                return str(value)

        return "Unbekannter Spieler"

    def _player_id(self, player: Any) -> str:
        if not isinstance(player, dict):
            return "-"

        for key in (
            "steamid",
            "SteamID",
            "steamId",
            "SteamId",
            "platformId",
            "PlatformId",
            "entityId",
            "EntityId",
            "id",
            "Id",
        ):
            value = player.get(key)
            if value is not None:
                return str(value)

        return "-"

    def _format_command_result(self, body: Any) -> str:
        data = extract_data(body)

        if isinstance(data, dict):
            for key in ("result", "Result", "output", "Output", "response", "Response"):
                value = data.get(key)
                if value:
                    return self._short(value, 1800)

            return self._short(data, 1800)

        return self._short(data, 1800)

    async def _build_status_embed(self, *, panel_mode: bool = False) -> nextcord.Embed:
        full_status = await self.api.get_full_status()

        info_body = full_status["server_info"]["body"]
        stats_body = full_status["server_stats"]["body"]
        player_body = full_status["players"]["body"]

        info = flatten_key_value_list(info_body)
        stats = extract_data(stats_body)
        player_count = extract_player_count(player_body)

        if not isinstance(stats, dict):
            stats = {}

        server_name = self._info_value(
            info,
            "GameHost",
            "ServerName",
            default="7 Days to Die Server",
        )

        game_type = self._info_value(
            info,
            "GameType",
            default="7DTD",
        )

        game_name = self._info_value(
            info,
            "GameName",
            default=self._env_value("SEVENDTD_SAVE_NAME", "n/a"),
        )

        game_world = self._info_value(
            info,
            "GameWorld",
            "WorldGenSeed",
            "WorldName",
            default=self._env_value("SEVENDTD_WORLD_NAME", "n/a"),
        )

        max_players = self._info_value(
            info,
            "ServerMaxPlayerCount",
            "MaxPlayerCount",
            "MaxPlayers",
            default=self._env_value("SEVENDTD_MAX_PLAYERS", "n/a"),
        )

        server_port = self._info_value(
            info,
            "ServerPort",
            "GamePort",
            "Port",
            default=self._env_value("SEVENDTD_GAME_PORT", "n/a"),
        )

        region = self._info_value(info, "Region", default="n/a")
        language = self._info_value(info, "Language", default="n/a")
        public_host = self._env_value("SEVENDTD_PUBLIC_HOST", "n/a")

        players_online = player_count
        if players_online is None:
            players_online = stats.get("players", 0)

        try:
            players_online_int = int(players_online or 0)
        except (TypeError, ValueError):
            players_online_int = 0

        hostiles = stats.get("hostiles", 0)
        animals = stats.get("animals", 0)
        game_time = self._format_game_time(stats)

        title = (
            "7 Days to Die – Live Panel"
            if panel_mode
            else "7 Days to Die – Serverstatus"
        )

        embed = self._base_embed(
            title=title,
            description="Live-Daten aus der 7DTD-WebAPI.",
            color=0x2ECC71,
        )

        embed.add_field(
            name="Server",
            value=(
                f"Name: `{server_name}`\n"
                f"Game: `{game_type}`\n"
                f"Save: `{game_name}`\n"
                f"Welt: `{game_world}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Live-Status",
            value=(
                f"Spieler: `{players_online_int}/{max_players}`\n"
                f"Spielzeit: `{game_time}`\n"
                f"Hostiles: `{hostiles}`\n"
                f"Animals: `{animals}`"
            ),
            inline=True,
        )

        embed.add_field(
            name="Netzwerk",
            value=(
                f"Adresse: `{public_host}:{server_port}`\n"
                f"Region: `{region}`\n"
                f"Sprache: `{language}`"
            ),
            inline=True,
        )

        if panel_mode:
            embed.add_field(
                name="Aktionen",
                value=(
                    "`Aktualisieren` – Panel neu laden\n"
                    "`Spieler` – aktuelle Spielerliste anzeigen\n"
                    "`Saveworld` – Welt speichern\n"
                    "`Dashboard öffnen` – WebDashboard öffnen"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="API",
                value=(
                    f"`{full_status['server_info']['path']}`\n"
                    f"`{full_status['server_stats']['path']}`\n"
                    f"`{full_status['players']['path']}`"
                ),
                inline=False,
            )

        return embed

    async def _build_players_embed(self) -> nextcord.Embed:
        path, body = await self.api.get_players()
        data = extract_data(body)
        players = extract_list(body)

        embed = self._base_embed(
            title="7 Days to Die – Spieler",
            description=f"Quelle: `{path}`",
            color=0x5865F2,
        )

        if not players:
            embed.add_field(
                name="Spieler online",
                value="Aktuell ist niemand auf dem Server.",
                inline=False,
            )

            if isinstance(data, dict):
                embed.add_field(
                    name="API-Status",
                    value=f"`players`: `{len(data.get('players', []))}`",
                    inline=True,
                )

            return embed

        lines: list[str] = []

        for player in players[:20]:
            name = self._player_name(player)
            pid = self._player_id(player)

            if isinstance(player, dict):
                ping = player.get("ping") or player.get("Ping")
                level = player.get("level") or player.get("Level")
                health = player.get("health") or player.get("Health")

                details = []
                if ping is not None:
                    details.append(f"Ping `{ping}`")
                if level is not None:
                    details.append(f"Level `{level}`")
                if health is not None:
                    details.append(f"HP `{health}`")

                suffix = f" | {', '.join(details)}" if details else ""
                lines.append(f"• `{name}` | ID: `{pid}`{suffix}")
            else:
                lines.append(f"• `{name}`")

        if len(players) > 20:
            lines.append(f"... und `{len(players) - 20}` weitere.")

        embed.add_field(
            name=f"Spieler online ({len(players)})",
            value="\n".join(lines)[:1024],
            inline=False,
        )

        return embed

    # ------------------------------------------------------------------ #
    # /7dtd Gruppe
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="7dtd",
        description="7 Days to Die Server-Tools.",
    )
    async def sevendtd_group(self, interaction: nextcord.Interaction) -> None:
        pass

    # ------------------------------------------------------------------ #
    # /7dtd dashboard
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="dashboard",
        description="Zeigt den Link zum 7DTD-WebDashboard.",
    )
    async def dashboard(self, interaction: nextcord.Interaction) -> None:
        dashboard_url = self._dashboard_url()

        embed = self._base_embed(
            title="7 Days to Die Dashboard",
            description="Öffne das WebDashboard über den Button.",
            color=0x5865F2,
        )
        embed.add_field(
            name="URL",
            value=f"[Dashboard öffnen]({dashboard_url})",
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed,
            view=DashboardView(dashboard_url),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /7dtd panel
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="panel",
        description="Erstellt oder aktualisiert das dauerhafte 7DTD Live-Panel.",
    )
    async def panel(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = SlashOption(
            description="Zielchannel. Ohne Angabe wird SEVENDTD_PANEL_CHANNEL_ID oder der aktuelle Channel genutzt.",
            required=False,
            default=None,
        ),
    ) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            target_channel = channel

            if target_channel is None:
                env_channel_id = self._first_env_value(
                    "SEVENDTD_PANEL_CHANNEL_ID",
                    "GAMESERVER_PANEL_CHANNEL_ID",
                )

                if env_channel_id.isdigit():
                    resolved = self.bot.get_channel(int(env_channel_id))
                    if isinstance(resolved, nextcord.TextChannel):
                        target_channel = resolved

            if target_channel is None:
                if isinstance(interaction.channel, nextcord.TextChannel):
                    target_channel = interaction.channel
                else:
                    await interaction.followup.send(
                        "Kein gültiger Zielchannel gefunden.",
                        ephemeral=True,
                    )
                    return

            embed = await self._build_status_embed(panel_mode=True)
            view = SevenDTDPanelView(self.bot, self._dashboard_url())

            state = load_panel_state()
            old_channel_id = state.get("channel_id")
            old_message_id = state.get("message_id")

            if old_channel_id and old_message_id:
                try:
                    old_channel = self.bot.get_channel(int(old_channel_id))
                    if isinstance(old_channel, nextcord.TextChannel):
                        old_message = await old_channel.fetch_message(
                            int(old_message_id)
                        )
                        await old_message.edit(embed=embed, view=view)

                        state["updated_by"] = interaction.user.id
                        state["updated_at"] = dt.datetime.now(
                            dt.timezone.utc
                        ).isoformat()
                        save_panel_state(state)

                        await interaction.followup.send(
                            f"7DTD Live-Panel aktualisiert: {old_channel.mention}",
                            ephemeral=True,
                        )

                        await self._log_command_to_db(
                            interaction=interaction,
                            command_name="7dtd panel",
                            success=True,
                        )
                        return

                except Exception:
                    pass

            message = await target_channel.send(embed=embed, view=view)

            save_panel_state(
                {
                    "channel_id": target_channel.id,
                    "message_id": message.id,
                    "created_by": interaction.user.id,
                    "updated_by": interaction.user.id,
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )

            await interaction.followup.send(
                f"7DTD Live-Panel erstellt: {target_channel.mention}",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel",
                success=True,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Panel konnte nicht erstellt werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd panel",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd api_probe
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="api_probe",
        description="Testet bekannte 7DTD-WebAPI-Endpunkte ohne Secrets auszugeben.",
    )
    async def api_probe(self, interaction: nextcord.Interaction) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            results = await self.api.probe()

            lines = []
            for item in results:
                lines.append(
                    f"`{item['path']}` → `{item['status']}` "
                    f"body=`{item['body_type']}` data=`{item['data_type']}`"
                )

            embed = self._base_embed(
                title="7DTD API Probe",
                description="\n".join(lines)[:4000] or "Keine Ergebnisse.",
                color=0xF1C40F,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as exc:
            await interaction.followup.send(
                f"API-Probe fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    # ------------------------------------------------------------------ #
    # /7dtd status
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="status",
        description="Zeigt den aktuellen 7DTD-Serverstatus.",
    )
    async def status(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            embed = await self._build_status_embed(panel_mode=False)

            await interaction.followup.send(
                embed=embed,
                view=DashboardView(self._dashboard_url()),
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd status",
                success=True,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Status konnte nicht geladen werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd status",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd players
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="players",
        description="Zeigt die aktuellen Spieler auf dem 7DTD-Server.",
    )
    async def players(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            embed = await self._build_players_embed()

            await interaction.followup.send(embed=embed, ephemeral=True)

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd players",
                success=True,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Spielerliste konnte nicht geladen werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd players",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd save
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="save",
        description="Speichert die 7DTD-Welt über saveworld.",
    )
    async def save(self, interaction: nextcord.Interaction) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            body = await self.api.save_world()
            result = self._format_command_result(body)

            embed = self._base_embed(
                title="7DTD Saveworld",
                description="`saveworld` wurde ausgeführt.",
                color=0x2ECC71,
            )
            embed.add_field(
                name="Antwort",
                value=result[:1024] or "Keine Ausgabe.",
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd save",
                success=True,
            )

        except SevenDTDCommandBlockedError as exc:
            await interaction.followup.send(
                f"Command blockiert: `{exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd save",
                success=False,
                error=type(exc).__name__,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Save fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd save",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd say
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="say",
        description="Sendet eine Servernachricht in den 7DTD-Chat.",
    )
    async def say(
        self,
        interaction: nextcord.Interaction,
        message: str = SlashOption(
            description="Nachricht an den Serverchat.",
            required=True,
        ),
    ) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        try:
            clean_message = self.api.sanitize_chat_message(message, max_length=200)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            body = await self.api.say(clean_message)
            result = self._format_command_result(body)

            embed = self._base_embed(
                title="7DTD Servernachricht",
                description="Nachricht wurde gesendet.",
                color=0x2ECC71,
            )
            embed.add_field(name="Nachricht", value=f"`{clean_message}`", inline=False)
            embed.add_field(
                name="Antwort",
                value=result[:1024] or "Keine Ausgabe.",
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd say",
                success=True,
            )

        except SevenDTDCommandBlockedError as exc:
            await interaction.followup.send(
                f"Command blockiert: `{exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd say",
                success=False,
                error=type(exc).__name__,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Nachricht konnte nicht gesendet werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd say",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd raw
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="raw",
        description="Führt einen sicheren 7DTD-Console-Command aus. Nur Owner.",
    )
    async def raw(
        self,
        interaction: nextcord.Interaction,
        command: str = SlashOption(
            description="Console-Command aus der Allowlist.",
            required=True,
        ),
    ) -> None:
        if not self._is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Nur der Bot-Owner darf Raw-Commands ausführen.",
                ephemeral=True,
            )
            return

        clean_command = command.strip()
        first_word = self._command_first_word(clean_command)

        if not clean_command:
            await interaction.response.send_message(
                "Command darf nicht leer sein.",
                ephemeral=True,
            )
            return

        if first_word in DANGEROUS_RAW_BLOCKLIST:
            await interaction.response.send_message(
                (
                    f"`{first_word}` ist in der Bot-Blocklist.\n"
                    "Führe diesen Befehl direkt im 7DTD-Dashboard aus, wenn du ihn wirklich brauchst."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            body = await self.api.execute_safe_command(clean_command)
            result = self._format_command_result(body)

            embed = self._base_embed(
                title="7DTD Safe Raw Command",
                color=0xF1C40F,
            )
            embed.add_field(
                name="Command",
                value=f"`{clean_command[:900]}`",
                inline=False,
            )
            embed.add_field(
                name="Antwort",
                value=result[:1024] or "Keine Ausgabe.",
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd raw",
                success=True,
            )

        except SevenDTDCommandBlockedError as exc:
            await interaction.followup.send(
                f"Command blockiert: `{exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd raw",
                success=False,
                error=type(exc).__name__,
            )

        except SevenDTDAPIError as exc:
            await interaction.followup.send(
                f"Raw-Command fehlgeschlagen: `{exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd raw",
                success=False,
                error=type(exc).__name__,
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Raw-Command fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_command_to_db(
                interaction=interaction,
                command_name="7dtd raw",
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /7dtd inspect
    # ------------------------------------------------------------------ #

    @sevendtd_group.subcommand(
        name="inspect",
        description="Zeigt eine kompakte Rohdaten-Vorschau eines 7DTD-API-Endpunkts.",
    )
    async def inspect(
        self,
        interaction: nextcord.Interaction,
        endpoint: str = SlashOption(
            description="API-Endpunkt prüfen.",
            choices=["serverinfo", "serverstats", "player"],
            required=True,
        ),
    ) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if endpoint == "serverinfo":
                path, body = await self.api.get_server_info()
            elif endpoint == "serverstats":
                path, body = await self.api.get_server_stats()
            else:
                path, body = await self.api.get_players()

            data = extract_data(body)

            embed = self._base_embed(
                title=f"7DTD Inspect – {endpoint}",
                description=f"Quelle: `{path}`",
                color=0xF1C40F,
            )

            embed.add_field(
                name="Body-Typ",
                value=f"`{type(body).__name__}`",
                inline=True,
            )

            embed.add_field(
                name="Data-Typ",
                value=f"`{type(data).__name__}`",
                inline=True,
            )

            if isinstance(data, dict):
                keys = ", ".join(f"`{key}`" for key in list(data.keys())[:30])
                embed.add_field(
                    name="Keys",
                    value=keys[:1024] if keys else "Keine Keys.",
                    inline=False,
                )
                preview = self._short(data, 1000)

            elif isinstance(data, list):
                embed.add_field(
                    name="Listengröße",
                    value=f"`{len(data)}` Einträge",
                    inline=True,
                )
                preview = self._short(data[:3], 1000)

            else:
                preview = self._short(data, 1000)

            embed.add_field(
                name="Preview",
                value=f"```text\n{preview[:950]}\n```",
                inline=False,
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as exc:
            await interaction.followup.send(
                f"Inspect fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SevenDTD(bot))
