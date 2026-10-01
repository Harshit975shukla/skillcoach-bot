-- Lesson videos for web mode, kept privately in this database (no public storage or CDN).
-- A media row starts as a capacity reservation ('reserved', with its writer's lease). Its chunks are
-- written in short transactions, and the row becomes 'ready' only after the stored chunks match the
-- declared size, count and SHA-256. Only 'ready' media are served, and only to a signed-in learner
-- whose sent message in the current access generation references them (web_media_refs).
-- Video bytes are derivatives of stored lesson data: they can be rendered again and are not part of
-- the learner state that backups must restore byte for byte.
CREATE TABLE web_media (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    asset_key text NOT NULL CHECK (asset_key ~ '^[0-9a-f]{64}:[a-z]+$'),
    role text NOT NULL CHECK (role IN ('video', 'poster', 'image')),
    learner_id text REFERENCES learners(id),
    mime text NOT NULL CHECK (mime IN ('video/mp4', 'image/png')),
    bytes integer NOT NULL CHECK (bytes BETWEEN 1 AND 3670016),
    chunks smallint NOT NULL CHECK (chunks BETWEEN 1 AND 8),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved', 'ready')),
    lease text,
    reserved_until timestamptz,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((state = 'reserved') = (lease IS NOT NULL AND reserved_until IS NOT NULL)),
    CHECK ((role = 'video' AND mime = 'video/mp4')
        OR (role <> 'video' AND mime = 'image/png' AND bytes <= 524288))
);
CREATE UNIQUE INDEX web_media_identity ON web_media(asset_key, role);
CREATE INDEX web_media_used ON web_media(last_used_at);

CREATE TABLE web_media_chunks (
    media_id text NOT NULL REFERENCES web_media(id) ON DELETE CASCADE,
    seq smallint NOT NULL CHECK (seq BETWEEN 0 AND 7),
    data bytea NOT NULL CHECK (octet_length(data) BETWEEN 1 AND 524288),
    PRIMARY KEY (media_id, seq)
);

-- Which sent message shows which media: the only authority for serving a media row.
CREATE TABLE web_media_refs (
    outbox_id text NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('video', 'poster', 'image')),
    media_id text NOT NULL REFERENCES web_media(id) ON DELETE CASCADE,
    PRIMARY KEY (outbox_id, role)
);
CREATE INDEX web_media_refs_media ON web_media_refs(media_id);

-- Bytes returned to each learner per IST day; reserved before a response is read or sent.
CREATE TABLE web_media_usage (
    learner_id text NOT NULL REFERENCES learners(id),
    day date NOT NULL,
    bytes bigint NOT NULL DEFAULT 0 CHECK (bytes >= 0),
    PRIMARY KEY (learner_id, day)
);

-- The single, globally rate-limited request to start a rendering worker for on-demand lessons.
CREATE TABLE web_media_wake (
    id smallint PRIMARY KEY CHECK (id = 1),
    requested_at timestamptz NOT NULL DEFAULT '-infinity',
    day date,
    count integer NOT NULL DEFAULT 0 CHECK (count >= 0)
);
INSERT INTO web_media_wake(id) VALUES (1);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_media, web_media_chunks, web_media_refs,
            web_media_usage, web_media_wake TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (14);
