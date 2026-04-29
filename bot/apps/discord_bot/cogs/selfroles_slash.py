from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import nextcord
from nextcord.ext import commands

# ---------------------------------------------------------------------------
# Pfade / Dateien
# ---------------------------------------------------------------------------

# .../bot/apps/discord_bot/cogs/selfroles_slash.py
COGS_DIR = Path(__file__).resolve().parent
DISCORD_BOT_DIR = COGS_DIR.parent
APPS_DIR = DISCORD_BOT_DIR.parent
BOT_ROOT = APPS_DIR.parent

DATA_DIR = BOT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SELFROLE_FILE = DATA_DIR / "selfroles.json"
FIXED_STATE_FILE = DATA_DIR / "selfroles_state.json"

# ---------------------------------------------------------------------------
# Feste Selfrole-Konfiguration
# ---------------------------------------------------------------------------

SELFROLE_CHANNEL_ENV = "SELFROLE_CHANNEL_ID"

ROLE_IDS = {
    "Regelwerk bestätigt": 1171411067755315230,
    "Twitch": 1171131544035938427,
    "YouTube": 1171131322811568250,
}

STYLE_CHOICES = {
    "primary": "primary",
    "secondary": "secondary",
    "success": "success",
    "danger": "danger",
}


# ---------------------------------------------------------------------------
# JSON Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
    except OSError:
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_selfroles() -> dict[str, dict[str, Any]]:
    return _load_json(SELFROLE_FILE)


def save_selfroles(data: dict[str, dict[str, Any]]) -> None:
    _save_json(SELFROLE_FILE, data)


def load_fixed_state() -> dict[str, Any]:
    return _load_json(FIXED_STATE_FILE)


def save_fixed_state(data: dict[str, Any]) -> None:
    _save_json(FIXED_STATE_FILE, data)


# ---------------------------------------------------------------------------
# Allgemeine Helpers
# ---------------------------------------------------------------------------

def _button_style(style_name: str | None) -> nextcord.ButtonStyle:
    style = (style_name or "secondary").lower()

    if style == "primary":
        return nextcord.ButtonStyle.primary
    if style == "success":
        return nextcord.ButtonStyle.success
    if style == "danger":
        return nextcord.ButtonStyle.danger

    return nextcord.ButtonStyle.secondary


def _has_selfrole_admin_permissions(interaction: nextcord.Interaction) -> bool:
    user = interaction.user

    if not isinstance(user, nextcord.Member):
        return False

    perms = user.guild_permissions
    return bool(
        perms.administrator
        or (perms.manage_guild and perms.manage_roles)
    )


async def _deny(interaction: nextcord.Interaction) -> None:
    await interaction.response.send_message(
        "Du brauchst **Server verwalten** und **Rollen verwalten**.",
        ephemeral=True,
    )


def build_fixed_embed() -> nextcord.Embed:
    embed = nextcord.Embed(
        title="Selfroles",
        color=nextcord.Color.blurple(),
    )
    embed.description = (
        "Klicke auf einen Button, um die Rolle **zu erhalten oder zu entfernen**.\n\n"
        "• Regelwerk bestätigt\n"
        "• Twitch (nur mit Regelwerk bestätigt)\n"
        "• YouTube (nur mit Regelwerk bestätigt)"
    )
    embed.set_footer(text="Buttons bleiben dauerhaft aktiv.")
    return embed


# ---------------------------------------------------------------------------
# Festes Selfrole-Panel: Regelwerk / Twitch / YouTube
# ---------------------------------------------------------------------------

class FixedSelfRoleView(nextcord.ui.View):
    """Persistente View für das feste Regelwerk/Twitch/YouTube-Panel."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _toggle_role(
        self,
        interaction: nextcord.Interaction,
        role_id: int,
        label: str,
        require_rules: bool = False,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            await interaction.response.send_message(
                "Guild/Member-Kontext fehlt.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member: nextcord.Member = interaction.user

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                f"Rolle nicht gefunden: {label}",
                ephemeral=True,
            )
            return

        rules_role = guild.get_role(ROLE_IDS["Regelwerk bestätigt"])

        if require_rules and (rules_role is None or rules_role not in member.roles):
            await interaction.response.send_message(
                "Bitte zuerst **Regelwerk bestätigt** anklicken.",
                ephemeral=True,
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Selfrole button")
                await interaction.response.send_message(
                    f"Entfernt: **{label}**",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role, reason="Selfrole button")
                await interaction.response.send_message(
                    f"Hinzugefügt: **{label}**",
                    ephemeral=True,
                )

        except nextcord.Forbidden:
            await interaction.response.send_message(
                "Fehlende Rechte: Bot kann diese Rolle nicht setzen.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.response.send_message(
                f"Fehler: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    @nextcord.ui.button(
        label="Regelwerk bestätigt",
        style=nextcord.ButtonStyle.success,
        custom_id="selfrole:fixed:rules",
    )
    async def btn_rules(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            await interaction.response.send_message(
                "Guild/Member-Kontext fehlt.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member: nextcord.Member = interaction.user

        rules_role = guild.get_role(ROLE_IDS["Regelwerk bestätigt"])
        twitch_role = guild.get_role(ROLE_IDS["Twitch"])
        youtube_role = guild.get_role(ROLE_IDS["YouTube"])

        if rules_role is None:
            await interaction.response.send_message(
                "Rolle nicht gefunden: Regelwerk bestätigt",
                ephemeral=True,
            )
            return

        try:
            if rules_role in member.roles:
                remove_roles = [
                    role
                    for role in (twitch_role, youtube_role, rules_role)
                    if role is not None and role in member.roles
                ]

                if remove_roles:
                    await member.remove_roles(
                        *remove_roles,
                        reason="Selfrole: rules removed -> remove dependent roles",
                    )

                await interaction.response.send_message(
                    "Entfernt: **Regelwerk bestätigt**. "
                    "Twitch/YouTube wurden ebenfalls entfernt.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(
                    rules_role,
                    reason="Selfrole rules accepted",
                )
                await interaction.response.send_message(
                    "Hinzugefügt: **Regelwerk bestätigt**",
                    ephemeral=True,
                )

        except nextcord.Forbidden:
            await interaction.response.send_message(
                "Fehlende Rechte: Bot kann Rollen nicht setzen.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.response.send_message(
                f"Fehler: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )

    @nextcord.ui.button(
        label="Twitch",
        style=nextcord.ButtonStyle.primary,
        custom_id="selfrole:fixed:twitch",
    )
    async def btn_twitch(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        await self._toggle_role(
            interaction,
            ROLE_IDS["Twitch"],
            label="Twitch",
            require_rules=True,
        )

    @nextcord.ui.button(
        label="YouTube",
        style=nextcord.ButtonStyle.primary,
        custom_id="selfrole:fixed:youtube",
    )
    async def btn_youtube(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction,
    ) -> None:
        await self._toggle_role(
            interaction,
            ROLE_IDS["YouTube"],
            label="YouTube",
            require_rules=True,
        )


# ---------------------------------------------------------------------------
# Dynamische Selfrole-Panels
# ---------------------------------------------------------------------------

class DynamicSelfroleButton(nextcord.ui.Button):
    """Button für dynamische Selfrole-Panels."""

    def __init__(
        self,
        *,
        guild_id: int,
        config_id: str,
        role_id: int,
        label: str,
        style: nextcord.ButtonStyle,
    ):
        super().__init__(
            label=label,
            style=style,
            custom_id=f"selfrole:dynamic:{config_id}:{role_id}",
        )
        self.guild_id = guild_id
        self.config_id = config_id
        self.role_id = role_id

    async def callback(self, interaction: nextcord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Selfroles funktionieren nur auf einem Server.",
                ephemeral=True,
            )
            return

        if interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "Diese Selfrole-Konfiguration gehört zu einem anderen Server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, nextcord.Member):
            await interaction.response.send_message(
                "Member-Kontext fehlt.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "Diese Rolle existiert nicht mehr.",
                ephemeral=True,
            )
            return

        member: nextcord.Member = interaction.user

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Selfrole: entfernt")
                await interaction.response.send_message(
                    f"Rolle {role.mention} wurde entfernt.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role, reason="Selfrole: vergeben")
                await interaction.response.send_message(
                    f"Rolle {role.mention} wurde hinzugefügt.",
                    ephemeral=True,
                )

        except nextcord.Forbidden:
            await interaction.response.send_message(
                "Ich habe nicht genügend Rechte, um diese Rolle zu verwalten.",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.response.send_message(
                f"Fehler: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )


class DynamicSelfroleView(nextcord.ui.View):
    """Persistente View für dynamische Selfrole-Konfigurationen."""

    def __init__(self, guild_id: int, config_id: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.config_id = config_id

        data = load_selfroles()
        config = data.get(str(guild_id), {}).get(config_id, {})
        roles: dict[str, dict[str, Any]] = config.get("roles", {})

        for role_id_str, button_conf in roles.items():
            try:
                role_id = int(role_id_str)
            except ValueError:
                continue

            label = str(button_conf.get("label", "Role"))[:80]
            style = _button_style(button_conf.get("style"))

            self.add_item(
                DynamicSelfroleButton(
                    guild_id=guild_id,
                    config_id=config_id,
                    role_id=role_id,
                    label=label,
                    style=style,
                )
            )


# ---------------------------------------------------------------------------
# Slash-Cog
# ---------------------------------------------------------------------------

class SelfrolesSlash(commands.Cog):
    """Slash-Commands für feste und dynamische Selfrole-Panels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Feste persistent View registrieren
        bot.add_view(FixedSelfRoleView())

        # Dynamische persistent Views aus JSON registrieren
        self._register_dynamic_views()

    def _register_dynamic_views(self) -> None:
        data = load_selfroles()

        for guild_id_str, configs in data.items():
            try:
                guild_id = int(guild_id_str)
            except ValueError:
                continue

            if not isinstance(configs, dict):
                continue

            for config_id in configs.keys():
                view = DynamicSelfroleView(guild_id, str(config_id))
                if len(view.children) > 0:
                    self.bot.add_view(view)

    # -------------------------------------------------------------- #
    # /selfrole Gruppe
    # -------------------------------------------------------------- #

    @nextcord.slash_command(
        name="selfrole",
        description="Verwalte Selfrole-Nachrichten.",
    )
    async def selfrole_group(self, interaction: nextcord.Interaction) -> None:
        pass

    # -------------------------------------------------------------- #
    # /selfrole fixed_panel
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="fixed_panel",
        description="Erstellt oder aktualisiert das feste Regelwerk/Twitch/YouTube-Panel.",
    )
    async def selfrole_fixed_panel(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel | None = nextcord.SlashOption(
            description="Optionaler Zielchannel. Ohne Angabe wird SELFROLE_CHANNEL_ID genutzt.",
            required=False,
            default=None,
        ),
    ) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        target_channel = channel

        if target_channel is None:
            channel_id = os.getenv(SELFROLE_CHANNEL_ENV, "").strip()
            if not channel_id.isdigit():
                await interaction.response.send_message(
                    "`SELFROLE_CHANNEL_ID` fehlt oder ist ungültig.",
                    ephemeral=True,
                )
                return

            resolved_channel = self.bot.get_channel(int(channel_id))
            if not isinstance(resolved_channel, nextcord.TextChannel):
                await interaction.response.send_message(
                    "Selfrole-Channel nicht gefunden oder kein Textkanal.",
                    ephemeral=True,
                )
                return

            target_channel = resolved_channel

        embed = build_fixed_embed()
        view = FixedSelfRoleView()

        state = load_fixed_state()
        guild_state = state.setdefault(str(interaction.guild.id), {})
        old_message_id = guild_state.get("fixed_panel_message_id")

        if old_message_id:
            try:
                old_message = await target_channel.fetch_message(int(old_message_id))
                await old_message.edit(embed=embed, view=view)
                self.bot.add_view(view)

                await interaction.response.send_message(
                    f"Festes Selfrole-Panel in {target_channel.mention} aktualisiert.",
                    ephemeral=True,
                )
                return
            except Exception:
                # Alte Nachricht existiert nicht mehr oder liegt in anderem Channel.
                pass

        message = await target_channel.send(embed=embed, view=view)
        guild_state["fixed_panel_channel_id"] = target_channel.id
        guild_state["fixed_panel_message_id"] = message.id
        save_fixed_state(state)

        self.bot.add_view(view)

        await interaction.response.send_message(
            f"Festes Selfrole-Panel in {target_channel.mention} erstellt.",
            ephemeral=True,
        )

    # -------------------------------------------------------------- #
    # /selfrole create
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="create",
        description="Erstellt eine dynamische Selfrole-Nachricht mit einer ersten Rolle.",
    )
    async def selfrole_create(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel = nextcord.SlashOption(
            description="Channel, in den die Selfrole-Nachricht gesendet werden soll.",
            required=True,
        ),
        titel: str = nextcord.SlashOption(
            description="Titel des Embeds.",
            required=True,
        ),
        beschreibung: str = nextcord.SlashOption(
            description="Beschreibung / Hinweistext.",
            required=True,
        ),
        rolle: nextcord.Role = nextcord.SlashOption(
            description="Erste Rolle, die vergeben werden soll.",
            required=True,
        ),
        button_label: str = nextcord.SlashOption(
            description="Text auf dem Button für diese Rolle.",
            required=True,
        ),
        style: str = nextcord.SlashOption(
            description="Button-Stil.",
            choices=STYLE_CHOICES,
            required=False,
            default="secondary",
        ),
    ) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        data = load_selfroles()
        guild_configs = data.setdefault(str(interaction.guild_id), {})

        config_id = f"cfg_{int(nextcord.utils.utcnow().timestamp())}"

        embed = nextcord.Embed(
            title=titel[:256],
            description=beschreibung[:4000],
            color=nextcord.Color.blurple(),
        )

        guild_configs[config_id] = {
            "channel_id": channel.id,
            "message_id": None,
            "title": titel[:256],
            "description": beschreibung[:4000],
            "roles": {
                str(rolle.id): {
                    "label": button_label[:80],
                    "style": style,
                }
            },
        }

        save_selfroles(data)

        view = DynamicSelfroleView(interaction.guild_id, config_id)
        self.bot.add_view(view)

        message = await channel.send(embed=embed, view=view)

        data = load_selfroles()
        data[str(interaction.guild_id)][config_id]["message_id"] = message.id
        save_selfroles(data)

        await interaction.response.send_message(
            (
                f"Selfrole-Nachricht erstellt in {channel.mention}.\n"
                f"Config-ID: `{config_id}`\n"
                f"Message-ID: `{message.id}`"
            ),
            ephemeral=True,
        )

    # -------------------------------------------------------------- #
    # /selfrole add
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="add",
        description="Fügt einer bestehenden dynamischen Selfrole-Nachricht eine Rolle hinzu.",
    )
    async def selfrole_add(
        self,
        interaction: nextcord.Interaction,
        message_id: str = nextcord.SlashOption(
            description="ID der Selfrole-Nachricht.",
            required=True,
        ),
        rolle: nextcord.Role = nextcord.SlashOption(
            description="Rolle, die hinzugefügt werden soll.",
            required=True,
        ),
        button_label: str = nextcord.SlashOption(
            description="Text auf dem Button für diese Rolle.",
            required=True,
        ),
        style: str = nextcord.SlashOption(
            description="Button-Stil.",
            choices=STYLE_CHOICES,
            required=False,
            default="secondary",
        ),
    ) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        data = load_selfroles()
        guild_configs = data.get(str(interaction.guild_id), {})

        target_config_id: str | None = None
        for config_id, config in guild_configs.items():
            if str(config.get("message_id")) == message_id:
                target_config_id = str(config_id)
                break

        if target_config_id is None:
            await interaction.response.send_message(
                "Keine Selfrole-Konfiguration mit dieser Nachrichten-ID gefunden.",
                ephemeral=True,
            )
            return

        config = guild_configs[target_config_id]
        roles: dict[str, dict[str, Any]] = config.setdefault("roles", {})

        if str(rolle.id) not in roles and len(roles) >= 25:
            await interaction.response.send_message(
                "Diese Selfrole-Nachricht hat bereits 25 Buttons. Discord erlaubt maximal 25 Komponenten.",
                ephemeral=True,
            )
            return

        roles[str(rolle.id)] = {
            "label": button_label[:80],
            "style": style,
        }

        save_selfroles(data)

        view = DynamicSelfroleView(interaction.guild_id, target_config_id)
        self.bot.add_view(view)

        channel = interaction.guild.get_channel(int(config["channel_id"]))
        if isinstance(channel, nextcord.TextChannel):
            try:
                message = await channel.fetch_message(int(config["message_id"]))
                await message.edit(view=view)
            except nextcord.NotFound:
                pass

        await interaction.response.send_message(
            f"Rolle {rolle.mention} wurde zur Selfrole-Nachricht hinzugefügt.",
            ephemeral=True,
        )

    # -------------------------------------------------------------- #
    # /selfrole remove
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="remove",
        description="Entfernt eine Rolle aus einer dynamischen Selfrole-Nachricht.",
    )
    async def selfrole_remove(
        self,
        interaction: nextcord.Interaction,
        message_id: str = nextcord.SlashOption(
            description="ID der Selfrole-Nachricht.",
            required=True,
        ),
        rolle: nextcord.Role = nextcord.SlashOption(
            description="Rolle, die aus dem Panel entfernt werden soll.",
            required=True,
        ),
    ) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        data = load_selfroles()
        guild_configs = data.get(str(interaction.guild_id), {})

        target_config_id: str | None = None
        for config_id, config in guild_configs.items():
            if str(config.get("message_id")) == message_id:
                target_config_id = str(config_id)
                break

        if target_config_id is None:
            await interaction.response.send_message(
                "Keine Selfrole-Konfiguration mit dieser Nachrichten-ID gefunden.",
                ephemeral=True,
            )
            return

        config = guild_configs[target_config_id]
        roles: dict[str, dict[str, Any]] = config.setdefault("roles", {})

        removed = roles.pop(str(rolle.id), None)
        if removed is None:
            await interaction.response.send_message(
                "Diese Rolle ist in der Selfrole-Nachricht nicht konfiguriert.",
                ephemeral=True,
            )
            return

        save_selfroles(data)

        view = DynamicSelfroleView(interaction.guild_id, target_config_id)
        self.bot.add_view(view)

        channel = interaction.guild.get_channel(int(config["channel_id"]))
        if isinstance(channel, nextcord.TextChannel):
            try:
                message = await channel.fetch_message(int(config["message_id"]))
                await message.edit(view=view if len(view.children) > 0 else None)
            except nextcord.NotFound:
                pass

        await interaction.response.send_message(
            f"Rolle {rolle.mention} wurde aus der Selfrole-Nachricht entfernt.",
            ephemeral=True,
        )

    # -------------------------------------------------------------- #
    # /selfrole list
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="list",
        description="Listet gespeicherte dynamische Selfrole-Konfigurationen.",
    )
    async def selfrole_list(self, interaction: nextcord.Interaction) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        data = load_selfroles()
        guild_configs = data.get(str(interaction.guild_id), {})

        if not guild_configs:
            await interaction.response.send_message(
                "Keine dynamischen Selfrole-Konfigurationen gefunden.",
                ephemeral=True,
            )
            return

        lines: list[str] = []

        for config_id, config in guild_configs.items():
            roles = config.get("roles", {})
            lines.append(
                f"`{config_id}` | Message `{config.get('message_id')}` | "
                f"Channel `{config.get('channel_id')}` | Rollen `{len(roles)}`"
            )

        await interaction.response.send_message(
            "\n".join(lines)[:1900],
            ephemeral=True,
        )

    # -------------------------------------------------------------- #
    # /selfrole delete_config
    # -------------------------------------------------------------- #

    @selfrole_group.subcommand(
        name="delete_config",
        description="Löscht eine dynamische Selfrole-Konfiguration. Nachricht bleibt optional bestehen.",
    )
    async def selfrole_delete_config(
        self,
        interaction: nextcord.Interaction,
        config_id: str = nextcord.SlashOption(
            description="Config-ID, z.B. cfg_1234567890.",
            required=True,
        ),
        delete_message: bool = nextcord.SlashOption(
            description="Soll die Discord-Nachricht ebenfalls gelöscht werden?",
            required=False,
            default=False,
        ),
    ) -> None:
        if not _has_selfrole_admin_permissions(interaction):
            await _deny(interaction)
            return

        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message(
                "Dieser Command ist nur auf einem Server nutzbar.",
                ephemeral=True,
            )
            return

        data = load_selfroles()
        guild_configs = data.get(str(interaction.guild_id), {})

        config = guild_configs.pop(config_id, None)
        if config is None:
            await interaction.response.send_message(
                "Keine Selfrole-Konfiguration mit dieser Config-ID gefunden.",
                ephemeral=True,
            )
            return

        save_selfroles(data)

        message_deleted = False
        if delete_message:
            channel = interaction.guild.get_channel(int(config["channel_id"]))
            if isinstance(channel, nextcord.TextChannel):
                try:
                    message = await channel.fetch_message(int(config["message_id"]))
                    await message.delete()
                    message_deleted = True
                except nextcord.NotFound:
                    pass

        await interaction.response.send_message(
            (
                f"Selfrole-Konfiguration `{config_id}` gelöscht.\n"
                f"Discord-Nachricht gelöscht: `{message_deleted}`"
            ),
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SelfrolesSlash(bot))