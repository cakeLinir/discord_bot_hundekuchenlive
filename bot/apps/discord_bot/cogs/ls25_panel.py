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
# Eigenes LS25/Farming Simulator 25 Panel.
#
# Der Server muss noch nicht installiert sein.
# Das Panel kann bereits im gemeinsamen Gameserver-Channel liegen.
#
# Slash-Commands:
# /ls25 panel
# /ls25 status
# /ls25 reload
#
# .env relevante Keys:
# GAMESERVER_PANEL_CHANNEL_ID=
# GAMESERVER_LOG_CHANNEL_ID=
#
# LS25_ENABLED=false
# LS25_PANEL_CHANNEL_ID=
# LS25_LOG_CHANNEL_ID=
# LS25_HOST=46.225.14.84
# LS25_GAME_PORT=10823
# LS25_WEB_HTTP_PORT=8080
# LS25_WEB_HTTPS_PORT=8443
# LS25_DASHBOARD_URL=
# LS25_HEALTH_URL=
# LS25_SERVER_NAME=hundekuchenlive | LS25
# LS25_MAX_PLAYERS=16


# ---------------------------------------------------------------------------
# Pfade / State
# ---------------------------------------------------------------------------

BOT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = BOT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "ls25_panel_state.json"


# ---------------------------------------------------------------------------
# Env Helper
# ---------------------------------------------------------------------------

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


def ls25_enabled() -> bool:
    return env_bool("LS25_ENABLED", False)


def ls25_host() -> str:
    return env_str("LS25_HOST", "GAMESERVER_HOST", default="46.225.14.84")


def ls25_game_port() -> int:
    return env_int("LS25_GAME_PORT", default=10823) or 10823


def ls25_web_http_port() -> int:
    return env_int("LS25_WEB_HTTP_PORT", default=8080) or 8080


def ls25_web_https_port() -> int:
    return env_int("LS25_WEB_HTTPS_PORT", default=8443) or 8443


def ls25_server_name() -> str:
    return env_str("LS25_SERVER_NAME", default="hundekuchenlive | LS25")


def ls25_max_players() -> str:
    return env_str("LS25_MAX_PLAYERS", default="16")


def ls25_dashboard_url() -> str | None:
    url = env_str("LS25_DASHBOARD_URL", default="")
    return safe_url(url)


def ls25_health_url() -> str | None:
    url = env_str("LS25_HEALTH_URL", default="")
    return safe_url(url)


def status_channel_id() -> int:
    return env_int(
        "LS25_PANEL_CHANNEL_ID",
        "GAMESERVER_PANEL_CHANNEL_ID",
        "GAMESERVER_STATUS_CHANNEL_ID",
        default=0,
    )


def log_channel_id() -> int:
    return env_int(
        "LS25_LOG_CHANNEL_ID",
        "GAMESERVER_LOG_CHANNEL_ID",
        default=0,
    )


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
# Data
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LS25Status:
    state: str
    server_name: str
    players: str
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


def state_icon(state: str) -> str:
    if state == "online":
        return "🟢"
    if state == "planned":
        return "🟣"
    if state == "disabled":
        return "⚪"
    if state == "partial":
        return "🟡"
    return "🔴"


def state_color(state: str) -> int:
    if state == "online":
        return 0x2ECC71
    if state == "planned":
        return 0x9B59B6
    if state == "disabled":
        return 0x95A5A6
    if state == "partial":
        return 0xF1C40F
    return 0xE74C3C


def safe_url(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    return url


# ---------------------------------------------------------------------------
# Network Checks
# ---------------------------------------------------------------------------

async def check_tcp(host: str, port: int, *, timeout_seconds: int = 4) -> tuple[bool, int | None, str]:
    start = now_utc()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_seconds,
        )

        writer.close()
        await writer.wait_closed()

        elapsed_ms = int((now_utc() - start).total_seconds() * 1000)
        return True, elapsed_ms, "TCP-Port erreichbar"

    except asyncio.TimeoutError:
        return False, None, "TCP Timeout"

    except OSError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


async def check_http(url: str, *, timeout_seconds: int = 5) -> tuple[bool, int | None, str]:
    start = now_utc()
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, ssl=False) as response:
                elapsed_ms = int((now_utc() - start).total_seconds() * 1000)
                ok = 200 <= response.status < 500
                return ok, elapsed_ms, f"HTTP {response.status}"

    except asyncio.TimeoutError:
        return False, None, "HTTP Timeout"

    except aiohttp.ClientError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


async def fetch_ls25_status() -> LS25Status:
    checked_at = now_utc()

    if not ls25_enabled():
        return LS25Status(
            state="planned",
            server_name=ls25_server_name(),
            players=f"0/{ls25_max_players()}",
            latency_ms=None,
            details="LS25 ist vorbereitet, aber noch nicht aktiviert. Setze LS25_ENABLED=true, sobald der Server läuft.",
            checked_at=checked_at,
        )

    # 1. Health URL bevorzugen, falls später ein interner Proxy/Webcheck existiert.
    health_url = ls25_health_url()
    if health_url:
        ok, latency_ms, details = await check_http(health_url)
        return LS25Status(
            state="online" if ok else "offline",
            server_name=ls25_server_name(),
            players=f"n/a/{ls25_max_players()}",
            latency_ms=latency_ms,
            details=f"Health URL: {details}",
            checked_at=checked_at,
        )

    # 2. Dashboard URL prüfen, falls gesetzt.
    dashboard_url = ls25_dashboard_url()
    if dashboard_url:
        ok, latency_ms, details = await check_http(dashboard_url)
        return LS25Status(
            state="online" if ok else "offline",
            server_name=ls25_server_name(),
            players=f"n/a/{ls25_max_players()}",
            latency_ms=latency_ms,
            details=f"Dashboard: {details}",
            checked_at=checked_at,
        )

    # 3. Fallback: Webinterface TCP-Port prüfen.
    # Achtung: Game-Port bei LS25 ist typischerweise UDP; TCP-Check ist dafür nicht geeignet.
    # Daher prüfen wir bevorzugt HTTPS 8443 und dann HTTP 8080.
    host = ls25_host()

    https_ok, https_latency, https_details = await check_tcp(host, ls25_web_https_port())
    if https_ok:
        return LS25Status(
            state="online",
            server_name=ls25_server_name(),
            players=f"n/a/{ls25_max_players()}",
            latency_ms=https_latency,
            details=f"Web HTTPS {ls25_web_https_port()}: {https_details}",
            checked_at=checked_at,
        )

    http_ok, http_latency, http_details = await check_tcp(host, ls25_web_http_port())
    if http_ok:
        return LS25Status(
            state="partial",
            server_name=ls25_server_name(),
            players=f"n/a/{ls25_max_players()}",
            latency_ms=http_latency,
            details=f"Web HTTP {ls25_web_http_port()}: {http_details}",
            checked_at=checked_at,
        )

    return LS25Status(
        state="offline",
        server_name=ls25_server_name(),
        players=f"n/a/{ls25_max_players()}",
        latency_ms=None,
        details=(
            f"Kein LS25-Webinterface erreichbar. "
            f"HTTPS {ls25_web_https_port()}: {https_details}; "
            f"HTTP {ls25_web_http_port()}: {http_details}"
        ),
        checked_at=checked_at,
    )


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------

def build_status_embed(status: LS25Status, *, panel_mode: bool = False) -> nextcord.Embed:
    title = "LS25 – Live Panel" if panel_mode else "LS25 – Status"
    latency = f"{status.latency_ms} ms" if status.latency_ms is not None else "n/a"

    embed = nextcord.Embed(
        title=title,
        description="Eigenes Panel für Farming Simulator 25. Server ist vorbereitet und später aktivierbar.",
        color=state_color(status.state),
        timestamp=now_utc(),
    )

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
            f"Name: `{status.server_name}`\n"
            f"Host: `{ls25_host()}`\n"
            f"Game-Port: `{ls25_game_port()}`\n"
            f"Web HTTP: `{ls25_web_http_port()}`\n"
            f"Web HTTPS: `{ls25_web_https_port()}`"
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
                "`Webinterface öffnen` – Link, sobald LS25_DASHBOARD_URL gesetzt ist"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Geprüft: {fmt_ts(status.checked_at)}")
    return embed


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class LS25PanelView(nextcord.ui.View):
    """Persistente Buttons für das LS25-Panel."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        dashboard_url = ls25_dashboard_url()
        if dashboard_url:
            self.add_item(
                nextcord.ui.Button(
                    label="Webinterface öffnen",
                    url=dashboard_url,
                    style=nextcord.ButtonStyle.link,
                )
            )

    def _cog(self) -> "LS25Panel | None":
        cog = self.bot.get_cog("LS25Panel")
        return cog if isinstance(cog, LS25Panel) else None

    @nextcord.ui.button(
        label="Aktualisieren",
        style=nextcord.ButtonStyle.primary,
        custom_id="ls25_panel:refresh",
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
            status = await fetch_ls25_status()
            embed = build_status_embed(status, panel_mode=True)

            await interaction.message.edit(embed=embed, view=self)

            await interaction.followup.send(
                f"LS25 Panel aktualisiert: `{status.state}`",
                ephemeral=True,
            )

            cog = self._cog()
            if cog:
                await cog._log_safe(
                    f"[LS25][REFRESH] user_id={interaction.user.id} state={status.state}"
                )

        except Exception as exc:
            await interaction.followup.send(
                f"Aktualisierung fehlgeschlagen: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class LS25Panel(commands.Cog):
    """Eigenes LS25/Farming Simulator 25 Panel für Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view_registered = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._view_registered:
            return

        self.bot.add_view(LS25PanelView(self.bot))
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
        channel_id = log_channel_id()
        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
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
    # /ls25 Gruppe
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="ls25",
        description="LS25 / Farming Simulator 25 Server-Panel verwalten.",
    )
    async def ls25_group(self, interaction: nextcord.Interaction) -> None:
        pass

    # ------------------------------------------------------------------ #
    # /ls25 panel
    # ------------------------------------------------------------------ #

    @ls25_group.subcommand(
        name="panel",
        description="Erstellt oder aktualisiert das LS25 Live-Panel.",
    )
    async def ls25_panel(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = SlashOption(
            description="Zielchannel. Ohne Angabe wird LS25_PANEL_CHANNEL_ID oder GAMESERVER_PANEL_CHANNEL_ID genutzt.",
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
            status = await fetch_ls25_status()
            embed = build_status_embed(status, panel_mode=True)
            view = LS25PanelView(self.bot)

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
                            f"LS25 Panel aktualisiert: {old_channel.mention}",
                            ephemeral=True,
                        )

                        await self._log_safe(
                            f"[LS25][PANEL_UPDATE] user_id={interaction.user.id} channel_id={old_channel.id}"
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
                f"LS25 Panel erstellt: {target_channel.mention}\nMessage-ID: `{message.id}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[LS25][PANEL_CREATE] user_id={interaction.user.id} channel_id={target_channel.id} message_id={message.id}"
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Panel konnte nicht erstellt werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

            await self._log_safe(
                f"[LS25][PANEL_ERROR] user_id={interaction.user.id} error={type(exc).__name__}: {exc}"
            )

    # ------------------------------------------------------------------ #
    # /ls25 status
    # ------------------------------------------------------------------ #

    @ls25_group.subcommand(
        name="status",
        description="Zeigt den aktuellen LS25-Serverstatus.",
    )
    async def ls25_status(self, interaction: nextcord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            status = await fetch_ls25_status()
            embed = build_status_embed(status, panel_mode=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as exc:
            await interaction.followup.send(
                f"Status konnte nicht geladen werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    # ------------------------------------------------------------------ #
    # /ls25 reload
    # ------------------------------------------------------------------ #

    @ls25_group.subcommand(
        name="reload",
        description="Zeigt die aktuell geladene LS25-Konfiguration.",
    )
    async def ls25_reload(self, interaction: nextcord.Interaction) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return

        embed = nextcord.Embed(
            title="LS25 Konfiguration",
            color=0x5865F2,
            timestamp=now_utc(),
        )

        embed.add_field(name="Enabled", value=f"`{ls25_enabled()}`", inline=True)
        embed.add_field(name="Host", value=f"`{ls25_host()}`", inline=True)
        embed.add_field(name="Game-Port", value=f"`{ls25_game_port()}`", inline=True)
        embed.add_field(name="Web HTTP", value=f"`{ls25_web_http_port()}`", inline=True)
        embed.add_field(name="Web HTTPS", value=f"`{ls25_web_https_port()}`", inline=True)
        embed.add_field(name="Max Players", value=f"`{ls25_max_players()}`", inline=True)
        embed.add_field(name="Panel Channel", value=f"`{status_channel_id() or 'n/a'}`", inline=True)
        embed.add_field(name="Log Channel", value=f"`{log_channel_id() or 'n/a'}`", inline=True)
        embed.add_field(name="Dashboard URL", value=f"`{ls25_dashboard_url() or 'n/a'}`", inline=False)
        embed.add_field(name="Health URL", value=f"`{ls25_health_url() or 'n/a'}`", inline=False)
        embed.add_field(name="State File", value=f"`{STATE_FILE}`", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(LS25Panel(bot))