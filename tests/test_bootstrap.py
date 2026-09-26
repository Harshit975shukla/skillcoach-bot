import ssl
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from skillcoach.bootstrap import runtime_url
from skillcoach.storage import Repository


def test_pooler_runtime_credentials_keep_exact_endpoint_and_encode_password():
    password = "a" * 32 + "@/:?"
    source = (
        "postgresql://postgres.project-ref:admin@exact.pooler.supabase.com:6543/postgres?sslmode=verify-full"
    )
    result = urlsplit(runtime_url(source, password))
    assert result.hostname == "exact.pooler.supabase.com"
    assert result.port == 6543
    assert result.username == "skillcoach_runtime.project-ref"
    assert unquote(result.password) == password
    assert result.query == "sslmode=verify-full"


def test_runtime_password_strength_and_admin_username_guard():
    with pytest.raises(ValueError):
        runtime_url("postgresql://postgres.ref:admin@exact.pooler.supabase.com/postgres", "weak")
    with pytest.raises(ValueError):
        runtime_url("postgresql://unexpected:admin@exact.pooler.supabase.com/postgres", "x" * 40)


def test_real_connection_disables_automatic_prepared_statements(monkeypatch):
    captured = {}

    class Connection:
        def execute(self, *args):
            return None

        @contextmanager
        def transaction(self):
            yield

    @contextmanager
    def connect(*args, **kwargs):
        captured.update(kwargs)
        yield Connection()

    monkeypatch.setattr("skillcoach.storage.psycopg.connect", connect)
    with Repository("postgresql://not-contacted").connection():
        pass
    assert captured["prepare_threshold"] is None
    assert captured["autocommit"] is True


def test_supabase_ca_is_packaged_and_requires_hostname_verification(monkeypatch):
    monkeypatch.setenv("DATABASE_CA_CERT_FILE", "certs/supabase-ca-2021.crt")
    with pytest.raises(ValueError, match="verify-full"):
        Repository("postgresql://example/postgres?sslmode=require")
    repo = Repository("postgresql://example/postgres?sslmode=verify-full")
    assert Path(repo.ca_cert_file).is_absolute()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(repo.ca_cert_file)
    assert context.cert_store_stats()["x509_ca"] == 1
