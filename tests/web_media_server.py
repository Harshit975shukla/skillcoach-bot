"""Serve the real web app on a disposable PostgreSQL schema for the lesson video browser check.

Delivers one lesson video through the real pipeline (the local storyboard renderer and ffmpeg, the
private chunked store and the transactional attach), signs two learners in with the real email-code
flow (fake mailbox), then serves the Flask app on 127.0.0.1 until stdin closes, and drops the schema.
Prints one JSON line: the address, the session cookies and the stored video's facts. Synthetic
learners only; nothing leaves this machine.
"""

import json
import os
import sys
import threading
from pathlib import Path
from uuid import uuid4

TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS), str(TESTS.parent)]

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402
from test_web_channel import build_web, sign_in  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from skillcoach.clients import Budget  # noqa: E402
from skillcoach.config import Config  # noqa: E402
from skillcoach.storage import Repository  # noqa: E402
from skillcoach.storyboard import reviewed_architecture  # noqa: E402
from skillcoach.web_channel import WEB_COOKIE  # noqa: E402


def main():
    url = os.environ["TEST_DATABASE_URL"]
    if "test" not in url.lower():
        raise SystemExit("TEST_DATABASE_URL must visibly identify a disposable test database")
    schema = "test_" + uuid4().hex
    repo = Repository(url, schema=schema)
    try:
        repo.migrate()
        web = build_web(repo, Config("postgresql://test-only", "fake-token", 42, "a" * 32), pytest.MonkeyPatch())
        learner = web.learner.learner_id
        with repo.connection() as conn:
            conn.execute("UPDATE learners SET email='second@example.test' WHERE id=%s", (web.silent.learner_id,))
            generation = conn.execute("SELECT generation FROM learners WHERE id=%s", (learner,)).fetchone()["generation"]
            conn.execute(
                "INSERT INTO jobs(id,payload,status,learner_id,access_generation) VALUES ('lesson:browser',%s,'done',%s,%s)",
                (Jsonb({"type": "test"}), learner, generation),
            )
            for index, body in enumerate(
                (
                    {"kind": "text", "text": "Today's lesson: how a load balancer routes requests."},
                    {
                        "kind": "media",
                        "mode": "video",
                        "caption": "How the load balancer routes requests",
                        "storyboard": reviewed_architecture("EC2").model_dump(),
                        "shared_reviewed": True,
                    },
                    {"kind": "text", "text": "After the video: your first exercise."},
                )
            ):
                conn.execute(
                    "INSERT INTO outbox(id,job_id,body,learner_id,access_generation) VALUES (%s,'lesson:browser',%s,%s,%s)",
                    (f"lesson:browser:{index}", Jsonb(body), learner, generation),
                )
        while web.bot.runtime.deliver_one(Budget(300), media=True):
            pass
        with repo.connection() as conn:
            row = conn.execute("SELECT body FROM outbox WHERE id='lesson:browser:1'").fetchone()
            note = row["body"].get("web_media") or {}
            if note.get("status") != "ready":
                raise SystemExit("The lesson video was not stored: " + json.dumps(note))
            video = conn.execute("SELECT bytes, sha256 FROM web_media WHERE id=%s", (note["video"],)).fetchone()
        tokens = {}
        for name, address in (("learner", "learner@example.test"), ("other", "second@example.test")):
            client = web.app.test_client()
            sign_in(web, address, client=client)
            tokens[name] = client.get_cookie(WEB_COOKIE).value
        server = make_server("127.0.0.1", 0, web.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(
            json.dumps(
                {
                    "origin": f"http://127.0.0.1:{server.server_port}",
                    "cookie": WEB_COOKIE,
                    **tokens,
                    "video": note["video"],
                    "poster": note.get("poster"),
                    "duration": note["duration"],
                    "bytes": video["bytes"],
                    "sha256": video["sha256"],
                }
            ),
            flush=True,
        )
        sys.stdin.read()
        server.shutdown()
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    main()
