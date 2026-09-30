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

CREATE TABLE web_sessions (
    token_hash text PRIMARY KEY,
    learner_id text NOT NULL REFERENCES learners(id),
    access_generation integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX web_sessions_learner ON web_sessions(learner_id, expires_at);

-- The web inbox pages through one learner's delivered messages in order.
CREATE INDEX outbox_learner_sequence ON outbox(learner_id, sequence);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_logins, web_sessions TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (11);
