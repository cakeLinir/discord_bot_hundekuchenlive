from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands

# ========= KONFIG =========
ALLOWED_DOMAINS = {
    "twitch.tv",
    "youtube.com",
    "tiktok.com",
    "instant-gaming.com",
    "steamcommunity.com",
}
# Optional (empfohlen): offizielle Kurzdomain von YouTube
ALLOWED_EXTRA_DOMAINS = {"youtu.be"}

DUP_WINDOW_SECONDS = 10  # Zeitfenster für Duplicate-Check
STRIKE_EXPIRE_DAYS = 30  # Strikes verfallen nach X Tagen
TIMEOUT_HOURS = 6  # Automatischer Timeout (Standard)
BAN_AT_STRIKES = 5  # Ab dieser Anzahl Strikes -> Ban
TIMEOUT_AT_STRIKES = 3  # Ab dieser Anzahl Strikes -> Timeout
WARN_DELETE_AFTER = 8  # Sekunden, nach denen Warnungen wieder gelöscht werden

# State-Datei: bot/data/moderation_state.json
BASE_DIR = Path(__file__).resolve().parents[3]  # .../bot
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "moderation_state.json"
# ==========================


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds")


def _parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def _ensure_state_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps({"badwords": [], "strikes": {}}, indent=2),
            encoding="utf-8",
        )


def load_state() -> dict:
    _ensure_state_file()
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"badwords": [], "strikes": {}}


def save_state(state: dict) -> None:
    _ensure_state_file()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clean_expired_strikes(state: dict, guild_id: int, user_id: int) -> int:
    """Entfernt abgelaufene Strikes; gibt aktive Strike-Anzahl zurück."""
    g = state.setdefault("strikes", {}).setdefault(str(guild_id), {})
    strikes = g.get(str(user_id), [])
    now = _now_utc()

    kept = []
    for s in strikes:
        try:
            exp = _parse_iso(s["expires"])
            if exp > now:
                kept.append(s)
        except Exception:
            # kaputter Eintrag -> weg
            continue

    if kept:
        g[str(user_id)] = kept
    else:
        g.pop(str(user_id), None)

    save_state(state)
    return len(kept)


def add_strike(
    state: dict, guild_id: int, user_id: int, *, rule: str, reason: str
) -> int:
    """Neuen Strike hinzufügen und Gesamtanzahl zurückgeben."""
    g = state.setdefault("strikes", {}).setdefault(str(guild_id), {})
    strikes = g.setdefault(str(user_id), [])

    now = _now_utc()
    exp = now + dt.timedelta(days=STRIKE_EXPIRE_DAYS)
    strikes.append(
        {
            "at": _iso(now),
            "expires": _iso(exp),
            "rule": rule,
            "reason": reason,
        }
    )
    save_state(state)
    return len(strikes)


def remove_all_strikes(state: dict, guild_id: int, user_id: int) -> None:
    g = state.setdefault("strikes", {}).setdefault(str(guild_id), {})
    g.pop(str(user_id), None)
    save_state(state)


def normalize_message_for_dup(text: str) -> str:
    """Duplicate-Check: trim, mehrfach-Spaces reduzieren, lowercase."""
    t = " ".join(text.strip().split())
    return t.lower()


URL_REGEX = re.compile(r"(https?://[^\s<]+)", re.IGNORECASE)


def extract_hosts(text: str) -> list[str]:
    """Extrahiert Hostnamen aus allen URLs in einem Text."""
    hosts: list[str] = []
    for m in URL_REGEX.findall(text):
        try:
            u = urlparse(m)
            host = (u.hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                hosts.append(host)
        except Exception:
            continue
    return hosts


def is_allowed_host(host: str) -> bool:
    allowed = set(ALLOWED_DOMAINS) | set(ALLOWED_EXTRA_DOMAINS)

    # exakter Match
    if host in allowed:
        return True

    # Subdomain erlaubt: z.B. clips.twitch.tv -> .twitch.tv
    for d in allowed:
        if host.endswith("." + d):
            return True

    return False


def contains_badword(text: str, badwords: list[str]) -> str | None:
    """Erstes gefundene Badword (case-insensitive) oder None."""
    if not badwords:
        return None
    lowered = text.lower()
    for w in badwords:
        w = w.strip().lower()
        if not w:
            continue
        if w in lowered:
            return w
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Duplicate-Cache: (guild_id, user_id) -> (hash, timestamp)
        self._dup_cache: dict[tuple[int, int], tuple[str, float]] = {}

    # ---------- Permission helpers ----------

    def _mod_role_id(self) -> int | None:
        v = os.getenv("MOD_ROLE_ID", "").strip()
        return int(v) if v.isdigit() else None

    def _log_channel_id(self) -> int | None:
        v = os.getenv("MOD_LOG_CHANNEL_ID", "").strip()
        return int(v) if v.isdigit() else None

    def is_mod(self, member: nextcord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        rid = self._mod_role_id()
        if not rid:
            return False
        return any(r.id == rid for r in getattr(member, "roles", []))

    async def log_mod(self, guild: nextcord.Guild, text: str) -> None:
        cid = self._log_channel_id()
        if not cid:
            return
        ch = guild.get_channel(cid)
        if ch:
            await ch.send(text)

    # ---------- Auto actions ----------

    async def apply_punishment_if_needed(
        self, member: nextcord.Member, strike_count: int, *, context: str
    ) -> None:
        """Timeout/Ban je nach Anzahl der Strikes."""
        # Timeout bei 3+
        if TIMEOUT_AT_STRIKES <= strike_count < BAN_AT_STRIKES:
            until = _now_utc() + dt.timedelta(hours=TIMEOUT_HOURS)
            try:
                await member.timeout(
                    until, reason=f"AutoMod: {context} (Strikes: {strike_count})"
                )
            except Exception:
                pass

        # Ban bei 5+
        if strike_count >= BAN_AT_STRIKES:
            try:
                await member.ban(
                    reason=f"AutoMod: {context} (Strikes: {strike_count})",
                    delete_message_days=0,
                )
            except Exception:
                pass

    async def warn_channel(self, channel: nextcord.abc.Messageable, text: str):
        try:
            await channel.send(text, delete_after=WARN_DELETE_AFTER)
        except Exception:
            pass

    # ---------- Auto moderation core ----------

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if not message.guild:
            return
        if message.author.bot:
            return

        member: nextcord.Member = message.author  # type: ignore[assignment]
        guild = message.guild

        # Strikes des Users zuerst aufräumen (abgelaufene löschen)
        state = load_state()
        clean_expired_strikes(state, guild.id, member.id)

        # 1) Link-Filter
        hosts = extract_hosts(message.content)
        if hosts:
            blocked = [h for h in hosts if not is_allowed_host(h)]
            if blocked:
                try:
                    await message.delete()
                    await self.warn_channel(
                        message.channel,
                        f"{member.mention} unerlaubter Link. (Strike)",
                    )
                except Exception:
                    pass

                state = load_state()
                strike_count = add_strike(
                    state,
                    guild.id,
                    member.id,
                    rule="link",
                    reason=f"Unerlaubter Link: {', '.join(blocked)[:150]}",
                )
                await self.log_mod(
                    guild,
                    f"[AUTOMOD][LINK] user={member} ({member.id}) "
                    f"channel=#{message.channel} blocked={blocked} "
                    f"strikes={strike_count} action=delete",
                )
                await self.apply_punishment_if_needed(
                    member, strike_count, context="Unerlaubter Link"
                )
                return

        # 2) Duplicate-Message (2 gleiche innerhalb 10s)
        norm = normalize_message_for_dup(message.content)
        if norm:
            h = hashlib.sha256(norm.encode("utf-8")).hexdigest()
            key = (guild.id, member.id)
            now_ts = message.created_at.timestamp()

            prev = self._dup_cache.get(key)
            if prev:
                prev_hash, prev_ts = prev
                if prev_hash == h and (now_ts - prev_ts) <= DUP_WINDOW_SECONDS:
                    try:
                        await message.delete()
                    except Exception:
                        pass

                    state = load_state()
                    strike_count = add_strike(
                        state,
                        guild.id,
                        member.id,
                        rule="duplicate",
                        reason=f"Doppelte Nachricht innerhalb {DUP_WINDOW_SECONDS}s",
                    )
                    await self.log_mod(
                        guild,
                        f"[AUTOMOD][DUP] user={member} ({member.id}) "
                        f"channel=#{message.channel} strikes={strike_count} action=delete",
                    )
                    await self.apply_punishment_if_needed(
                        member, strike_count, context="Duplicate Spam"
                    )
                    await self.warn_channel(
                        message.channel,
                        f"{member.mention} Duplicate-Spam. Bitte nicht doppelt posten. (Strike)",
                    )
                    return

            self._dup_cache[key] = (h, now_ts)

        # 3) Badword/Blacklist
        state = load_state()
        badwords: list[str] = state.get("badwords", [])
        hit = contains_badword(message.content, badwords)
        if hit:
            try:
                await message.delete()
            except Exception:
                pass

            state = load_state()
            strike_count = add_strike(
                state,
                guild.id,
                member.id,
                rule="badword",
                reason=f"Badword: {hit}",
            )
            await self.log_mod(
                guild,
                f"[AUTOMOD][BADWORD] user={member} ({member.id}) "
                f"channel=#{message.channel} hit='{hit}' "
                f"strikes={strike_count} action=delete",
            )
            await self.apply_punishment_if_needed(
                member, strike_count, context=f"Badword '{hit}'"
            )
            await self.warn_channel(
                message.channel,
                f"{member.mention} Ausdruck nicht erlaubt. (Strike)",
            )
            return

    # ---------- Slash command group ----------

    @nextcord.slash_command(
        name="mod",
        description="Moderation (Mod-Rolle oder Admin erforderlich)",
    )
    async def mod_root(self, interaction: Interaction):
        # wird nicht direkt benutzt; Subcommands hängen darunter
        pass

    def _check_mod(self, interaction: Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return False
        return self.is_mod(interaction.user)

    # ----- Kick / Ban / Timeout / Clear -----

    @mod_root.subcommand(description="User kicken")
    async def kick(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
        reason: str = SlashOption(description="Grund", required=False, default=""),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        try:
            await user.kick(reason=reason or None)
            await interaction.response.send_message(
                f"{user.mention} gekickt.", ephemeral=True
            )
            await self.log_mod(
                interaction.guild,
                f"[MOD][KICK] by={interaction.user} target={user} reason='{reason}'",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler: {type(e).__name__}: {e}", ephemeral=True
            )

    @mod_root.subcommand(description="User bannen")
    async def ban(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
        reason: str = SlashOption(description="Grund", required=False, default=""),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        try:
            await user.ban(reason=reason or None, delete_message_days=0)
            await interaction.response.send_message(
                f"{user.mention} gebannt.", ephemeral=True
            )
            await self.log_mod(
                interaction.guild,
                f"[MOD][BAN] by={interaction.user} target={user} reason='{reason}'",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler: {type(e).__name__}: {e}", ephemeral=True
            )

    @mod_root.subcommand(description="User timeout setzen (Standard 6h)")
    async def timeout(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
        hours: int = SlashOption(description="Stunden", required=False, default=6),
        reason: str = SlashOption(description="Grund", required=False, default=""),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        try:
            until = _now_utc() + dt.timedelta(hours=max(1, hours))
            await user.timeout(until, reason=reason or None)
            await interaction.response.send_message(
                f"{user.mention} Timeout bis {until.isoformat(timespec='minutes')}.",
                ephemeral=True,
            )
            await self.log_mod(
                interaction.guild,
                f"[MOD][TIMEOUT] by={interaction.user} target={user} "
                f"hours={hours} reason='{reason}'",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler: {type(e).__name__}: {e}", ephemeral=True
            )

    @mod_root.subcommand(description="Timeout entfernen")
    async def untimeout(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
        reason: str = SlashOption(description="Grund", required=False, default=""),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        try:
            await user.timeout(None, reason=reason or None)
            await interaction.response.send_message(
                f"Timeout von {user.mention} entfernt.", ephemeral=True
            )
            await self.log_mod(
                interaction.guild,
                f"[MOD][UNTIMEOUT] by={interaction.user} target={user} reason='{reason}'",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler: {type(e).__name__}: {e}", ephemeral=True
            )

    @mod_root.subcommand(description="Nachrichten löschen")
    async def clear(
        self,
        interaction: Interaction,
        amount: int = SlashOption(description="Anzahl (1-100)"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        if not interaction.channel or not hasattr(interaction.channel, "purge"):
            await interaction.response.send_message(
                "Ungültiger Channel.", ephemeral=True
            )
            return

        amount = max(1, min(100, amount))
        try:
            deleted = await interaction.channel.purge(limit=amount)  # type: ignore[attr-defined]
            await interaction.response.send_message(
                f"{len(deleted)} Nachrichten gelöscht.", ephemeral=True
            )
            await self.log_mod(
                interaction.guild,
                f"[MOD][CLEAR] by={interaction.user} "
                f"channel=#{interaction.channel} amount={len(deleted)}",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler: {type(e).__name__}: {e}", ephemeral=True
            )

    # ----- Strikes -----

    @mod_root.subcommand(description="Strikes eines Users anzeigen")
    async def strikes(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return

        state = load_state()
        count = clean_expired_strikes(state, interaction.guild.id, user.id)
        state = load_state()
        strikes = (
            state.get("strikes", {})
            .get(str(interaction.guild.id), {})
            .get(str(user.id), [])
        )

        lines = []
        for s in strikes[:10]:
            lines.append(
                f"- {s.get('rule','?')} | exp: {s.get('expires','?')} "
                f"| {s.get('reason','')}"
            )
        text = "\n".join(lines) if lines else "Keine aktiven Strikes."

        await interaction.response.send_message(
            f"Aktive Strikes für {user.mention}: **{count}**\n{text}",
            ephemeral=True,
        )

    @mod_root.subcommand(description="Strikes eines Users löschen")
    async def strike_clear(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return
        state = load_state()
        remove_all_strikes(state, interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"Strikes für {user.mention} gelöscht.", ephemeral=True
        )
        await self.log_mod(
            interaction.guild,
            f"[MOD][STRIKE_CLEAR] by={interaction.user} target={user}",
        )

    @mod_root.subcommand(description="Strike manuell hinzufügen")
    async def strike_add(
        self,
        interaction: Interaction,
        user: nextcord.Member = SlashOption(description="User"),
        reason: str = SlashOption(description="Grund"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return

        state = load_state()
        clean_expired_strikes(state, interaction.guild.id, user.id)
        state = load_state()
        strike_count = add_strike(
            state, interaction.guild.id, user.id, rule="manual", reason=reason
        )
        await interaction.response.send_message(
            f"Strike hinzugefügt. Aktive Strikes: **{strike_count}**",
            ephemeral=True,
        )
        await self.log_mod(
            interaction.guild,
            f"[MOD][STRIKE_ADD] by={interaction.user} "
            f"target={user} strikes={strike_count} reason='{reason}'",
        )
        await self.apply_punishment_if_needed(
            user, strike_count, context="Manual strike"
        )

    # ----- Badwords -----

    @mod_root.subcommand(description="Badword hinzufügen")
    async def badword_add(
        self,
        interaction: Interaction,
        word: str = SlashOption(description="Wort/Phrase"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return

        w = word.strip().lower()
        if not w:
            await interaction.response.send_message("Ungültig.", ephemeral=True)
            return

        state = load_state()
        badwords: list[str] = state.get("badwords", [])
        lowered = [x.lower() for x in badwords]
        if w in lowered:
            await interaction.response.send_message(
                "Bereits vorhanden.", ephemeral=True
            )
            return

        badwords.append(w)
        state["badwords"] = sorted(set(badwords))
        save_state(state)

        await interaction.response.send_message(
            f"Badword hinzugefügt: `{w}`", ephemeral=True
        )
        await self.log_mod(
            interaction.guild,
            f"[MOD][BADWORD_ADD] by={interaction.user} word='{w}'",
        )

    @mod_root.subcommand(description="Badword entfernen")
    async def badword_remove(
        self,
        interaction: Interaction,
        word: str = SlashOption(description="Wort/Phrase"),
    ):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return

        w = word.strip().lower()
        state = load_state()
        badwords: list[str] = state.get("badwords", [])
        new_list = [x for x in badwords if x.lower() != w]
        state["badwords"] = new_list
        save_state(state)

        await interaction.response.send_message(
            f"Badword entfernt: `{w}`", ephemeral=True
        )
        await self.log_mod(
            interaction.guild,
            f"[MOD][BADWORD_REMOVE] by={interaction.user} word='{w}'",
        )

    @mod_root.subcommand(description="Badwords anzeigen")
    async def badword_list(self, interaction: Interaction):
        if not self._check_mod(interaction):
            await interaction.response.send_message(
                "Keine Berechtigung.", ephemeral=True
            )
            return

        state = load_state()
        badwords: list[str] = state.get("badwords", [])
        if not badwords:
            await interaction.response.send_message("Liste ist leer.", ephemeral=True)
            return

        shown = ", ".join(badwords[:50])
        more = "" if len(badwords) <= 50 else f" (+{len(badwords) - 50} weitere)"
        await interaction.response.send_message(
            f"Badwords ({len(badwords)}): {shown}{more}",
            ephemeral=True,
        )


def setup(bot: commands.Bot):
    bot.add_cog(Moderation(bot))
