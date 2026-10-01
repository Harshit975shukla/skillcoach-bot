-- Web push: one row per browser push subscription that a learner turned on. A row delivers only
-- while its learner, access generation, sign-in address and web session are all still current.
-- Every (re)binding gets a new id, so cleanup of an older notification never touches a newer one.
CREATE TABLE web_push_subscriptions (
    id text PRIMARY KEY,
    endpoint_hash text NOT NULL UNIQUE,
    endpoint text NOT NULL CHECK (length(endpoint) <= 1024 AND endpoint LIKE 'https://%'),
    p256dh text NOT NULL CHECK (length(p256dh) = 87),
    auth text NOT NULL CHECK (length(auth) = 22),
    learner_id text NOT NULL REFERENCES learners(id),
    access_generation integer NOT NULL,
    email_hash text NOT NULL,
    session_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_sent_at timestamptz
);
CREATE INDEX web_push_subscriptions_learner ON web_push_subscriptions(learner_id, created_at);
CREATE INDEX web_push_subscriptions_session ON web_push_subscriptions(session_hash);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_push_subscriptions TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (13);
