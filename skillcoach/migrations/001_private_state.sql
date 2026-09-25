CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE coach_state (
    id integer PRIMARY KEY CHECK (id = 1),
    revision bigint NOT NULL DEFAULT 0,
    displayed_target jsonb,
    body jsonb NOT NULL
);
INSERT INTO coach_state(id, body) VALUES (1, '{}');

CREATE TABLE worker_leases (
    name text PRIMARY KEY,
    token text,
    expires_at timestamptz NOT NULL DEFAULT '-infinity'
);
INSERT INTO worker_leases(name) VALUES ('domain'), ('delivery');

CREATE TABLE jobs (
    id text PRIMARY KEY,
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'failed', 'done', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    error_code text
);
CREATE INDEX jobs_ready ON jobs(status, available_at, sequence);

CREATE TABLE ai_results (
    job_id text NOT NULL REFERENCES jobs(id),
    operation text NOT NULL,
    body jsonb NOT NULL,
    PRIMARY KEY (job_id, operation)
);

CREATE TABLE task_keys (
    id text PRIMARY KEY,
    origin text NOT NULL UNIQUE
);
CREATE TABLE answer_keys (
    session_id text NOT NULL,
    question_id text NOT NULL,
    job_id text NOT NULL REFERENCES jobs(id),
    PRIMARY KEY(session_id, question_id)
);

CREATE TABLE outbox (
    id text PRIMARY KEY,
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    job_id text NOT NULL REFERENCES jobs(id),
    body jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent', 'suppressed', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    error_code text,
    delivered_at timestamptz
);
CREATE INDEX outbox_ready ON outbox(status, sequence);

INSERT INTO schema_migrations(version) VALUES (1);
