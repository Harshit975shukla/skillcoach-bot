ALTER TABLE learners ADD COLUMN last_job_at timestamptz NOT NULL DEFAULT '1970-01-01 00:00:00+00';
ALTER TABLE learners ADD COLUMN last_delivery_at timestamptz NOT NULL DEFAULT '1970-01-01 00:00:00+00';
INSERT INTO schema_migrations(version) VALUES (3);
