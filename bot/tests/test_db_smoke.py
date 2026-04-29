from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

from core.db import Database


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.sqlite3")
        await db.connect()
        await db.setup_schema()

        await db.log_command(
            guild_id=1,
            channel_id=2,
            user_id=3,
            command_name="ping",
            command_type="slash",
        )

        action_id = await db.log_moderation_action(
            guild_id=1,
            target_user_id=3,
            moderator_user_id=4,
            action_type="warn",
            reason="smoke test",
        )

        summary = await db.get_user_summary(guild_id=1, user_id=3)
        assert summary["commands"] == 1
        assert summary["warn"] == 1
        assert action_id > 0

        rows = await db.filter_moderation_actions(guild_id=1, target_user_id=3)
        assert len(rows) == 1

        deleted = await db.delete_user_data(
            user_id=3,
            moderator_user_id=4,
            guild_id=1,
        )
        assert deleted.affected_rows >= 2

        await db.close()


if __name__ == "__main__":
    asyncio.run(main())