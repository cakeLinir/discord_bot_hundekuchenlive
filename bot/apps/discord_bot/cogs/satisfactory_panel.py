from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import nextcord
from nextcord import SlashOption
from nextcord.ext import commands


# ---------------------------------------------------------------------------
# Zweck
# ---------------------------------------------------------------------------
# Eigenes Satisfactory-Panel.
#
# Kein Sammelpanel für alle Gameserver.
# Dieses Panel kann aber im selben Channel liegen wie:
# - 7DTD Panel
# - LS25 Panel
# - spätere weitere Einzelpanels
#
# Slash-Commands:
# /satisfactory panel
# /satisfactory status
# /satisfactory save
# /satisfactory reload
#
# Legacy Prefix:
# !satis_panel
#
# .env relevante Keys:
# GAMESERVER_PANEL_CHANNEL_ID=
# GAMESERVER_LOG_CHANNEL_ID=
#
# SATIS_PANEL_CHANNEL_ID=          optionaler Override
# SATIS_LOG_CHANNEL_ID=            optionaler Override
# SATIS_API_URL=https://IP:7777/api/v1/
# SATIS_API_TOKEN=
# SATIS_DASHBOARD_URL=             optional
# SATIS_BANNER_URL=                optional
# SATIS_HOST=46.225.14.84          optional
# SATIS_PORT=7777                  optional


# ---------------------------------------------------------------------------
# Pfade / Dateien
# ---------------------------------------------------------------------------

BOT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = BOT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "satisfactory_panel_state.json"


# ---------------------------------------------------------------------------
# Defaults / Env
# ---------------------------------------------------------------------------

DEFAULT_HOST = os.getenv("SATIS_HOST", os.getenv("GAMESERVER_HOST", "46.225.14.84")).strip() or "46.225.14.84"
DEFAULT_PORT = 7777

SATIS_ICON_URL = "https://satisfactory.wiki.gg/images/3/3f/Satisfactory_Logo.png"
DEFAULT_PANEL_TITLE = "Satisfactory – Live Panel"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def env_int(*names: str, default: int = 0) -> int:
    for name in names:
        value = os.getenv(name, "").strip()
        if value.isdigit():
            return int(value)
    return default


def env_str(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def status_channel_id() -> int:
    return env_int(
        "SATIS_PANEL_CHANNEL_ID",
        "GAMESERVER_PANEL_CHANNEL_ID",
        "GAMESERVER_STATUS_CHANNEL_ID",
        default=1476220645971984416,
    )


def log_channel_id() -> int:
    return env_int(
        "SATIS_LOG_CHANNEL_ID",
        "GAMESERVER_LOG_CHANNEL_ID",
        default=1442466604645617704,
    )


def satis_port() -> int:
    return env_int("SATIS_PORT", default=DEFAULT_PORT) or DEFAULT_PORT


def satis_api_url() -> str:
    configured = os.getenv("SATIS_API_URL", "").strip()
    if configured:
        return configured.rstrip("/") + "/"

    return f"https://{DEFAULT_HOST}:{satis_port()}/api/v1/"


def satis_token() -> str:
    return os.getenv("SATIS_API_TOKEN", "").strip()


def satis_dashboard_url() -> str | None:
    url = env_str("SATIS_DASHBOARD_URL", default="")
    return safe_url(url)


def satis_banner_url() -> str | None:
    url = env_str("SATIS_BANNER_URL", default="")
    return safe_url(url)


# ---------------------------------------------------------------------------
# JSON State
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(data: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SatisfactoryStatus:
    state: str
    game_server_name: str
    players: str
    uptime: str
    latency_ms: int | None
    details: str
    checked_at: dt.datetime


# ---------------------------------------------------------------------------
# Format Helper
# ---------------------------------------------------------------------------

def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fmt_ts(value: dt.datetime | None = None) -> str:
    return (value or now_utc()).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return "n/a"

    try:
        return str(dt.timedelta(seconds=int(seconds)))
    except Exception:
        return "n/a"


def state_icon(state: str) -> str:
    if state == "online":
        return "🟢"
    if state == "slow":
        return "🟡"
    if state == "disabled":
        return "⚪"
    return "🔴"


def state_color(state: str) -> int:
    if state == "online":
        return 0x2ECC71
    if state == "slow":
        return 0xF1C40F
    if state == "disabled":
        return 0x95A5A6
    return 0xE74C3C


def normalize_satisfactory_health(value: str | None) -> str:
    raw = str(value or "").lower().strip()

    if raw in {"healthy", "online", "ok", "running"}:
        return "online"

    if raw == "slow":
        return "slow"

    if raw in {"offline", "error", "failed"}:
        return "offline"

    if "slow" in raw:
        return "slow"

    if "error" in raw or "fehler" in raw or "offline" in raw:
        return "offline"

    return "online" if raw else "offline"


def safe_url(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    return url


# ---------------------------------------------------------------------------
# Satisfactory API Client
# ---------------------------------------------------------------------------

async def satisfactory_call(
    *,
    function: str,
    data: dict[str, Any],
    token: str | None = None,
    timeout_seconds: int = 8,
) -> tuple[int, dict[str, Any]]:
    payload = {
        "function": function,
        "data": data,
    }

    headers = {
        "Content-Type": "application/json",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.post(satis_api_url(), json=payload, ssl=False) as response:
            if response.status in {202, 204}:
                return response.status, {}

            try:
                body = await response.json(content_type=None)
            except Exception:
                body = {"raw": await response.text()}

            return response.status, body if isinstance(body, dict) else {"raw": body}


async def fetch_satisfactory_status() -> SatisfactoryStatus:
    checked_at = now_utc()
    token = satis_token()

    game_server_name = "Satisfactory Dedicated Server"
    players = "n/a"
    uptime = "n/a"

    # Authentifizierte Abfrage bevorzugen.
    if token:
        start = now_utc()

        try:
            http_status, body = await satisfactory_call(
                function="QueryServerState",
                data={},
                token=token,
                timeout_seconds=8,
            )

            latency_ms = int((now_utc() - start).total_seconds() * 1000)

            data = body.get("data", {})
            server_game_state = data.get("serverGameState") or data.get("ServerGameState")

            if http_status == 200 and isinstance(server_game_state, dict):
                sg = server_game_state

                game_server_name = (
                    sg.get("activeSessionName")
                    or sg.get("ActiveSessionName")
                    or game_server_name
                )

                num_players = sg.get("numConnectedPlayers", sg.get("NumConnectedPlayers"))
                player_limit = sg.get("playerLimit", sg.get("PlayerLimit"))

                if num_players is not None and player_limit is not None:
                    players = f"{num_players}/{player_limit}"
                elif num_players is not None:
                    players = str(num_players)

                uptime = fmt_seconds(
                    sg.get("totalGameDuration", sg.get("TotalGameDuration"))
                )

                is_running = sg.get("isGameRunning", sg.get("IsGameRunning", True))
                avg_tick = sg.get("averageTickRate", sg.get("AverageTickRate"))

                if is_running is False:
                    return SatisfactoryStatus(
                        state="offline",
                        game_server_name=str(game_server_name),
                        players=players,
                        uptime=uptime,
                        latency_ms=latency_ms,
                        details="Save nicht geladen / Server wartet",
                        checked_at=checked_at,
                    )

                if isinstance(avg_tick, (int, float)) and avg_tick < 10:
                    return SatisfactoryStatus(
                        state="slow",
                        game_server_name=str(game_server_name),
                        players=players,
                        uptime=uptime,
                        latency_ms=latency_ms,
                        details=f"Tickrate: {avg_tick:.1f}",
                        checked_at=checked_at,
                    )

                return SatisfactoryStatus(
                    state="online",
                    game_server_name=str(game_server_name),
                    players=players,
                    uptime=uptime,
                    latency_ms=latency_ms,
                    details=f"QueryServerState HTTP {http_status}",
                    checked_at=checked_at,
                )

        except Exception:
            # Fallback auf HealthCheck.
            pass

    # Öffentlicher Fallback.
    start = now_utc()

    try:
        http_status, body = await satisfactory_call(
            function="HealthCheck",
            data={"ClientCustomData": ""},
            token=None,
            timeout_seconds=8,
        )

        latency_ms = int((now_utc() - start).total_seconds() * 1000)

        data = body.get("data", {})
        health = data.get("health") or data.get("Health")
        state = normalize_satisfactory_health(health)

        if http_status != 200:
            state = "offline"

        return SatisfactoryStatus(
            state=state,
            game_server_name=game_server_name,
            players=players,
            uptime=uptime,
            latency_ms=latency_ms,
            details=f"HealthCheck: {health or 'unknown'} | HTTP {http_status}",
            checked_at=checked_at,
        )

    except Exception as exc:
        return SatisfactoryStatus(
            state="offline",
            game_server_name=game_server_name,
            players=players,
            uptime=uptime,
            latency_ms=None,
            details=f"{type(exc).__name__}: {exc}",
            checked_at=checked_at,
        )


async def save_satisfactory_game(save_name: str) -> tuple[int, dict[str, Any]]:
    token = satis_token()
    if not token:
        raise RuntimeError("SATIS_API_TOKEN fehlt in .env")

    # Alte Implementierung nutzte saveName. Das bleibt der Primärweg.
    http_status, body = await satisfactory_call(
        function="SaveGame",
        data={"saveName": save_name},
        token=token,
        timeout_seconds=12,
    )

    if http_status in {200, 202, 204} and not body.get("errorCode"):
        return http_status, body

    # Fallback für abweichende API-Cases.
    if http_status in {400, 422}:
        return await satisfactory_call(
            function="SaveGame",
            data={"SaveName": save_name},
            token=token,
            timeout_seconds=12,
        )

    return http_status, body


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------

def build_status_embed(status: SatisfactoryStatus, *, panel_mode: bool = False) -> nextcord.Embed:
    title = "Satisfactory – Live Panel" if panel_mode else "Satisfactory – Status"
    latency = f"{status.latency_ms} ms" if status.latency_ms is not None else "n/a"

    embed = nextcord.Embed(
        title=title,
        description="Eigenes Panel für deinen Satisfactory Dedicated Server.",
        color=state_color(status.state),
        timestamp=now_utc(),
    )

    banner_url = satis_banner_url()
    if banner_url:
        embed.set_image(url=banner_url)

    embed.set_thumbnail(url=SATIS_ICON_URL)

    embed.add_field(
        name="Status",
        value=f"`{state_icon(status.state)} {status.state}`",
        inline=True,
    )
    embed.add_field(name="Latenz", value=f"`{latency}`", inline=True)
    embed.add_field(name="Spieler", value=f"`{status.players}`", inline=True)

    embed.add_field(
        name="Server",
        value=(
            f"Name: `{status.game_server_name}`\n"
            f"Host: `{DEFAULT_HOST}:{satis_port()}`\n"
            f"Laufzeit: `{status.uptime}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Details",
        value=f"`{status.details[:900] or 'n/a'}`",
        inline=False,
    )

    if panel_mode:
        embed.add_field(
            name="Aktionen",
            value=(
                "`Aktualisieren` – Panel neu laden\n"
                "`SaveGame` – manuellen Save starten\n"
                "`Dashboard öffnen` – optionaler externer Link"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Geprüft: {fmt_ts(status.checked_at)}")
    return embed


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class SatisfactoryPanelView(nextcord.ui.View):
    """Persistente Buttons für das Satisfactory-Panel."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        dashboard_url = satis_dashboard_url()
        if dashboard_url:
            self.add_item(
                nextcord.ui.Button(
                    label="Dashboard öffnen",
                    url=dashboard_url,
                    style=nextcord.ButtonStyle.link,
                )
            )

    def _cog(self) -> "SatisfactoryPanel | None":
        cog = self.bot.get_cog("SatisfactoryPanel")
        return cog if isinstance(cog, SatisfactoryPanel) else None

    @nextcord.ui.button(
        label="Aktualisieren",
        style=nextcord.ButtonStyle.primary,
        custom_id="satis_panel:refresh",
    )
    async def btn_refresh(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.message is None:
            await interaction.followup.send("Panel-Nachricht nicht gefunden.", ephemeral=True)
            return

        try:
            status = await fetch_satisfactory_status()
            embed = build_status_embed(status, panel_mode=True)

            await interaction.message.edit(embed=embed, view=self)

            await interaction.followup.send(
                f"Satisfactory Panel aktualisiert: `{status.state}`",
                ephemeral=True,
            )

            cog = self._cog()
            if cog:
                await cog._log_safe(
                    f"[SATIS][REFRESH] user_id={interaction.user.id} state={status.state}"
                )

        except Exception as exc:
            await interaction.followup.send(
                f"Aktualisierung fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    @nextcord.ui.button(
        label="SaveGame",
        style=nextcord.ButtonStyle.success,
        custom_id="satis_panel:save",
    )
    async def btn_save(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        cog = self._cog()
        if cog is None:
            await interaction.response.send_message("Satisfactory-Cog nicht geladen.", ephemeral=True)
            return

        if not cog._is_admin(interaction):
            await cog._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        save_name = f"discord-panel-{now_utc().strftime('%Y%m%d-%H%M%S')}"

        try:
            http_status, body = await save_satisfactory_game(save_name)
            ok = http_status in {200, 202, 204} and not body.get("errorCode")

            if not ok:
                error_message = body.get("errorMessage") or body.get("raw") or body
                await interaction.followup.send(
                    f"Save fehlgeschlagen. HTTP `{http_status}`\n`{str(error_message)[:1500]}`",
                    ephemeral=True,
                )
                await cog._log_safe(
                    f"[SATIS][SAVE_FAIL] user_id={interaction.user.id} http={http_status} body={body}"
                )
                return

            await interaction.followup.send(
                f"Save gestartet.\nSaveName: `{save_name}`\nHTTP: `{http_status}`",
                ephemeral=True,
            )

            await cog._log_safe(
                f"[SATIS][SAVE] user_id={interaction.user.id} saveName={save_name} http={http_status}"
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Save fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await cog._log_safe(
                f"[SATIS][SAVE_EXCEPTION] user_id={interaction.user.id} error={type(exc).__name__}: {exc}"
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class SatisfactoryPanel(commands.Cog):
    """Eigenes Satisfactory-Panel für Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view_registered = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._view_registered:
            return

        self.bot.add_view(SatisfactoryPanelView(self.bot))
        self._view_registered = True

    # ------------------------------------------------------------------ #
    # Permissions / Logging
    # ------------------------------------------------------------------ #

    def _is_admin(self, interaction: nextcord.Interaction) -> bool:
        if not isinstance(interaction.user, nextcord.Member):
            return False

        return bool(
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_guild
        )

    async def _deny(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.send_message(
            "Du brauchst **Server verwalten** oder Administratorrechte.",
            ephemeral=True,
        )

    async def _log_safe(self, text: str) -> None:
        channel = self.bot.get_channel(log_channel_id())
        if not isinstance(channel, nextcord.TextChannel):
            return

        try:
            await channel.send(text[:1900])
        except Exception:
            pass

    async def _resolve_target_channel(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None,
    ) -> nextcord.TextChannel | None:
        if channel is not None:
            return channel

        resolved = self.bot.get_channel(status_channel_id())
        if isinstance(resolved, nextcord.TextChannel):
            return resolved

        if isinstance(interaction.channel, nextcord.TextChannel):
            return interaction.channel

        return None

    # ------------------------------------------------------------------ #
    # Legacy Prefix
    # ------------------------------------------------------------------ #

    @commands.has_permissions(administrator=True)
    @commands.command(name="satis_panel")
    async def satis_panel_prefix(self, ctx: commands.Context) -> None:
        target_channel = self.bot.get_channel(status_channel_id())

        if not isinstance(target_channel, nextcord.TextChannel):
            await ctx.send("Satisfactory-Panel-Channel nicht gefunden.")
            return

        status = await fetch_satisfactory_status()
        embed = build_status_embed(status, panel_mode=True)
        view = SatisfactoryPanelView(self.bot)

        state = load_state()
        old_message_id = state.get("panel_message_id")
        old_channel_id = state.get("panel_channel_id")

        if old_message_id and old_channel_id:
            try:
                old_channel = self.bot.get_channel(int(old_channel_id))
                if isinstance(old_channel, nextcord.TextChannel):
                    old_message = await old_channel.fetch_message(int(old_message_id))
                    await old_message.edit(embed=embed, view=view)
                    await ctx.send("Satisfactory Panel aktualisiert.", delete_after=5)
                    return
            except Exception:
                pass

        message = await target_channel.send(embed=embed, view=view)

        save_state(
            {
                "panel_channel_id": target_channel.id,
                "panel_message_id": message.id,
                "updated_at": now_utc().isoformat(),
            }
        )

        await ctx.send("Satisfactory Panel erstellt.", delete_after=5)

    # ------------------------------------------------------------------ #
    # /satisfactory Gruppe
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="satisfactory",
        description="Satisfactory Server-Panel verwalten.",
    )
    async def satisfactory_group(self, interaction: nextcord.Interaction) -> None:
        pass

    # ------------------------------------------------------------------ #
    # /satisfactory panel
    # ------------------------------------------------------------------ #

    @satisfactory_group.subcommand(
        name="panel",
        description="Erstellt oder aktualisiert das Satisfactory Live-Panel.",
    )
    async def satisfactory_panel(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = SlashOption(
            description="Zielchannel. Ohne Angabe wird SATIS_PANEL_CHANNEL_ID oder GAMESERVER_PANEL_CHANNEL_ID genutzt.",
            required=False,
            default=None,
        ),
    ) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        target_channel = await self._resolve_target_channel(interaction, channel)
        if target_channel is None:
            await interaction.followup.send(
                "Kein gültiger Zielchannel gefunden.",
                ephemeral=True,
            )
            return

        try:
            status = await fetch_satisfactory_status()
            embed = build_status_embed(status, panel_mode=True)
            view = SatisfactoryPanelView(self.bot)

            state = load_state()
            old_message_id = state.get("panel_message_id")
            old_channel_id = state.get("panel_channel_id")

            if old_message_id and old_channel_id:
                try:
                    old_channel = self.bot.get_channel(int(old_channel_id))
                    if isinstance(old_channel, nextcord.TextChannel):
                        old_message = await old_channel.fetch_message(int(old_message_id))
                        await old_message.edit(embed=embed, view=view)

                        state["updated_by"] = interaction.user.id
                        state["updated_at"] = now_utc().isoformat()
                        save_state(state)

                        await interaction.followup.send(
                            f"Satisfactory Panel aktualisiert: {old_channel.mention}",
                            ephemeral=True,
                        )

                        await self._log_safe(
                            f"[SATIS][PANEL_UPDATE] user_id={interaction.user.id} channel_id={old_channel.id}"
                        )
                        return

                except Exception:
                    pass

            message = await target_channel.send(embed=embed, view=view)

            save_state(
                {
                    "panel_channel_id": target_channel.id,
                    "panel_message_id": message.id,
                    "created_by": interaction.user.id,
                    "updated_by": interaction.user.id,
                    "updated_at": now_utc().isoformat(),
                }
            )

            await interaction.followup.send(
                f"Satisfactory Panel erstellt: {target_channel.mention}\nMessage-ID: `{message.id}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[SATIS][PANEL_CREATE] user_id={interaction.user.id} channel_id={target_channel.id} message_id={message.id}"
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Panel konnte nicht erstellt werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[SATIS][PANEL_ERROR] user_id={interaction.user.id} error={type(exc).__name__}: {exc}"
            )

    # ------------------------------------------------------------------ #
    # /satisfactory status
    # ------------------------------------------------------------------ #

    @satisfactory_group.subcommand(
        name="status",
        description="Zeigt den aktuellen Satisfactory-Serverstatus.",
    )
    async def satisfactory_status(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            status = await fetch_satisfactory_status()
            embed = build_status_embed(status, panel_mode=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as exc:
            await interaction.followup.send(
                f"Status konnte nicht geladen werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    # ------------------------------------------------------------------ #
    # /satisfactory save
    # ------------------------------------------------------------------ #

    @satisfactory_group.subcommand(
        name="save",
        description="Startet einen manuellen Satisfactory-Save.",
    )
    async def satisfactory_save(
        self,
        interaction: nextcord.Interaction,
        save_name: str | None = SlashOption(
            description="Optionaler SaveName. Ohne Angabe wird automatisch einer erzeugt.",
            required=False,
            default=None,
        ),
    ) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return

        token = satis_token()
        if not token:
            await interaction.response.send_message(
                "SATIS_API_TOKEN fehlt in `.env`.",
                ephemeral=True,
            )
            return

        final_save_name = (
            save_name.strip()
            if save_name and save_name.strip()
            else f"discord-manual-{now_utc().strftime('%Y%m%d-%H%M%S')}"
        )

        await interaction.response.defer(ephemeral=True)

        try:
            http_status, body = await save_satisfactory_game(final_save_name)
            ok = http_status in {200, 202, 204} and not body.get("errorCode")

            if not ok:
                error_message = body.get("errorMessage") or body.get("raw") or body
                await interaction.followup.send(
                    f"Save fehlgeschlagen. HTTP `{http_status}`\n`{str(error_message)[:1500]}`",
                    ephemeral=True,
                )

                await self._log_safe(
                    f"[SATIS][SAVE_FAIL] user_id={interaction.user.id} http={http_status} body={body}"
                )
                return

            await interaction.followup.send(
                f"Save gestartet.\nSaveName: `{final_save_name}`\nHTTP: `{http_status}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[SATIS][SAVE] user_id={interaction.user.id} saveName={final_save_name} http={http_status}"
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Save fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[SATIS][SAVE_EXCEPTION] user_id={interaction.user.id} error={type(exc).__name__}: {exc}"
            )

    # ------------------------------------------------------------------ #
    # /satisfactory reload
    # ------------------------------------------------------------------ #

    @satisfactory_group.subcommand(
        name="reload",
        description="Zeigt die aktuell geladene Satisfactory-Konfiguration.",
    )
    async def satisfactory_reload(self, interaction: nextcord.Interaction) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return

        embed = nextcord.Embed(
            title="Satisfactory Konfiguration",
            color=0x5865F2,
            timestamp=now_utc(),
        )

        embed.add_field(name="API URL", value=f"`{satis_api_url()}`", inline=False)
        embed.add_field(name="Host", value=f"`{DEFAULT_HOST}`", inline=True)
        embed.add_field(name="Port", value=f"`{satis_port()}`", inline=True)
        embed.add_field(name="Panel Channel", value=f"`{status_channel_id()}`", inline=True)
        embed.add_field(name="Log Channel", value=f"`{log_channel_id()}`", inline=True)
        embed.add_field(name="Token gesetzt", value=f"`{bool(satis_token())}`", inline=True)
        embed.add_field(name="Dashboard URL", value=f"`{satis_dashboard_url() or 'n/a'}`", inline=False)
        embed.add_field(name="State File", value=f"`{STATE_FILE}`", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SatisfactoryPanel(bot))