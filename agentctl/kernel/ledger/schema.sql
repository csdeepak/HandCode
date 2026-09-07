-- Effect ledger. docs/0012 §2.1
--
-- synchronous = FULL is deliberate and non-negotiable: NORMAL can lose the
-- last commit on power failure, and that is exactly the record whose absence
-- causes a double effect.
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = FULL;

CREATE TABLE IF NOT EXISTS effect_record (
    tool_call_id     TEXT    PRIMARY KEY,
    conversation_id  TEXT    NOT NULL,
    turn_id          TEXT    NOT NULL,
    action_event_id  TEXT,
    tool_name        TEXT    NOT NULL,
    intent_hash      TEXT    NOT NULL,
    effect_class     TEXT    NOT NULL,
    state            TEXT    NOT NULL,
    fence_token      INTEGER NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 1,
    started_at       REAL    NOT NULL,
    committed_at     REAL,
    observation      BLOB,
    probe_verdict    TEXT,
    -- World fingerprint captured BEFORE execution, so a probe can later ask
    -- "did anything change?" without the tool having cooperated. docs/0016b
    pre_state        TEXT,
    error            TEXT,
    CHECK (state IN ('INTENT','COMMITTED','OBSERVED','FAILED','BLOCKED')),
    CHECK (effect_class IN
        ('PURE_READ','IDEMPOTENT_WRITE','NON_IDEMPOTENT_WRITE','EXTERNAL','DESTRUCTIVE'))
);

CREATE INDEX IF NOT EXISTS ix_effect_conv ON effect_record(conversation_id, turn_id);

-- The recovery scan: everything needing attention after a crash.
CREATE INDEX IF NOT EXISTS ix_effect_open ON effect_record(state)
    WHERE state IN ('INTENT','BLOCKED');

-- Fencing: one live writer per conversation.
CREATE TABLE IF NOT EXISTS lease (
    conversation_id TEXT PRIMARY KEY,
    holder          TEXT    NOT NULL,
    fence_token     INTEGER NOT NULL,
    expires_at      REAL    NOT NULL
);
