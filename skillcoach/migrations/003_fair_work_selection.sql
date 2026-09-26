ALTER TABLE learners ADD COLUMN last_job_at timestamptz NOT NULL DEFAULT '-infinity';
ALTER TABLE learners ADD COLUMN last_delivery_at timestamptz NOT NULL DEFAULT '-infinity';
INSERT INTO schema_migrations(version) VALUES (3);
