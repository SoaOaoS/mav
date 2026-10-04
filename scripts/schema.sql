-- ============================================================================
-- Mav — Postgres schema (idempotent, safe to re-run)
-- Applied by install.sh on first database start.
-- ============================================================================

-- ----------------------------------------------------------------- memory
CREATE TABLE IF NOT EXISTS conversations (
    id          bigserial PRIMARY KEY,
    chat_id     bigint  NOT NULL,
    session_id  text    NOT NULL,
    question    text    NOT NULL,
    answer      text    NOT NULL,
    ts          bigint  NOT NULL
);
-- source = where the exchange happened (dashboard…), agent = the helper that answered.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent  text;
-- Full-text index used by memory recall (bot/ocmemory.py).
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', question || ' ' || answer)) STORED;
CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations (chat_id);
CREATE INDEX IF NOT EXISTS idx_conv_ts   ON conversations (ts);
CREATE INDEX IF NOT EXISTS idx_conv_tsv  ON conversations USING gin (tsv);

CREATE TABLE IF NOT EXISTS facts (
    id       bigserial PRIMARY KEY,
    chat_id  bigint NOT NULL,
    fact     text   NOT NULL,
    source   text,
    ts       bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts (chat_id);

CREATE TABLE IF NOT EXISTS preferences (
    id       bigserial PRIMARY KEY,
    chat_id  bigint NOT NULL,
    key      text   NOT NULL,
    value    text   NOT NULL,
    ts       bigint NOT NULL,
    UNIQUE (chat_id, key)
);

-- ---------------------------------------------------------------- watch
CREATE TABLE IF NOT EXISTS watch_items (
    id            bigserial PRIMARY KEY,
    chat_id       bigint  NOT NULL,
    kind          text    NOT NULL,
    target        text    NOT NULL,
    last_state    text,
    last_checked  bigint,
    enabled       boolean DEFAULT true,
    ts            bigint  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_watch_chat ON watch_items (chat_id);

-- ---------------------------------------------------------------- RAG
CREATE TABLE IF NOT EXISTS documents (
    id       bigserial PRIMARY KEY,
    chat_id  bigint NOT NULL,
    title    text   NOT NULL,
    body     text   NOT NULL,
    source   text,
    ts       bigint NOT NULL,
    tsv      tsvector GENERATED ALWAYS AS (
                 to_tsvector('french', coalesce(title, '') || ' ' || coalesce(body, ''))
             ) STORED
);
CREATE INDEX IF NOT EXISTS idx_docs_chat ON documents (chat_id);
CREATE INDEX IF NOT EXISTS idx_docs_tsv  ON documents USING gin (tsv);

-- ---------------------------------------------------------------- notifications
CREATE TABLE IF NOT EXISTS notifications (
    id         bigserial PRIMARY KEY,
    ts         bigint  NOT NULL,
    chat_id    bigint,
    topic      text,
    title      text,
    body       text,
    dedup_key  text,
    channels   text[],
    delivered  boolean DEFAULT true
);
-- Where tapping the notification leads (e.g. the routine's chat).
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link text;
-- How much it deserved to interrupt the user (critical/important/useful/fyi).
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS level text;
CREATE INDEX IF NOT EXISTS notifications_ts_idx    ON notifications (ts DESC);
CREATE INDEX IF NOT EXISTS notifications_dedup_idx ON notifications (dedup_key, ts DESC);

-- ---------------------------------------------------------------- proactivity
-- Incoming events (bot/ocevents.py): what wakes a routine up besides time.
CREATE TABLE IF NOT EXISTS events (
    id        bigserial PRIMARY KEY,
    ts        bigint NOT NULL,
    kind      text,
    source    text,
    payload   jsonb,
    consumed  boolean DEFAULT false
);
CREATE INDEX IF NOT EXISTS events_pending_idx ON events (consumed, id);

-- Alerts below the user's proactivity bar: collected, then sent as one digest.
CREATE TABLE IF NOT EXISTS notify_digest (
    id       bigserial PRIMARY KEY,
    ts       bigint NOT NULL,
    chat_id  bigint,
    topic    text,
    title    text,
    body     text,
    level    text,
    sent     boolean DEFAULT false
);
CREATE INDEX IF NOT EXISTS notify_digest_idx ON notify_digest (sent, chat_id, ts);

-- Drafts proposed by Mav (bot/ocdrafts.py): a reply, a message, a note, ready
-- to review and send from the dashboard.
CREATE TABLE IF NOT EXISTS drafts (
    id       bigserial PRIMARY KEY,
    ts       bigint NOT NULL,
    chat_id  bigint,
    kind     text,
    title    text,
    body     text,
    status   text DEFAULT 'pending',
    source   text
);
CREATE INDEX IF NOT EXISTS drafts_status_idx ON drafts (status, ts DESC);

-- Background actions (bot/ocactions.py): long tasks running on their own.
CREATE TABLE IF NOT EXISTS actions (
    id       bigserial PRIMARY KEY,
    ts       bigint NOT NULL,
    chat_id  bigint,
    name     text,
    kind     text,
    status   text DEFAULT 'queued',
    result   text,
    link     text,
    updated  bigint
);
CREATE INDEX IF NOT EXISTS actions_status_idx ON actions (status, ts DESC);
