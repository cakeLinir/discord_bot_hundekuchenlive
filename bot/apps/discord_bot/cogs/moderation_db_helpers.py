from __future__ import annotations

from datetime import datetime, timezone, timedelta

from nextcord.ext import commands


def seconds_to_expires_at(duration_seconds: int | None) -> int | None:
    if duration_seconds is None:
        return None
    return int((datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)).timestamp())


async def log_warn(
    bot: commands.Bot,
    *,
    guild_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str | None,
) -> int:
    return await bot.db.log_moderation_action(
        guild_id=guild_id,
        target_user_id=target_user_id,
        moderator_user_id=moderator_user_id,
        action_type="warn",
        reason=reason,
    )


async def log_mute(
    bot: commands.Bot,
    *,
    guild_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str | None,
    duration_seconds: int | None = None,
) -> int:
    return await bot.db.log_moderation_action(
        guild_id=guild_id,
        target_user_id=target_user_id,
        moderator_user_id=moderator_user_id,
        action_type="mute",
        reason=reason,
        duration_seconds=duration_seconds,
        expires_at=seconds_to_expires_at(duration_seconds),
    )


async def log_timeout(
    bot: commands.Bot,
    *,
    guild_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str | None,
    duration_seconds: int | None = None,
) -> int:
    return await bot.db.log_moderation_action(
        guild_id=guild_id,
        target_user_id=target_user_id,
        moderator_user_id=moderator_user_id,
        action_type="timeout",
        reason=reason,
        duration_seconds=duration_seconds,
        expires_at=seconds_to_expires_at(duration_seconds),
    )


async def log_kick(
    bot: commands.Bot,
    *,
    guild_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str | None,
) -> int:
    return await bot.db.log_moderation_action(
        guild_id=guild_id,
        target_user_id=target_user_id,
        moderator_user_id=moderator_user_id,
        action_type="kick",
        reason=reason,
    )


async def log_ban(
    bot: commands.Bot,
    *,
    guild_id: int,
    target_user_id: int,
    moderator_user_id: int,
    reason: str | None,
) -> int:
    return await bot.db.log_moderation_action(
        guild_id=guild_id,
        target_user_id=target_user_id,
        moderator_user_id=moderator_user_id,
        action_type="ban",
        reason=reason,
    )


# Beispiel-Einbau in bestehende Commands:
#
# await log_warn(
#     self.bot,
#     guild_id=interaction.guild.id,
#     target_user_id=user.id,
#     moderator_user_id=interaction.user.id,
#     reason=reason,
# )