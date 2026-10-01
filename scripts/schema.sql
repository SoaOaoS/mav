-- ============================================================================
-- Mav — schéma Postgres (idempotent, rejouable sans risque)
-- Appliqué par install.sh au premier démarrage de la base.
-- ============================================================================

-- ---------------------------------------------------------------- mémoire
CREATE TABLE IF NOT EXISTS conversations (
    id          bigserial PRIMARY KEY,
    chat_id     bigint  NOT NULL,
    session_id  text    NOT NULL,
    question    text    NOT NULL,
    answer      text    NOT NULL,
    ts          bigint  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations (chat_id);
CREATE INDEX IF NOT EXISTS idx_conv_ts   ON conversations (ts);

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

-- ---------------------------------------------------------------- veille
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
CREATE INDEX IF NOT EXISTS notifications_ts_idx    ON notifications (ts DESC);
CREATE INDEX IF NOT EXISTS notifications_dedup_idx ON notifications (dedup_key, ts DESC);
