ALTER TABLE learners ADD COLUMN email text
    CHECK (email IS NULL OR (email = lower(email) AND length(email) <= 254 AND email LIKE '_%@_%._%'));
CREATE UNIQUE INDEX learners_email ON learners(email) WHERE email IS NOT NULL;

CREATE TABLE web_logins (
    id text PRIMARY KEY,
    email_hash text NOT NULL,
    learner_id text REFERENCES learners(id),
    verifier_hash text NOT NULL UNIQUE,
    code_hash text,
    attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','consumed','rejected')),
    notified boolean NOT NULL DEFAULT false,
    requested_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX web_logins_email ON web_logins(email_hash, requested_at);
CREATE INDEX web_logins_requested ON web_logins(requested_at);

-- A session stays valid only while the learner still signs in with the same address.
CREATE TABLE web_sessions (
    token_hash text PRIMARY KEY,
    learner_id text NOT NULL REFERENCES learners(id),
    access_generation integer NOT NULL,
    email_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX web_sessions_learner ON web_sessions(learner_id, expires_at);

-- Delivery order, not insertion order: retried or recovered messages are sent later than newer
-- ones, and the web inbox must still show them. Existing sent messages keep their delivery order.
CREATE SEQUENCE outbox_delivery_order;
ALTER TABLE outbox ADD COLUMN delivered_seq bigint;
WITH ordered AS (
    SELECT id, row_number() OVER (ORDER BY delivered_at NULLS FIRST, sequence) AS position
    FROM outbox WHERE status = 'sent'
)
UPDATE outbox o SET delivered_seq = ordered.position FROM ordered WHERE o.id = ordered.id;
SELECT setval('outbox_delivery_order', COALESCE((SELECT max(delivered_seq) FROM outbox), 0) + 1, false);
CREATE INDEX outbox_learner_delivered ON outbox(learner_id, delivered_seq) WHERE delivered_seq IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_logins, web_sessions TO skillcoach_runtime;
        GRANT USAGE, SELECT ON SEQUENCE outbox_delivery_order TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (11);
