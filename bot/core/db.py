from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

import aiosqlite


ModerationActionType = Literal[
    "warn",
    "mute",
    "timeout",
    "kick",
    "ban",
    "unmute",
    "untimeout",
    "unban",
    "note",
    "other",
]

VALID_MODERATION_ACTIONS: set[str] = {
    "warn",
    "mute",
    "timeout",
    "kick",
    "ban",
    "unmute",
    "untimeout",
    "unban",
    "note",
    "other",
}


def utc_timestamp() -> int:
    """Return current UTC timestamp in seconds."""
    return int(time.time())


def timestamp_to_iso(ts: int | None) -> str | None:
    """Convert a stored UTC timestamp to ISO-8601."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@dataclass(slots=True)
class DeletionResult:
    affected_rows: int
    command_logs: int
    moderation_actions: int
    user_notes: int
    deletion_audit: int = 0


class Database:
    """
    Async SQLite database wrapper for Bot V1.0.1.

    Stores:
    - command usage
    - moderation actions
    - optional user notes
    - deletion audit entries

    Retention:
    - delete_old_user_data() removes stored user-related rows older than N days.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.conn is not None:
            return

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

        # WAL improves concurrent read/write behavior for a bot process.
        await self.conn.execute("PRAGMA journal_mode = WAL;")
        await self.conn.execute("PRAGMA foreign_keys = ON;")
        await self.conn.execute("PRAGMA busy_timeout = 5000;")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    def require_conn(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database connection is not initialized. Call connect() first.")
        return self.conn

    async def setup_schema(self) -> None:
        db = self.require_conn()
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS command_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                user_id INTEGER NOT NULL,
                command_name TEXT NOT NULL,
                command_type TEXT NOT NULL DEFAULT 'unknown',
                success INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS moderation_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                moderator_user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                reason TEXT,
                duration_seconds INTEGER,
                expires_at INTEGER,
                created_at INTEGER NOT NULL,
                CHECK (action_type IN (
                    'warn',
                    'mute',
                    'timeout',
                    'kick',
                    'ban',
                    'unmute',
                    'untimeout',
                    'unban',
                    'note',
                    'other'
                ))
            );

            CREATE TABLE IF NOT EXISTS user_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_user_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deletion_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moderator_user_id INTEGER,
                deletion_type TEXT NOT NULL,
                affected_rows INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_command_logs_user_id ON command_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_command_logs_created_at ON command_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_command_logs_command_name ON command_logs(command_name);

            CREATE INDEX IF NOT EXISTS idx_mod_actions_target_user_id ON moderation_actions(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_mod_actions_moderator_user_id ON moderation_actions(moderator_user_id);
            CREATE INDEX IF NOT EXISTS idx_mod_actions_action_type ON moderation_actions(action_type);
            CREATE INDEX IF NOT EXISTS idx_mod_actions_created_at ON moderation_actions(created_at);

            CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_notes_created_at ON user_notes(created_at);

            CREATE INDEX IF NOT EXISTS idx_deletion_audit_created_at ON deletion_audit(created_at);
            """
        )
        await db.commit()

    async def log_command(
        self,
        *,
        user_id: int,
        command_name: str,
        guild_id: int | None = None,
        channel_id: int | None = None,
        command_type: str = "unknown",
        success: bool = True,
        error: str | None = None,
        created_at: int | None = None,
    ) -> None:
        db = self.require_conn()
        await db.execute(
            """
            INSERT INTO command_logs (
                guild_id, channel_id, user_id, command_name,
                command_type, success, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                user_id,
                command_name[:128],
                command_type[:32],
                int(success),
                error[:500] if error else None,
                created_at or utc_timestamp(),
            ),
        )
        await db.commit()

    async def log_moderation_action(
        self,
        *,
        guild_id: int,
        target_user_id: int,
        moderator_user_id: int,
        action_type: ModerationActionType | str,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: int | None = None,
        created_at: int | None = None,
    ) -> int:
        if action_type not in VALID_MODERATION_ACTIONS:
            raise ValueError(f"Invalid moderation action_type: {action_type!r}")

        db = self.require_conn()
        cursor = await db.execute(
            """
            INSERT INTO moderation_actions (
                guild_id, target_user_id, moderator_user_id,
                action_type, reason, duration_seconds, expires_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                target_user_id,
                moderator_user_id,
                action_type,
                reason[:1000] if reason else None,
                duration_seconds,
                expires_at,
                created_at or utc_timestamp(),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)

    async def add_user_note(
        self,
        *,
        guild_id: int,
        user_id: int,
        moderator_user_id: int,
        note: str,
        created_at: int | None = None,
    ) -> int:
        db = self.require_conn()
        now = created_at or utc_timestamp()

        cursor = await db.execute(
            """
            INSERT INTO user_notes (
                guild_id, user_id, moderator_user_id, note, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, moderator_user_id, note[:1500], now),
        )

        await db.execute(
            """
            INSERT INTO moderation_actions (
                guild_id, target_user_id, moderator_user_id,
                action_type, reason, duration_seconds, expires_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, moderator_user_id, "note", note[:1000], None, None, now),
        )

        await db.commit()
        return int(cursor.lastrowid)

    async def filter_moderation_actions(
        self,
        *,
        guild_id: int,
        target_user_id: int | None = None,
        moderator_user_id: int | None = None,
        action_type: str | None = None,
        since_timestamp: int | None = None,
        until_timestamp: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        db = self.require_conn()

        query = "SELECT * FROM moderation_actions WHERE guild_id = ?"
        params: list[Any] = [guild_id]

        if target_user_id is not None:
            query += " AND target_user_id = ?"
            params.append(target_user_id)

        if moderator_user_id is not None:
            query += " AND moderator_user_id = ?"
            params.append(moderator_user_id)

        if action_type is not None:
            query += " AND action_type = ?"
            params.append(action_type)

        if since_timestamp is not None:
            query += " AND created_at >= ?"
            params.append(since_timestamp)

        if until_timestamp is not None:
            query += " AND created_at <= ?"
            params.append(until_timestamp)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def filter_command_logs(
        self,
        *,
        guild_id: int | None = None,
        user_id: int | None = None,
        command_name: str | None = None,
        success: bool | None = None,
        since_timestamp: int | None = None,
        until_timestamp: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        db = self.require_conn()

        query = "SELECT * FROM command_logs WHERE 1 = 1"
        params: list[Any] = []

        if guild_id is not None:
            query += " AND guild_id = ?"
            params.append(guild_id)

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        if command_name is not None:
            query += " AND command_name LIKE ?"
            params.append(f"%{command_name}%")

        if success is not None:
            query += " AND success = ?"
            params.append(int(success))

        if since_timestamp is not None:
            query += " AND created_at >= ?"
            params.append(since_timestamp)

        if until_timestamp is not None:
            query += " AND created_at <= ?"
            params.append(until_timestamp)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def get_user_summary(self, *, guild_id: int, user_id: int) -> dict[str, int]:
        db = self.require_conn()

        result: dict[str, int] = {
            "commands": 0,
            "warn": 0,
            "mute": 0,
            "timeout": 0,
            "kick": 0,
            "ban": 0,
            "notes": 0,
            "moderation_total": 0,
        }

        async with db.execute(
            "SELECT COUNT(*) AS count FROM command_logs WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            result["commands"] = int(row["count"] if row else 0)

        async with db.execute(
            """
            SELECT action_type, COUNT(*) AS count
            FROM moderation_actions
            WHERE guild_id = ? AND target_user_id = ?
            GROUP BY action_type
            """,
            (guild_id, user_id),
        ) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            action_type = row["action_type"]
            count = int(row["count"])
            result["moderation_total"] += count
            if action_type in result:
                result[action_type] = count

        async with db.execute(
            "SELECT COUNT(*) AS count FROM user_notes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            result["notes"] = int(row["count"] if row else 0)

        return result

    async def delete_old_user_data(self, *, retention_days: int = 30) -> DeletionResult:
        cutoff = utc_timestamp() - (retention_days * 24 * 60 * 60)
        return await self._delete_by_cutoff(cutoff=cutoff, retention_days=retention_days)

    async def _delete_by_cutoff(self, *, cutoff: int, retention_days: int) -> DeletionResult:
        db = self.require_conn()

        command_logs = await self._delete_from_table(
            "command_logs",
            "created_at < ?",
            (cutoff,),
        )
        moderation_actions = await self._delete_from_table(
            "moderation_actions",
            "created_at < ?",
            (cutoff,),
        )
        user_notes = await self._delete_from_table(
            "user_notes",
            "created_at < ?",
            (cutoff,),
        )

        # Also keep deletion audit short-lived. It contains moderator IDs.
        deletion_audit = await self._delete_from_table(
            "deletion_audit",
            "created_at < ?",
            (cutoff,),
        )

        affected_rows = command_logs + moderation_actions + user_notes + deletion_audit

        await db.execute(
            """
            INSERT INTO deletion_audit (
                moderator_user_id, deletion_type, affected_rows, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (None, f"auto_retention_{retention_days}_days", affected_rows, utc_timestamp()),
        )
        await db.commit()

        return DeletionResult(
            affected_rows=affected_rows,
            command_logs=command_logs,
            moderation_actions=moderation_actions,
            user_notes=user_notes,
            deletion_audit=deletion_audit,
        )

    async def delete_user_data(
        self,
        *,
        user_id: int,
        moderator_user_id: int,
        guild_id: int | None = None,
        include_as_moderator: bool = False,
    ) -> DeletionResult:
        db = self.require_conn()

        guild_clause = ""
        guild_params: tuple[int, ...] = ()
        if guild_id is not None:
            guild_clause = " AND guild_id = ?"
            guild_params = (guild_id,)

        command_logs = await self._delete_from_table(
            "command_logs",
            f"user_id = ?{guild_clause}",
            (user_id, *guild_params),
        )

        moderation_actions = await self._delete_from_table(
            "moderation_actions",
            f"target_user_id = ?{guild_clause}",
            (user_id, *guild_params),
        )

        user_notes = await self._delete_from_table(
            "user_notes",
            f"user_id = ?{guild_clause}",
            (user_id, *guild_params),
        )

        if include_as_moderator:
            moderation_actions += await self._delete_from_table(
                "moderation_actions",
                f"moderator_user_id = ?{guild_clause}",
                (user_id, *guild_params),
            )
            user_notes += await self._delete_from_table(
                "user_notes",
                f"moderator_user_id = ?{guild_clause}",
                (user_id, *guild_params),
            )

        affected_rows = command_logs + moderation_actions + user_notes

        await db.execute(
            """
            INSERT INTO deletion_audit (
                moderator_user_id, deletion_type, affected_rows, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                moderator_user_id,
                "manual_user_delete",
                affected_rows,
                utc_timestamp(),
            ),
        )
        await db.commit()

        return DeletionResult(
            affected_rows=affected_rows,
            command_logs=command_logs,
            moderation_actions=moderation_actions,
            user_notes=user_notes,
        )

    async def delete_moderation_action_by_id(
        self,
        *,
        action_id: int,
        moderator_user_id: int,
        guild_id: int,
    ) -> int:
        deleted = await self._delete_from_table(
            "moderation_actions",
            "id = ? AND guild_id = ?",
            (action_id, guild_id),
        )

        db = self.require_conn()
        await db.execute(
            """
            INSERT INTO deletion_audit (
                moderator_user_id, deletion_type, affected_rows, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (moderator_user_id, "manual_moderation_action_delete", deleted, utc_timestamp()),
        )
        await db.commit()

        return deleted

    async def _delete_from_table(
        self,
        table: str,
        where_sql: str,
        params: Iterable[Any],
    ) -> int:
        allowed_tables = {
            "command_logs",
            "moderation_actions",
            "user_notes",
            "deletion_audit",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsafe table name: {table!r}")

        db = self.require_conn()
        cursor = await db.execute(f"DELETE FROM {table} WHERE {where_sql}", tuple(params))
        return int(cursor.rowcount if cursor.rowcount != -1 else 0)

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
        data = dict(row)

        for field in ("created_at", "expires_at"):
            if field in data:
                data[f"{field}_iso"] = timestamp_to_iso(data[field])

        return data