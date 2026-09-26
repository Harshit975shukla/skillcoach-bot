CREATE TABLE media_assets (
    asset_key text PRIMARY KEY,
    learner_id text REFERENCES learners(id),
    file_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('video','photo')),
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX media_assets_owner ON media_assets(learner_id);
INSERT INTO schema_migrations(version) VALUES (5);
