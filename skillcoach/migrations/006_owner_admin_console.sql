CREATE TABLE admin_logins (
    id text PRIMARY KEY,
    verifier_hash text NOT NULL UNIQUE,
    owner_id bigint NOT NULL,
    display_code text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','consumed')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    notified boolean NOT NULL DEFAULT false
);
CREATE INDEX admin_logins_expiry ON admin_logins(expires_at);

CREATE TABLE admin_sessions (
    token_hash text PRIMARY KEY,
    owner_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX admin_sessions_expiry ON admin_sessions(expires_at);

CREATE TABLE admin_requests (
    id text PRIMARY KEY,
    session_hash text NOT NULL REFERENCES admin_sessions(token_hash),
    action text NOT NULL,
    target_id text NOT NULL,
    arguments jsonb NOT NULL,
    expected_generation integer NOT NULL,
    expected_status text NOT NULL,
    preview jsonb NOT NULL,
    state text NOT NULL DEFAULT 'preview' CHECK (state IN ('preview','completed')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX admin_requests_session ON admin_requests(session_hash, created_at);

CREATE TABLE admin_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL REFERENCES admin_requests(id),
    action text NOT NULL,
    subject_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations(version) VALUES (6);
