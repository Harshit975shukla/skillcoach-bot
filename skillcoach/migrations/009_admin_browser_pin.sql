ALTER TABLE admin_logins
    ADD COLUMN pin_hash text,
    ADD COLUMN pin_attempts smallint NOT NULL DEFAULT 0 CHECK (pin_attempts BETWEEN 0 AND 3),
    ADD COLUMN pin_last_failed_at timestamptz;
CREATE INDEX admin_logins_owner_requested ON admin_logins(owner_id, requested_at);
INSERT INTO schema_migrations(version) VALUES (9);
