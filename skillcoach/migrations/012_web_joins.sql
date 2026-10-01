-- Web invitations: a join request only becomes a pending learner after the address it names has been
-- confirmed with a one-time code in the same browser. Requests are deleted after two days.
CREATE TABLE web_joins (
    id text PRIMARY KEY,
    invite_id text NOT NULL REFERENCES invitations(id),
    email text NOT NULL
        CHECK (email = lower(email) AND length(email) <= 254 AND email LIKE '_%@_%._%'),
    email_hash text NOT NULL,
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
    verifier_hash text NOT NULL UNIQUE,
    code_hash text,
    attempts smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','consumed','rejected')),
    notified boolean NOT NULL DEFAULT false,
    learner_id text REFERENCES learners(id),
    requested_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX web_joins_invite ON web_joins(invite_id, requested_at);
CREATE INDEX web_joins_email ON web_joins(email_hash, requested_at);
CREATE INDEX web_joins_requested ON web_joins(requested_at);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_joins TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (12);
