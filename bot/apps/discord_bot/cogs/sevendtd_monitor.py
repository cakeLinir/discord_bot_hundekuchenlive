from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin

import aiohttp
import nextcord
from nextcord.ext import commands


TokenKind = Literal["read", "admin", "log"]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    if not value.isdigit():
        return default
    return int(value)


OWNER_ID = _env_int("BOT_OWNER_ID", 0)
MOD_ROLE_ID = _env_int("MOD_ROLE_ID", 0)


@dataclass(slots=True)
class ClassifiedLogEvent:
    category: str
    title: str
    description: str
    color: int
    important: bool = False


class SevenDTDLogMonitor(commands.Cog):
    """
    7DTD Log-/Event-Monitor.

    Liest den WebDashboard/SSE-Logstream und sendet nur relevante,
    gefilterte Events in einen Discord-Channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        self.connected = False
        self.current_endpoint: str | None = None
        self.last_error: str | None = None
        self.last_event_at: dt.datetime | None = None
        self.last_event_text: str | None = None
        self.total_events_sent = 0
        self.total_lines_seen = 0

        self._recent_hashes: dict[str, float] = {}
        self._event_timestamps: deque[float] = deque(maxlen=120)

    # ------------------------------------------------------------------ #
    # Cog lifecycle
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._task is not None and not self._task.done():
            return

        if not _env_bool("SEVENDTD_EVENT_MONITOR_ENABLED", False):
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())

    def cog_unload(self) -> None:
        self._stop_event.set()

        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def _base_url(self) -> str:
        value = os.getenv("SEVENDTD_API_BASE_URL", "").strip()
        if not value:
            raise RuntimeError("SEVENDTD_API_BASE_URL fehlt in .env")
        return value.rstrip("/") + "/"

    def _url(self, endpoint: str) -> str:
        return urljoin(self._base_url(), endpoint.lstrip("/"))

    def _endpoint_candidates(self) -> list[str]:
        configured = os.getenv("SEVENDTD_LOG_SSE_ENDPOINT", "").strip()

        candidates = []
        if configured:
            candidates.append(configured)

        candidates.extend(
            [
                "api/log",
                "api/Log",
            ]
        )

        seen: set[str] = set()
        result: list[str] = []

        for item in candidates:
            clean = item.strip().lstrip("/")
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)

        return result

    def _headers(self) -> dict[str, str]:
        token_kind = os.getenv("SEVENDTD_LOG_TOKEN_KIND", "admin").strip().lower()

        if token_kind == "log":
            token_name = os.getenv("SEVENDTD_LOG_TOKEN_NAME", "").strip()
            token_secret = os.getenv("SEVENDTD_LOG_TOKEN_SECRET", "").strip()
        elif token_kind == "read":
            token_name = os.getenv("SEVENDTD_READ_TOKEN_NAME", "").strip()
            token_secret = os.getenv("SEVENDTD_READ_TOKEN_SECRET", "").strip()
        else:
            token_name = os.getenv("SEVENDTD_ADMIN_TOKEN_NAME", "").strip()
            token_secret = os.getenv("SEVENDTD_ADMIN_TOKEN_SECRET", "").strip()

        if not token_name or not token_secret:
            raise RuntimeError(
                "7DTD Log-Monitor Token fehlt. Prüfe SEVENDTD_LOG_TOKEN_KIND und Token-Variablen."
            )

        name_header = os.getenv("SEVENDTD_TOKEN_NAME_HEADER", "X-SDTD-API-TOKENNAME").strip()
        secret_header = os.getenv("SEVENDTD_TOKEN_SECRET_HEADER", "X-SDTD-API-SECRET").strip()

        return {
            name_header: token_name,
            secret_header: token_secret,
            "Accept": "text/event-stream, application/json, text/plain",
            "Cache-Control": "no-cache",
        }

    def _event_channel_id(self) -> int:
        return _env_int("SEVENDTD_EVENT_CHANNEL_ID", 0)

    def _event_channel(self) -> nextcord.TextChannel | None:
        channel_id = self._event_channel_id()
        if not channel_id:
            return None

        channel = self.bot.get_channel(channel_id)
        return channel if isinstance(channel, nextcord.TextChannel) else None

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
        await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)

    # ------------------------------------------------------------------ #
    # Monitor loop
    # ------------------------------------------------------------------ #

    async def _monitor_loop(self) -> None:
        await self.bot.wait_until_ready()

        backoff = 3

        while not self.bot.is_closed() and not self._stop_event.is_set():
            try:
                for endpoint in self._endpoint_candidates():
                    if self._stop_event.is_set():
                        break

                    try:
                        self.current_endpoint = endpoint
                        await self._consume_stream(endpoint)
                        backoff = 3

                    except asyncio.CancelledError:
                        raise

                    except Exception as exc:
                        self.connected = False
                        self.last_error = f"{type(exc).__name__}: {exc}"

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

            except asyncio.CancelledError:
                break

            except Exception as exc:
                self.connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _consume_stream(self, endpoint: str) -> None:
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=15,
            sock_connect=15,
            sock_read=None,
        )

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.get(self._url(endpoint), ssl=False) as response:
                if response.status != 200:
                    raw = await response.text()
                    raise RuntimeError(f"{endpoint} returned HTTP {response.status}: {raw[:300]}")

                self.connected = True
                self.last_error = None

                content_type = response.headers.get("Content-Type", "").lower()
                is_sse = "text/event-stream" in content_type

                event_name: str | None = None
                data_lines: list[str] = []

                async for raw_line in response.content:
                    if self._stop_event.is_set():
                        break

                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    except Exception:
                        continue

                    if not line:
                        if data_lines:
                            payload = "\n".join(data_lines)
                            await self._handle_payload(payload, event_name=event_name)
                            data_lines.clear()
                            event_name = None
                        continue

                    if line.startswith(":"):
                        continue

                    if is_sse:
                        if line.startswith("event:"):
                            event_name = line.removeprefix("event:").strip()
                            continue

                        if line.startswith("data:"):
                            data_lines.append(line.removeprefix("data:").strip())
                            continue

                        # Fallback, falls Server kein sauberes SSE-Format sendet.
                        await self._handle_payload(line, event_name=event_name)
                    else:
                        await self._handle_payload(line, event_name=None)

    # ------------------------------------------------------------------ #
    # Payload / parsing
    # ------------------------------------------------------------------ #

    async def _handle_payload(self, payload: str, *, event_name: str | None) -> None:
        payload = payload.strip()
        if not payload:
            return

        self.total_lines_seen += 1

        lines = self._payload_to_lines(payload)

        for line in lines:
            clean = self._sanitize_line(line)
            if not clean:
                continue

            classified = self._classify_line(clean, event_name=event_name)
            if classified is None:
                continue

            if self._is_duplicate(classified.category, clean):
                continue

            if self._is_rate_limited():
                continue

            await self._send_event(classified, raw_line=clean)

    def _payload_to_lines(self, payload: str) -> list[str]:
        # JSON-Objekte vom WebAPI-Log möglichst sauber extrahieren.
        try:
            obj = json.loads(payload)

            if isinstance(obj, dict):
                for key in ("msg", "message", "line", "text", "data"):
                    value = obj.get(key)
                    if isinstance(value, str):
                        return value.splitlines()

                if "entries" in obj and isinstance(obj["entries"], list):
                    return [str(item) for item in obj["entries"]]

                return [json.dumps(obj, ensure_ascii=False)]

            if isinstance(obj, list):
                return [str(item) for item in obj]

        except Exception:
            pass

        return payload.splitlines()

    def _sanitize_line(self, line: str) -> str:
        text = " ".join(str(line).strip().split())
        if not text:
            return ""

        # Secrets/Passwörter nicht in Discord spiegeln.
        text = re.sub(
            r"(?i)\b(token|secret|password|passwd|pwd|auth|authorization)\b\s*[:=]\s*\S+",
            r"\1=<redacted>",
            text,
        )

        return text[:1800]

    def _classify_line(
        self,
        line: str,
        *,
        event_name: str | None,
    ) -> ClassifiedLogEvent | None:
        lower = line.lower()

        raw_debug = _env_bool("SEVENDTD_EVENT_RAW_DEBUG", False)
        forward_chat = _env_bool("SEVENDTD_EVENT_FORWARD_CHAT", False)

        # Fehler / Exceptions
        if (
            "exception" in lower
            or "nullreferenceexception" in lower
            or "error" in lower
            or "[err]" in lower
            or " err " in lower
        ):
            return ClassifiedLogEvent(
                category="error",
                title="7DTD Fehler / Exception",
                description=line,
                color=0xE74C3C,
                important=True,
            )

        # Warnungen
        if (
            "warning" in lower
            or "[wrn]" in lower
            or " wrn " in lower
        ):
            return ClassifiedLogEvent(
                category="warning",
                title="7DTD Warnung",
                description=line,
                color=0xF1C40F,
            )

        # Join / Connect
        if (
            "player connected" in lower
            or "playerspawnedinworld" in lower
            or "joined the game" in lower
            or "logged in" in lower
        ):
            return ClassifiedLogEvent(
                category="join",
                title="Spieler beigetreten",
                description=line,
                color=0x2ECC71,
            )

        # Leave / Disconnect
        if (
            "player disconnected" in lower
            or "disconnected" in lower
            or "left the game" in lower
            or "connection closed" in lower
        ):
            return ClassifiedLogEvent(
                category="leave",
                title="Spieler verlassen",
                description=line,
                color=0x95A5A6,
            )

        # Bloodmoon / Horde
        if (
            "bloodmoon" in lower
            or "blood moon" in lower
            or "horde" in lower
        ):
            return ClassifiedLogEvent(
                category="bloodmoon",
                title="Bloodmoon / Horde Event",
                description=line,
                color=0xC0392B,
                important=True,
            )

        # Save / World save
        if (
            "saveworld" in lower
            or "world saved" in lower
            or "saving world" in lower
            or "save and cleanup" in lower
        ):
            return ClassifiedLogEvent(
                category="save",
                title="Welt gespeichert",
                description=line,
                color=0x3498DB,
            )

        # Server start / ready
        if (
            "server started" in lower
            or "game started" in lower
            or "startdedicated" in lower
            or "server is ready" in lower
        ):
            return ClassifiedLogEvent(
                category="server_start",
                title="7DTD Server gestartet",
                description=line,
                color=0x2ECC71,
                important=True,
            )

        # Server stop / shutdown
        if (
            "server shutdown" in lower
            or "shutting down" in lower
            or "server stopped" in lower
        ):
            return ClassifiedLogEvent(
                category="server_stop",
                title="7DTD Server stoppt",
                description=line,
                color=0xE67E22,
                important=True,
            )

        # Chat bewusst optional.
        if forward_chat and (
            "chat" in lower
            or "sayplayer" in lower
            or "global" in lower
        ):
            return ClassifiedLogEvent(
                category="chat",
                title="7DTD Chat",
                description=line,
                color=0x5865F2,
            )

        if raw_debug:
            return ClassifiedLogEvent(
                category="raw",
                title=f"7DTD Log{f' · {event_name}' if event_name else ''}",
                description=line,
                color=0x5865F2,
            )

        return None

    # ------------------------------------------------------------------ #
    # Anti-Spam
    # ------------------------------------------------------------------ #

    def _is_duplicate(self, category: str, line: str, *, window_seconds: int = 30) -> bool:
        now = asyncio.get_running_loop().time()
        digest = hashlib.sha256(f"{category}:{line}".encode("utf-8")).hexdigest()

        # alte Hashes entfernen
        expired = [key for key, ts in self._recent_hashes.items() if now - ts > window_seconds]
        for key in expired:
            self._recent_hashes.pop(key, None)

        previous = self._recent_hashes.get(digest)
        if previous is not None and now - previous <= window_seconds:
            return True

        self._recent_hashes[digest] = now
        return False

    def _is_rate_limited(self, *, max_events: int = 20, window_seconds: int = 60) -> bool:
        now = asyncio.get_running_loop().time()

        while self._event_timestamps and now - self._event_timestamps[0] > window_seconds:
            self._event_timestamps.popleft()

        if len(self._event_timestamps) >= max_events:
            return True

        self._event_timestamps.append(now)
        return False

    # ------------------------------------------------------------------ #
    # Discord output
    # ------------------------------------------------------------------ #

    async def _send_event(self, event: ClassifiedLogEvent, *, raw_line: str) -> None:
        channel = self._event_channel()
        if channel is None:
            self.last_error = "SEVENDTD_EVENT_CHANNEL_ID fehlt oder Channel nicht gefunden."
            return

        embed = nextcord.Embed(
            title=event.title,
            description=f"```text\n{event.description[:1500]}\n```",
            color=event.color,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )

        embed.add_field(name="Kategorie", value=f"`{event.category}`", inline=True)

        if self.current_endpoint:
            embed.add_field(name="Quelle", value=f"`{self.current_endpoint}`", inline=True)

        embed.set_footer(text="hundekuchenlive Bot • 7DTD Event Monitor")

        await channel.send(embed=embed)

        self.last_event_at = dt.datetime.now(dt.timezone.utc)
        self.last_event_text = raw_line
        self.total_events_sent += 1

    # ------------------------------------------------------------------ #
    # Slash commands
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="7dtdlog",
        description="7DTD Log-/Event-Monitor verwalten.",
    )
    async def log_group(self, interaction: nextcord.Interaction) -> None:
        pass

    @log_group.subcommand(
        name="status",
        description="Zeigt den Status des 7DTD Log-/Event-Monitors.",
    )
    async def log_status(self, interaction: nextcord.Interaction) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        embed = nextcord.Embed(
            title="7DTD Log-/Event-Monitor",
            color=0x5865F2,
            timestamp=dt.datetime.now(dt.timezone.utc),
        )

        embed.add_field(
            name="Aktiviert",
            value=f"`{_env_bool('SEVENDTD_EVENT_MONITOR_ENABLED', False)}`",
            inline=True,
        )
        embed.add_field(name="Verbunden", value=f"`{self.connected}`", inline=True)
        embed.add_field(name="Endpoint", value=f"`{self.current_endpoint or 'n/a'}`", inline=True)
        embed.add_field(name="Gesehene Zeilen", value=f"`{self.total_lines_seen}`", inline=True)
        embed.add_field(name="Gesendete Events", value=f"`{self.total_events_sent}`", inline=True)
        embed.add_field(
            name="Event-Channel",
            value=f"`{self._event_channel_id() or 'n/a'}`",
            inline=True,
        )

        if self.last_event_at:
            embed.add_field(
                name="Letztes Event",
                value=f"`{self.last_event_at.isoformat(timespec='seconds')}`",
                inline=False,
            )

        if self.last_error:
            embed.add_field(
                name="Letzter Fehler",
                value=f"```text\n{self.last_error[:900]}\n```",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @log_group.subcommand(
        name="reconnect",
        description="Startet den 7DTD Log-/Event-Monitor neu.",
    )
    async def log_reconnect(self, interaction: nextcord.Interaction) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        self.connected = False
        self.last_error = None

        if self._task and not self._task.done():
            self._task.cancel()

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())

        await interaction.response.send_message(
            "7DTD Log-/Event-Monitor reconnect gestartet.",
            ephemeral=True,
        )

    @log_group.subcommand(
        name="test",
        description="Sendet ein Testevent in den konfigurierten Event-Channel.",
    )
    async def log_test(self, interaction: nextcord.Interaction) -> None:
        if not self._is_mod_or_admin(interaction):
            await self._deny(interaction)
            return

        event = ClassifiedLogEvent(
            category="test",
            title="7DTD Event-Monitor Test",
            description=f"Testevent ausgelöst von {interaction.user} ({interaction.user.id}).",
            color=0x2ECC71,
        )

        await self._send_event(event, raw_line=event.description)

        await interaction.response.send_message(
            "Testevent gesendet.",
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SevenDTDLogMonitor(bot))