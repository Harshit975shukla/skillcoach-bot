CREATE TABLE learner_document_requests (
    id text NOT NULL,
    learner_id text NOT NULL REFERENCES learners(id),
    access_generation integer NOT NULL,
    auth_hash text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('resume','jd')),
    content_hash text NOT NULL,
    profile_hash text NOT NULL,
    plan_id text,
    text text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'processing'
        CHECK(status IN ('processing','ready','failed','queued','cancelled')),
    choice text CHECK(choice IN ('keep','revise')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(learner_id,id)
);
CREATE INDEX learner_document_request_expiry ON learner_document_requests(expires_at);
INSERT INTO schema_migrations(version) VALUES (8);
