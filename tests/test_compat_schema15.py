"""Rollback proof: the code live before both mode (716f677) on schema 15 (the final migration 015).

This file exists only on the test-only branch compat-716f677-schema15, which is 716f677 plus the exact
final migration 015, this file and the migration count in test_postgres.py. The whole old suite runs on
schema 15 here. These tests also check the rollback step itself: after `telegram-copies-off` (whose
exact statement is WITHDRAW below) the old code works with the sent and withdrawn Telegram copies, and
the negative control shows why that step must come first: the old code fails an open copy.
"""

import hashlib
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb
from test_web_channel import build_web
from test_web_dashboard import browser, private

from skillcoach.clients import Budget

ROOT = Path(__file__).resolve().parents[1]
OWNER = 42
FINAL_015_SHA256 = "1ec4cdec57c92697a65cd8177117ba4b0d9a6071097f60d8d0db896ebc53f11b"
OLD_CODE_SHA256 = {
    "skillcoach/runtime.py": "7881ac4c506cc9b4c49316421525ccf8d062052d550a70c9add7d37770f8f6b2",
    "skillcoach/storage.py": "5d73d94d4e666a69a29dd8ceb8e89c142bd2fc6b6a8aa7ae910e94664b24d958",
    "skillcoach/access.py": "c4e772188f5c006b015fb1049b64ba357bb1faddbd0208acde6a514714e307f2",
    "skillcoach/web_channel.py": "1f49b7e5b7cd9add640f64c100e3825bd77e5de36b4e08a723f3777934374c37",
}
# telegram_copies.WITHDRAW_OPEN_COPIES on the feature branch, character for character.
WITHDRAW = (
    "UPDATE outbox SET status='suppressed', error_code='copies_off' "
    "WHERE body->>'kind'='telegram' AND status IN ('pending','failed')"
)
WITHDRAW_SHA256 = "e4759e6e7c5eb2793c00cfc7556f9e3b97bf9ae33eb065e630f8abd2387aa00a"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_this_is_the_old_code_with_the_final_migration_and_the_shared_withdrawal():
    import importlib

    for name, expected in OLD_CODE_SHA256.items():
        assert digest(ROOT / name) == expected, name
        # The modules actually imported by these tests are those files, not another checkout's.
        module = importlib.import_module(name.removesuffix(".py").replace("/", "."))
        assert Path(module.__file__).resolve() == (ROOT / name).resolve(), name
    assert not (ROOT / "skillcoach" / "telegram_copies.py").exists()
    assert importlib.util.find_spec("skillcoach.telegram_copies") is None
    assert digest(ROOT / "skillcoach" / "migrations" / "015_telegram_copies.sql") == FINAL_015_SHA256
    assert hashlib.sha256(WITHDRAW.encode()).hexdigest() == WITHDRAW_SHA256


def rows(web, sql, *args):
    with web.bot.repo.connection() as conn:
        return conn.execute(sql, args).fetchall()


def add_copy(web, original: str, suffix: str, status: str, code=None):
    """A Telegram copy row as both mode leaves it (the old code never creates one)."""
    with web.bot.repo.connection() as conn:
        conn.execute(
            "INSERT INTO outbox(id,job_id,body,learner_id,access_generation,status,error_code,attempts) "
            "SELECT %s, job_id, %s, learner_id, access_generation, %s, %s, %s FROM outbox WHERE id=%s",
            (original + suffix, Jsonb({"kind": "telegram", "copy_of": original, "bot": 0}), status, code,
             1 if status != "pending" else 0, original),
        )
    return original + suffix


def latest_sent_text(web, learner="owner"):
    return rows(
        web,
        "SELECT id FROM outbox WHERE learner_id=%s AND body->>'kind'='text' AND status='sent' "
        "AND delivered_seq IS NOT NULL ORDER BY delivered_seq DESC LIMIT 1",
        learner,
    )[0]["id"]


def drain(web):
    runtime = web.bot.runtime
    runtime.recover(media=False)
    for _ in range(20):
        if not runtime.deliver_one(Budget(60)):
            break


@pytest.mark.postgres
def test_old_code_runs_on_schema_15_after_open_copies_are_withdrawn(pg_repo, config, monkeypatch):
    web = build_web(pg_repo, config, monkeypatch)
    assert rows(web, "SELECT max(version) AS v FROM schema_migrations")[0]["v"] == 15
    # Receipts and access audits written by the old code use bot namespace 0, the recorded bot.
    assert {row["bot_id"] for row in rows(web, "SELECT bot_id FROM telegram_receipts")} == {0}
    audits = rows(web, "SELECT bot_id FROM access_audit")
    assert audits and {row["bot_id"] for row in audits} == {0}
    assert web.bot.input(OWNER, "/help", update_id=777001) == "queued"
    assert web.bot.input(OWNER, "/help", update_id=777001) == "duplicate"
    # Both mode left one accepted copy, one already withdrawn, and two still open (one with spent attempts).
    original = latest_sent_text(web)
    sent_copy = add_copy(web, original, ":tg", "sent")
    withdrawn = add_copy(web, original, ":tg-old", "suppressed", "copies_off")
    open_rows = [add_copy(web, original, ":tg-pending", "pending"), add_copy(web, original, ":tg-failed", "failed")]
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET attempts=5 WHERE id=%s", (open_rows[1],))
    others = "SELECT id, status, error_code, attempts FROM outbox WHERE body->>'kind' IS DISTINCT FROM 'telegram' ORDER BY id"
    before = rows(web, others)
    # The rollback step (telegram-copies-off), applied with the identical statement.
    with web.bot.repo.connection() as conn:
        assert conn.execute(WITHDRAW).rowcount == 2
    assert rows(web, others) == before
    assert not rows(web, "SELECT 1 FROM outbox WHERE body->>'kind'='telegram' AND status IN ('pending','failed')")
    # The old workers then run cleanly: no failure, no recovery notice, and copies stay as they are.
    copies = "SELECT id, status, error_code FROM outbox WHERE body->>'kind'='telegram' ORDER BY id"
    snapshot = rows(web, copies)
    drain(web)
    web.bot.input(OWNER, "/retry")  # /retry in web mode never revives withdrawn copies
    drain(web)
    assert rows(web, copies) == snapshot
    assert {row["id"]: row["status"] for row in snapshot}[sent_copy] == "sent"
    assert {row["id"]: row["error_code"] for row in snapshot}[withdrawn] == "copies_off"
    assert not rows(web, "SELECT 1 FROM outbox WHERE id LIKE '%%:tg%%:delivery-error'")
    assert web.bot.repo.failure_counts(web_mode=True, all_learners=True)["deliveries"] == 0
    # The old web inbox never shows a copy.
    client, csrf = browser(web, "owner@example.test")
    feed = private(client, csrf, "/web/feed").json["messages"]
    assert feed and all(item["kind"] in ("text", "media") for item in feed)


@pytest.mark.postgres
def test_an_open_copy_breaks_old_code_so_copies_off_must_run_first(pg_repo, config, monkeypatch):
    web = build_web(pg_repo, config, monkeypatch)
    web.bot.input(OWNER, "/help")
    open_copy = add_copy(web, latest_sent_text(web), ":tg", "pending")
    drain(web)
    failed = rows(web, "SELECT status, error_code FROM outbox WHERE id=%s", open_copy)[0]
    assert (failed["status"], failed["error_code"]) == ("failed", "invalid_outbox_kind")
    assert rows(web, "SELECT 1 FROM outbox WHERE id=%s", open_copy + ":delivery-error")
    assert web.bot.repo.failure_counts(web_mode=True, all_learners=True)["deliveries"] >= 1
