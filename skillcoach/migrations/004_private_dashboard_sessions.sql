CREATE TABLE dashboard_sessions (
    auth_hash text PRIMARY KEY,
    learner_id text NOT NULL REFERENCES learners(id),
    access_generation integer NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX dashboard_sessions_expiry ON dashboard_sessions(expires_at);
INSERT INTO schema_migrations(version) VALUES (4);
