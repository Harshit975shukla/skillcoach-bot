CREATE TABLE usage_daily (
    learner_id text NOT NULL REFERENCES learners(id),
    day date NOT NULL,
    event text NOT NULL CHECK (event IN ('dashboard_open', 'lesson_page', 'course_page')),
    count integer NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (learner_id, day, event)
);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'skillcoach_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON usage_daily TO skillcoach_runtime;
    END IF;
END $$;
INSERT INTO schema_migrations(version) VALUES (10);
