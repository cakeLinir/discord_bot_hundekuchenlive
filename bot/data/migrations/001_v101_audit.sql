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