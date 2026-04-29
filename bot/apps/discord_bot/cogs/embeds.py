from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlparse

import nextcord
from nextcord import SlashOption
from nextcord.ext import commands

# ---------------------------------------------------------------------------
# Discord Embed Limits
# Quelle: Discord API Limits, hier technisch defensiv umgesetzt.
# ---------------------------------------------------------------------------

MAX_TITLE_LENGTH = 256
MAX_DESCRIPTION_LENGTH = 4096
MAX_FOOTER_LENGTH = 2048
MAX_AUTHOR_LENGTH = 256
MAX_TOTAL_EMBED_CHARS = 6000

HEX_COLOR_REGEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_manage_guild_member(interaction: nextcord.Interaction) -> bool:
    user = interaction.user

    if not isinstance(user, nextcord.Member):
        return False

    return bool(
        user.guild_permissions.manage_guild
        or user.guild_permissions.administrator
    )


async def _deny(interaction: nextcord.Interaction) -> None:
    await interaction.response.send_message(
        "Du brauchst die Berechtigung **Server verwalten**, um Embeds zu verwalten.",
        ephemeral=True,
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()
    return value or None


def _truncate(value: str | None, limit: int) -> str | None:
    value = _clean_optional(value)
    if value is None:
        return None

    return value[:limit]


def _parse_color(color_hex: str | None) -> tuple[nextcord.Color, str | None]:
    color_hex = _clean_optional(color_hex) or "#00ffcc"

    if not HEX_COLOR_REGEX.fullmatch(color_hex):
        return nextcord.Color.red(), "Ungültige Farbe. Fallback `rot` wurde verwendet."

    clean = color_hex.replace("#", "")
    return nextcord.Color(int(clean, 16)), None


def _is_valid_http_url(url: str | None) -> bool:
    url = _clean_optional(url)
    if url is None:
        return True

    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_urls(*urls: str | None) -> str | None:
    for url in urls:
        clean = _clean_optional(url)
        if clean and not _is_valid_http_url(clean):
            return f"Ungültige URL: `{clean}`. Erlaubt sind nur `http://` und `https://`."
    return None


def _is_sendable_channel(channel: object) -> bool:
    return isinstance(
        channel,
        (
            nextcord.TextChannel,
            nextcord.Thread,
        ),
    )


def _embed_total_length(
    *,
    title: str | None,
    description: str | None,
    footer: str | None,
    author_name: str | None,
) -> int:
    return sum(
        len(value or "")
        for value in (
            title,
            description,
            footer,
            author_name,
        )
    )


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Embeds(commands.Cog):
    """Slash-Commands zum Erstellen, Senden und Bearbeiten von Embeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    # Logging optional
    # ------------------------------------------------------------------ #

    async def _db_log_embed_action(
        self,
        *,
        interaction: nextcord.Interaction,
        action: str,
        target_channel_id: int | None = None,
        message_id: int | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        db = getattr(self.bot, "db", None)
        if db is None:
            return

        try:
            await db.log_command(
                guild_id=interaction.guild.id if interaction.guild else None,
                channel_id=target_channel_id or (interaction.channel.id if interaction.channel else None),
                user_id=interaction.user.id,
                command_name=f"embed_{action}",
                command_type="slash",
                success=success,
                error=error if error else (f"message_id={message_id}" if message_id else None),
            )
        except Exception:
            # DB-Logging darf den eigentlichen Command nicht blockieren.
            pass

    # ------------------------------------------------------------------ #
    # Embed Builder
    # ------------------------------------------------------------------ #

    def _build_embed(
        self,
        *,
        title: str,
        description: str,
        color_hex: str | None = "#00ffcc",
        footer: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        title_url: str | None = None,
        author_name: str | None = None,
        author_icon_url: str | None = None,
        add_timestamp: bool = True,
    ) -> tuple[nextcord.Embed, str | None]:
        """Erstellt ein Embed und gibt optional eine Warnung zurück."""

        title = (_truncate(title, MAX_TITLE_LENGTH) or "Embed")
        description = (_truncate(description, MAX_DESCRIPTION_LENGTH) or "-")
        footer = _truncate(footer, MAX_FOOTER_LENGTH)
        author_name = _truncate(author_name, MAX_AUTHOR_LENGTH)

        color, color_warning = _parse_color(color_hex)

        total_length = _embed_total_length(
            title=title,
            description=description,
            footer=footer,
            author_name=author_name,
        )

        if total_length > MAX_TOTAL_EMBED_CHARS:
            description = description[: max(0, MAX_TOTAL_EMBED_CHARS - len(title) - len(footer or "") - len(author_name or ""))]

        embed = nextcord.Embed(
            title=title,
            description=description,
            color=color,
            url=_clean_optional(title_url),
        )

        if add_timestamp:
            embed.timestamp = _utcnow()

        if footer:
            embed.set_footer(text=footer)

        if image_url:
            embed.set_image(url=image_url.strip())

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url.strip())

        if author_name:
            if author_icon_url:
                embed.set_author(
                    name=author_name,
                    icon_url=author_icon_url.strip(),
                )
            else:
                embed.set_author(name=author_name)

        return embed, color_warning

    async def _build_or_respond_error(
        self,
        interaction: nextcord.Interaction,
        *,
        titel: str,
        beschreibung: str,
        farbe: str | None,
        footer: str | None,
        bild_url: str | None,
        thumbnail_url: str | None,
        titel_url: str | None,
        author_name: str | None,
        author_icon_url: str | None,
        timestamp: bool,
    ) -> tuple[nextcord.Embed | None, str | None]:
        url_error = _validate_urls(
            bild_url,
            thumbnail_url,
            titel_url,
            author_icon_url,
        )
        if url_error:
            await interaction.response.send_message(url_error, ephemeral=True)
            return None, None

        embed, warning = self._build_embed(
            title=titel,
            description=beschreibung,
            color_hex=farbe,
            footer=footer,
            image_url=_clean_optional(bild_url),
            thumbnail_url=_clean_optional(thumbnail_url),
            title_url=_clean_optional(titel_url),
            author_name=_clean_optional(author_name),
            author_icon_url=_clean_optional(author_icon_url),
            add_timestamp=timestamp,
        )

        return embed, warning

    # ------------------------------------------------------------------ #
    # /embed Gruppe
    # ------------------------------------------------------------------ #

    @nextcord.slash_command(
        name="embed",
        description="Erstelle, sende oder bearbeite Embeds.",
    )
    async def embed_group(self, interaction: nextcord.Interaction) -> None:
        pass

    # ------------------------------------------------------------------ #
    # /embed preview
    # ------------------------------------------------------------------ #

    @embed_group.subcommand(
        name="preview",
        description="Zeigt dir eine Vorschau eines Embeds.",
    )
    async def embed_preview(
        self,
        interaction: nextcord.Interaction,
        titel: str = SlashOption(
            description="Titel des Embeds.",
            required=True,
        ),
        beschreibung: str = SlashOption(
            description="Beschreibung / Inhalt des Embeds.",
            required=True,
        ),
        farbe: str = SlashOption(
            description="Farbe als Hex, z.B. #ff9900.",
            required=False,
            default="#00ffcc",
        ),
        footer: str | None = SlashOption(
            description="Footer-Text.",
            required=False,
            default=None,
        ),
        bild_url: str | None = SlashOption(
            description="Bild-URL.",
            required=False,
            default=None,
        ),
        thumbnail_url: str | None = SlashOption(
            description="Thumbnail-URL.",
            required=False,
            default=None,
        ),
        titel_url: str | None = SlashOption(
            description="Klickbarer Link im Embed-Titel.",
            required=False,
            default=None,
        ),
        author_name: str | None = SlashOption(
            description="Author-Name oben im Embed.",
            required=False,
            default=None,
        ),
        author_icon_url: str | None = SlashOption(
            description="Icon-URL für den Author.",
            required=False,
            default=None,
        ),
        timestamp: bool = SlashOption(
            description="Aktuelle Uhrzeit im Embed anzeigen?",
            required=False,
            default=True,
        ),
    ) -> None:
        if not _is_manage_guild_member(interaction):
            await _deny(interaction)
            return

        embed, warning = await self._build_or_respond_error(
            interaction,
            titel=titel,
            beschreibung=beschreibung,
            farbe=farbe,
            footer=footer,
            bild_url=bild_url,
            thumbnail_url=thumbnail_url,
            titel_url=titel_url,
            author_name=author_name,
            author_icon_url=author_icon_url,
            timestamp=timestamp,
        )

        if embed is None:
            return

        content = "Hier ist deine Embed-Vorschau:"
        if warning:
            content += f"\nHinweis: {warning}"

        await interaction.response.send_message(
            content=content,
            embed=embed,
            ephemeral=True,
        )

        await self._db_log_embed_action(
            interaction=interaction,
            action="preview",
            success=True,
        )

    # ------------------------------------------------------------------ #
    # /embed send
    # ------------------------------------------------------------------ #

    @embed_group.subcommand(
        name="send",
        description="Sendet ein Embed in einen ausgewählten Channel.",
    )
    async def embed_send(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.abc.GuildChannel = SlashOption(
            description="Channel, in den das Embed gesendet werden soll.",
            required=True,
        ),
        titel: str = SlashOption(
            description="Titel des Embeds.",
            required=True,
        ),
        beschreibung: str = SlashOption(
            description="Beschreibung / Inhalt des Embeds.",
            required=True,
        ),
        farbe: str = SlashOption(
            description="Farbe als Hex, z.B. #ff9900.",
            required=False,
            default="#00ffcc",
        ),
        footer: str | None = SlashOption(
            description="Footer-Text.",
            required=False,
            default=None,
        ),
        bild_url: str | None = SlashOption(
            description="Bild-URL.",
            required=False,
            default=None,
        ),
        thumbnail_url: str | None = SlashOption(
            description="Thumbnail-URL.",
            required=False,
            default=None,
        ),
        titel_url: str | None = SlashOption(
            description="Klickbarer Link im Embed-Titel.",
            required=False,
            default=None,
        ),
        author_name: str | None = SlashOption(
            description="Author-Name oben im Embed.",
            required=False,
            default=None,
        ),
        author_icon_url: str | None = SlashOption(
            description="Icon-URL für den Author.",
            required=False,
            default=None,
        ),
        timestamp: bool = SlashOption(
            description="Aktuelle Uhrzeit im Embed anzeigen?",
            required=False,
            default=True,
        ),
    ) -> None:
        if not _is_manage_guild_member(interaction):
            await _deny(interaction)
            return

        if not _is_sendable_channel(channel):
            await interaction.response.send_message(
                "Bitte wähle einen Textkanal oder Thread aus.",
                ephemeral=True,
            )
            return

        embed, warning = await self._build_or_respond_error(
            interaction,
            titel=titel,
            beschreibung=beschreibung,
            farbe=farbe,
            footer=footer,
            bild_url=bild_url,
            thumbnail_url=thumbnail_url,
            titel_url=titel_url,
            author_name=author_name,
            author_icon_url=author_icon_url,
            timestamp=timestamp,
        )

        if embed is None:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            message = await channel.send(embed=embed)

            response = f"Embed wurde in {channel.mention} gesendet.\nMessage-ID: `{message.id}`"
            if warning:
                response += f"\nHinweis: {warning}"

            await interaction.followup.send(response, ephemeral=True)

            await self._db_log_embed_action(
                interaction=interaction,
                action="send",
                target_channel_id=channel.id,
                message_id=message.id,
                success=True,
            )

        except nextcord.Forbidden:
            await interaction.followup.send(
                "Ich habe keine Berechtigung, in diesen Channel zu schreiben.",
                ephemeral=True,
            )
            await self._db_log_embed_action(
                interaction=interaction,
                action="send",
                target_channel_id=channel.id,
                success=False,
                error="Forbidden",
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Embed konnte nicht gesendet werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )
            await self._db_log_embed_action(
                interaction=interaction,
                action="send",
                target_channel_id=channel.id,
                success=False,
                error=type(exc).__name__,
            )

    # ------------------------------------------------------------------ #
    # /embed edit
    # ------------------------------------------------------------------ #

    @embed_group.subcommand(
        name="edit",
        description="Bearbeitet ein bestehendes Bot-Embed per Message-ID.",
    )
    async def embed_edit(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.abc.GuildChannel = SlashOption(
            description="Channel, in dem die Nachricht liegt.",
            required=True,
        ),
        message_id: str = SlashOption(
            description="Message-ID der zu bearbeitenden Bot-Nachricht.",
            required=True,
        ),
        titel: str = SlashOption(
            description="Neuer Titel des Embeds.",
            required=True,
        ),
        beschreibung: str = SlashOption(
            description="Neue Beschreibung / Inhalt des Embeds.",
            required=True,
        ),
        farbe: str = SlashOption(
            description="Farbe als Hex, z.B. #ff9900.",
            required=False,
            default="#00ffcc",
        ),
        footer: str | None = SlashOption(
            description="Footer-Text.",
            required=False,
            default=None,
        ),
        bild_url: str | None = SlashOption(
            description="Bild-URL.",
            required=False,
            default=None,
        ),
        thumbnail_url: str | None = SlashOption(
            description="Thumbnail-URL.",
            required=False,
            default=None,
        ),
        titel_url: str | None = SlashOption(
            description="Klickbarer Link im Embed-Titel.",
            required=False,
            default=None,
        ),
        author_name: str | None = SlashOption(
            description="Author-Name oben im Embed.",
            required=False,
            default=None,
        ),
        author_icon_url: str | None = SlashOption(
            description="Icon-URL für den Author.",
            required=False,
            default=None,
        ),
        timestamp: bool = SlashOption(
            description="Aktuelle Uhrzeit im Embed anzeigen?",
            required=False,
            default=True,
        ),
    ) -> None:
        if not _is_manage_guild_member(interaction):
            await _deny(interaction)
            return

        if not _is_sendable_channel(channel):
            await interaction.response.send_message(
                "Bitte wähle einen Textkanal oder Thread aus.",
                ephemeral=True,
            )
            return

        if not message_id.isdigit():
            await interaction.response.send_message(
                "Die Message-ID muss numerisch sein.",
                ephemeral=True,
            )
            return

        embed, warning = await self._build_or_respond_error(
            interaction,
            titel=titel,
            beschreibung=beschreibung,
            farbe=farbe,
            footer=footer,
            bild_url=bild_url,
            thumbnail_url=thumbnail_url,
            titel_url=titel_url,
            author_name=author_name,
            author_icon_url=author_icon_url,
            timestamp=timestamp,
        )

        if embed is None:
            return

        await interaction.response.defer(ephemeral=True)

        try:
            message = await channel.fetch_message(int(message_id))

            if self.bot.user is not None and message.author.id != self.bot.user.id:
                await interaction.followup.send(
                    "Ich bearbeite nur Nachrichten, die von diesem Bot gesendet wurden.",
                    ephemeral=True,
                )
                return

            await message.edit(embed=embed)

            response = f"Embed wurde bearbeitet.\nMessage-ID: `{message.id}`"
            if warning:
                response += f"\nHinweis: {warning}"

            await interaction.followup.send(response, ephemeral=True)

            await self._db_log_embed_action(
                interaction=interaction,
                action="edit",
                target_channel_id=channel.id,
                message_id=message.id,
                success=True,
            )

        except nextcord.NotFound:
            await interaction.followup.send(
                "Nachricht nicht gefunden.",
                ephemeral=True,
            )
            await self._db_log_embed_action(
                interaction=interaction,
                action="edit",
                target_channel_id=channel.id,
                success=False,
                error="NotFound",
            )

        except nextcord.Forbidden:
            await interaction.followup.send(
                "Ich habe keine Berechtigung, diese Nachricht zu lesen oder zu bearbeiten.",
                ephemeral=True,
            )
            await self._db_log_embed_action(
                interaction=interaction,
                action="edit",
                target_channel_id=channel.id,
                success=False,
                error="Forbidden",
            )

        except Exception as exc:
            await interaction.followup.send(
                f"Embed konnte nicht bearbeitet werden: `{type(exc).__name__}: {exc}`",
                ephemeral=True,
            )
            await self._db_log_embed_action(
                interaction=interaction,
                action="edit",
                target_channel_id=channel.id,
                success=False,
                error=type(exc).__name__,
            )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Embeds(bot))