"""Web push: RFC 8291 encryption, RFC 8292 VAPID, push-service endpoint validation and the transport;
then, on a real database, device bindings, their fencing and delivery. Synthetic keys and endpoints
only: nothing here contacts a push service."""

import base64
import json
import secrets
import threading
import time
from dataclasses import replace
from datetime import timedelta

import pytest
import requests
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from test_web_channel import ORIGIN, WEB_ENV, build_web, sign_in, web_config
from test_web_dashboard import private
from test_web_join import act, owner_admin

from skillcoach import web_push
from skillcoach.clients import Budget, ExternalError
from skillcoach.config import ConfigurationError, web_settings
from skillcoach.web import create_app
from skillcoach.web_channel import WEB_COOKIE, digest

PUBLIC, PRIVATE = web_push.generate_keys()
X962 = (serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def browser_keys():
    """A synthetic browser subscription key pair: (private key, p256dh, auth)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key, b64(key.public_key().public_bytes(*X962)), b64(secrets.token_bytes(16))


def decrypt(body: bytes, receiver, auth: str) -> bytes:
    """RFC 8291 decryption written from the RFC with plain cryptography primitives (not http-ece)."""
    salt, record, length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    sender_point, ciphertext = body[21 : 21 + length], body[21 + length :]
    assert record == 4096 and length == 65 and len(ciphertext) <= record
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_point)
    receiver_point = receiver.public_key().public_bytes(*X962)
    ikm = HKDF(
        hashes.SHA256(), 32, salt=unb64(auth), info=b"WebPush: info\x00" + receiver_point + sender_point
    ).derive(receiver.exchange(ec.ECDH(), sender))
    key = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None).rstrip(b"\x00")
    assert plain.endswith(b"\x02"), "a single final record ends with the 0x02 delimiter"
    return plain[:-1]


def push_config(config):
    return replace(web_config(config), web_push_public_key=PUBLIC, web_push_private_key=PRIVATE)


# Encryption and signatures -------------------------------------------------------------------


def test_rfc8291_example_is_reproduced_exactly():
    sender = ec.derive_private_key(
        int.from_bytes(unb64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1()
    )
    body = web_push.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=unb64("DGv6ra1nlYgDCS1FRnbzlw"),
        sender=sender,
    )
    header = unb64(
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
        "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
    )
    ciphertext = unb64("8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ")
    assert len(header) == 86 and body == header + ciphertext
    # The RFC's receiver key decrypts it with the independent implementation above.
    receiver = ec.derive_private_key(
        int.from_bytes(unb64("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"), "big"), ec.SECP256R1()
    )
    assert decrypt(body, receiver, "BTBZMqHH6r4Tts7J_aSIgg") == b"When I grow up, I want to be a watermelon"


def test_every_message_gets_a_fresh_salt_and_sender_key():
    receiver, p256dh, auth = browser_keys()
    first, second = (web_push.encrypt(b'{"push":"quiz"}', p256dh, auth) for _ in range(2))
    assert first[:16] != second[:16], "salt"
    assert first[21:86] != second[21:86], "sender key"
    for body in (first, second):
        assert decrypt(body, receiver, auth) == b'{"push":"quiz"}'
        point = body[21:86]
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
        assert point != receiver.public_key().public_bytes(*X962)
    tampered = bytearray(first)
    tampered[-1] ^= 1
    with pytest.raises(InvalidTag):
        decrypt(bytes(tampered), receiver, auth)
    other, _, _ = browser_keys()
    with pytest.raises(InvalidTag):
        decrypt(first, other, auth)
    with pytest.raises(ExternalError, match="push_payload_too_large"):
        web_push.encrypt(b"x" * 513, p256dh, auth)


def test_vapid_header_signs_each_push_services_origin_with_the_configured_key(config):
    settings = push_config(config)
    now = time.time()
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(PUBLIC))
    for endpoint, audience in (
        ("https://fcm.googleapis.com/fcm/send/" + "a" * 40, "https://fcm.googleapis.com"),
        ("https://web.push.apple.com/" + "b" * 40, "https://web.push.apple.com"),
    ):
        header = web_push.authorization(endpoint, settings, now)
        assert header.startswith("vapid t=")
        parts = dict(item.split("=", 1) for item in header.removeprefix("vapid ").split(","))
        assert parts["k"] == PUBLIC
        encoded_header, encoded_claims, signature = parts["t"].split(".")
        assert json.loads(unb64(encoded_header)) == {"typ": "JWT", "alg": "ES256"}
        claims = json.loads(unb64(encoded_claims))
        assert claims["aud"] == audience and claims["sub"] == settings.web_app_url
        assert now + 11 * 3600 < claims["exp"] <= now + 12 * 3600 + 5 and claims["exp"] <= now + 24 * 3600
        raw = unb64(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        public.verify(der, f"{encoded_header}.{encoded_claims}".encode(), ec.ECDSA(hashes.SHA256()))
        forged = b64(json.dumps({**claims, "aud": "https://evil.example"}).encode())
        with pytest.raises(InvalidSignature):
            public.verify(der, f"{encoded_header}.{forged}".encode(), ec.ECDSA(hashes.SHA256()))


def test_vapid_keys_must_be_one_matching_pair(monkeypatch):
    other_public, other_private = web_push.generate_keys()
    assert web_push.check_keys(PUBLIC, PRIVATE)
    for public, secret in (
        (other_public, PRIVATE),
        (PUBLIC, other_private),
        (PUBLIC, ""),
        ("", PRIVATE),
        (PUBLIC, b64(b"\xff" * 32)),
        (PUBLIC, b64(b"\x00" * 32)),
        (PUBLIC[:-2], PRIVATE),
        (PUBLIC, PRIVATE + "A"),
        ("not+base64/", PRIVATE),
    ):
        assert not web_push.check_keys(public, secret)
    for name in WEB_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WEB_PUSH_PUBLIC_KEY", other_public)
    monkeypatch.setenv("WEB_PUSH_PRIVATE_KEY", PRIVATE)
    with pytest.raises(ConfigurationError) as error:
        web_settings()
    assert PRIVATE not in str(error.value) and other_public not in str(error.value)
    monkeypatch.delenv("WEB_PUSH_PUBLIC_KEY")
    with pytest.raises(ConfigurationError):
        web_settings()
    monkeypatch.setenv("WEB_PUSH_PUBLIC_KEY", PUBLIC)
    settings = web_settings()
    assert settings["web_push_public_key"] == PUBLIC and settings["web_push_private_key"] == PRIVATE


def test_push_needs_web_mode_and_both_keys(config):
    assert not replace(config, web_push_public_key=PUBLIC, web_push_private_key=PRIVATE).push_enabled
    assert not web_config(config).push_enabled
    assert push_config(config).push_enabled


TOKEN = "dGVzdC10b2tlbi0xMjM0NTY3ODkwYWJjZGVmZ2hpams"


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        ("https://fcm.googleapis.com/fcm/send/cX9:APA91b" + TOKEN, "fcm"),
        ("https://fcm.googleapis.com/wp/" + TOKEN, "fcm"),
        ("https://FCM.googleapis.com:443/fcm/send/" + TOKEN, "fcm"),
        ("https://updates.push.services.mozilla.com/wpush/v2/gAAAAA" + TOKEN + "==", "mozilla"),
        ("https://web.push.apple.com/Q" + TOKEN, "apple"),
        ("https://wns2-par02p.notify.windows.com/w/?token=BQYAAAB%2b" + TOKEN + "%3d", "windows"),
        ("http://fcm.googleapis.com/fcm/send/" + TOKEN, None),
        ("https://fcm.googleapis.com:8443/fcm/send/" + TOKEN, None),
        ("https://user:pass@fcm.googleapis.com/fcm/send/" + TOKEN, None),
        ("https://fcm.googleapis.com@evil.example/fcm/send/" + TOKEN, None),
        ("https://fcm.googleapis.com.evil.example/fcm/send/" + TOKEN, None),
        ("https://evilfcm.googleapis.com/fcm/send/" + TOKEN, None),
        ("https://fcm.googleapis.com./fcm/send/" + TOKEN, None),
        ("https://push.apple.com/" + TOKEN, None),
        ("https://evilpush.apple.com/" + TOKEN, None),
        ("https://web.push.apple.com.evil.example/" + TOKEN, None),
        ("https://notify.windows.com.evil.example/w/?token=" + TOKEN, None),
        ("https://142.250.1.1/fcm/send/" + TOKEN, None),
        ("https://[::1]/fcm/send/" + TOKEN, None),
        ("https://127.0.0.1/wp/" + TOKEN, None),
        ("https://localhost/fcm/send/" + TOKEN, None),
        ("https://fcm.googleapis.com/fcm/other/" + TOKEN, None),
        ("https://fcm.googleapis.com/fcm/send/" + TOKEN + "/../../admin", None),
        ("https://fcm.googleapis.com/fcm/send/" + TOKEN + "?redirect=https://evil.example", None),
        ("https://fcm.googleapis.com/fcm/send/" + TOKEN + "#x", None),
        ("https://fcm.googleapis.com/fcm/send/ " + TOKEN, None),
        ("https://fcm.googleapis.com/fcm/send/short", None),
        ("https://fcm.googleapis.com/fcm/send/" + "a" * 1100, None),
        ("https://xn--fcm-googleapis-1nb.com/fcm/send/" + TOKEN, None),
        ("https://fcm.googleаpis.com/fcm/send/" + TOKEN, None),
        ("https://updates.push.services.mozilla.com/wpush/v3/" + TOKEN, None),
        ("https://wns2-par02p.notify.windows.com/w/?token=" + TOKEN + "&next=https://evil.example", None),
        ("", None),
        (None, None),
    ],
)
def test_only_real_push_service_endpoints_are_accepted(endpoint, expected):
    assert web_push.provider(endpoint) == expected


def test_browser_keys_must_be_a_p256_point_and_a_16_byte_secret():
    _, p256dh, auth = browser_keys()
    assert web_push.receiver_keys(p256dh, auth) == (p256dh, auth)
    point = unb64(p256dh)
    for bad_point, bad_auth in (
        (b64(b"\x04" + b"\x00" * 64), auth),
        (b64(b"\x02" + point[1:33]), auth),
        (b64(point[:-1]), auth),
        (p256dh, b64(b"\x01" * 15)),
        (p256dh, b64(b"\x01" * 17)),
        (p256dh.replace("A", "+", 1) if "A" in p256dh else "+" + p256dh[1:], auth),
        (None, auth),
    ):
        with pytest.raises((ValueError, TypeError)):
            web_push.receiver_keys(bad_point, bad_auth)


class Answer:
    def __init__(self, status):
        self.status_code = status
        self.read = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, *args, **kwargs):
        self.read = True
        return iter(())


class Session:
    """Stands in for requests.Session and records every request it would have made."""

    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.calls = []
        self.trust_env = True

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return Answer(status)


def target():
    receiver, p256dh, auth = browser_keys()
    endpoint = "https://fcm.googleapis.com/fcm/send/" + secrets.token_urlsafe(40)
    return receiver, {"id": "binding", "endpoint": endpoint, "p256dh": p256dh, "auth": auth}


def test_transport_refuses_redirects_bounds_time_and_sends_only_the_kind(config):
    settings = push_config(config)
    receiver, device = target()
    session = Session(201)
    sender = web_push.WebPush(settings, session)
    assert session.trust_env is False
    assert sender.send(device, "quiz", Budget(30)) == "accepted"
    url, sent = session.calls[0]
    assert url == device["endpoint"]
    assert sent["allow_redirects"] is False and sent["stream"] is True
    assert sent["timeout"][0] <= web_push.CONNECT_SECONDS and sent["timeout"][1] <= web_push.READ_SECONDS
    headers = sent["headers"]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == str(web_push.TTL_SECONDS)
    assert headers["Urgency"] == "normal" and headers["Authorization"].startswith("vapid t=")
    assert json.loads(decrypt(sent["data"], receiver, device["auth"])) == {"push": "quiz"}
    # A redirect is never followed: one request, and the push service's answer is not read.
    for status, expected in ((301, "push_redirect_refused"), (307, "push_redirect_refused")):
        session = Session(status)
        with pytest.raises(ExternalError) as error:
            web_push.WebPush(settings, session).send(device, "quiz", Budget(30))
        assert error.value.code == expected and not error.value.retryable and len(session.calls) == 1
    for status, outcome in ((200, "accepted"), (202, "accepted"), (404, "gone"), (410, "gone")):
        assert web_push.WebPush(settings, Session(status)).send(device, "lesson", Budget(30)) == outcome
    for status, retryable in (
        (400, False),
        (401, False),
        (403, False),
        (413, False),
        (429, True),
        (500, True),
    ):
        with pytest.raises(ExternalError) as error:
            web_push.WebPush(settings, Session(status)).send(device, "lesson", Budget(30))
        assert error.value.code == f"push_http_{status}" and error.value.retryable is retryable
    with pytest.raises(ExternalError, match="push_network_unavailable"):
        web_push.WebPush(settings, Session(requests.ConnectTimeout())).send(device, "lesson", Budget(30))
    # Nothing is sent to an endpoint that is not a listed push service, or with an unknown kind.
    session = Session(201)
    for bad, kind, code in (
        (
            {**device, "endpoint": "https://evil.example/fcm/send/" + TOKEN},
            "quiz",
            "push_endpoint_not_allowed",
        ),
        (device, "Your score is 2/5", "invalid_push_kind"),
        ({**device, "p256dh": b64(b"\x04" + b"\x00" * 64)}, "quiz", "push_subscription_keys_invalid"),
    ):
        with pytest.raises(ExternalError, match=code):
            web_push.WebPush(settings, session).send(bad, kind, Budget(30))
    assert session.calls == []


def test_reminder_kinds_are_generic(monkeypatch, config):
    monkeypatch.setattr(web_push, "targets", lambda scoped, settings, now: ["binding"])
    settings = push_config(config)
    note = {"kind": "email", "scheduled": True, "scheduled_date": "2026-10-02"}
    for payload, kind in (
        ({"type": "schedule", "kind": "lesson", "date": "2026-10-02"}, "lesson"),
        ({"type": "schedule", "kind": "quiz"}, "quiz"),
        ({"type": "schedule", "kind": "weekly"}, "weekly"),
        ({"type": "schedule", "kind": "review"}, "review"),
        ({"type": "encouragement", "message": "private words"}, "mentor"),
        ({"type": "telegram", "requested_by": "owner_admin"}, "update"),
    ):
        body = web_push.reminder({"payload": payload}, note, None, settings, None)
        assert body == {
            "kind": "push",
            "push": kind,
            "targets": ["binding"],
            "scheduled": True,
            "scheduled_date": "2026-10-02",
        }
    assert (
        web_push.reminder({"payload": {"type": "telegram", "text": "/help"}}, note, None, settings, None)
        is None
    )
    assert (
        web_push.reminder({"payload": {"type": "schedule", "kind": "other"}}, note, None, settings, None)
        is None
    )
    assert (
        web_push.reminder(
            {"payload": {"type": "schedule", "kind": "lesson"}}, note, None, web_config(config), None
        )
        is None
    )


def test_push_routes_are_off_outside_web_mode_and_without_keys(harness):
    client = create_app(harness.runtime).test_client()
    body = {"endpoint": "https://fcm.googleapis.com/fcm/send/" + TOKEN, "p256dh": "x", "auth": "y"}
    for path in ("/web/push/subscribe", "/web/push/sync", "/web/push/unsubscribe"):
        response = client.post(path, base_url=ORIGIN, json=body, headers={"Origin": ORIGIN})
        assert response.status_code == 404
    for path in ("/web/manifest.webmanifest", "/web/sw.js", "/web/offline"):
        assert client.get(path, base_url=ORIGIN).status_code == 404
    harness.runtime.config = web_config(harness.runtime.config)
    response = client.post("/web/push/subscribe", base_url=ORIGIN, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 404 and response.json["push"] is False
    manifest = client.get("/web/manifest.webmanifest", base_url=ORIGIN)
    assert manifest.mimetype == "application/manifest+json"
    assert manifest.json["scope"] == "/web" and manifest.json["start_url"] == "/web"
    assert {icon["purpose"] for icon in manifest.json["icons"]} == {"any", "maskable"}
    worker = client.get("/web/sw.js", base_url=ORIGIN)
    assert worker.headers["Service-Worker-Allowed"] == "/web" and worker.mimetype == "text/javascript"
    assert "frame-ancestors 'none'" in worker.headers["Content-Security-Policy"]
    offline = client.get("/web/offline", base_url=ORIGIN)
    assert offline.status_code == 200 and b"You're offline" in offline.data
    page = client.get("/web/dashboard", base_url=ORIGIN).data
    assert b'rel="manifest"' in page and b"telegram.org" not in page
    assert b'rel="manifest"' not in client.get("/app", base_url=ORIGIN).data
    for name in (
        "icon-192.png",
        "icon-512.png",
        "icon-maskable-512.png",
        "apple-touch-icon.png",
        "badge-72.png",
    ):
        icon = client.get("/static/" + name, base_url=ORIGIN)
        assert (
            icon.status_code == 200 and icon.mimetype == "image/png" and icon.data[:8] == b"\x89PNG\r\n\x1a\n"
        )


# PostgreSQL: bindings, fencing and delivery -----------------------------------------------------


class FakePush:
    """Records each send instead of contacting a push service; answers per endpoint. An answer
    list is consumed one send at a time (the last one repeats)."""

    def __init__(self):
        self.attempts = []
        self.answers = {}
        self.before = None

    def send(self, target, kind, budget, *, ttl=web_push.TTL_SECONDS):
        budget.remaining()
        if self.before:
            self.before(target)
        answer = self.answers.get(target["endpoint"], "accepted")
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, ExternalError) and answer.code == "request_budget_exhausted":
            raise answer
        self.attempts.append((target["id"], target["endpoint"], kind))
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def web(pg_repo, config, monkeypatch):
    web = build_web(pg_repo, config, monkeypatch)
    with pg_repo.connection() as conn:
        conn.execute("UPDATE learners SET email='second@example.test' WHERE id=%s", (web.silent.learner_id,))
    web.bot.runtime.config = push_config(web.bot.runtime.config)
    web.bot.runtime.push = FakePush()
    web.push = web.bot.runtime.push
    return web


def browser(web, email):
    client = web.app.test_client()
    csrf = sign_in(web, email, client=client).json["csrf"]
    web.clock.now += timedelta(seconds=61)
    return client, csrf


def device():
    _, p256dh, auth = browser_keys()
    endpoint = "https://fcm.googleapis.com/fcm/send/" + secrets.token_urlsafe(40)
    return {"endpoint": endpoint, "p256dh": p256dh, "auth": auth}


def bindings(web, learner=None):
    with web.bot.repo.connection() as conn:
        return conn.execute(
            "SELECT * FROM web_push_subscriptions WHERE (%s::text IS NULL OR learner_id=%s) ORDER BY created_at, id",
            (learner, learner),
        ).fetchall()


def remind(web, *scopes, deliver=True):
    """Queue a mentor note (which sends an email and a push reminder) for each learner."""
    for scoped in scopes:
        scoped.enqueue("admin:note:" + secrets.token_hex(4), {"type": "encouragement", "message": "goal"})
    if deliver:
        web.bot.runtime.recover(media=False)
    else:
        while web.bot.runtime.process_one(Budget(60)):
            pass


def push_rows(web):
    with web.bot.repo.connection() as conn:
        return conn.execute(
            "SELECT id, learner_id, status, error_code, attempts, body FROM outbox "
            "WHERE body->>'kind'='push' ORDER BY sequence"
        ).fetchall()


def deliver(web):
    while web.bot.runtime.deliver_one(Budget(60)):
        pass


def retry_now(web, row):
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE outbox SET available_at=now() WHERE id=%s", (row["id"],))
    deliver(web)


def session_of(client):
    """What authenticate() returned for this browser's request, before anything else happened."""
    token = client.get_cookie(WEB_COOKIE).value
    return token


def subscribed(web, *pairs):
    for client, csrf, item in pairs:
        assert private(client, csrf, "/web/push/subscribe", item).status_code == 200


@pytest.mark.postgres
def test_devices_bind_to_the_signed_in_learner_and_requests_cannot_name_another(web):
    first, first_csrf = browser(web, "learner@example.test")
    second, second_csrf = browser(web, "second@example.test")
    assert first.get("/web/session", base_url=ORIGIN).json["push_key"] == PUBLIC
    phone = device()
    for csrf, origin, extra, client in (
        (None, ORIGIN, {}, first),
        (first_csrf, "https://evil.invalid", {}, first),
        (first_csrf, ORIGIN, {"learner": web.silent.learner_id}, first),
        (first_csrf, ORIGIN, {}, web.app.test_client()),
        (second_csrf, ORIGIN, {}, first),
    ):
        response = private(client, csrf, "/web/push/subscribe", {**phone, **extra}, origin=origin)
        assert response.status_code == 403
    assert private(first, first_csrf, "/web/push/subscribe", phone, query="?learner=owner").status_code == 403
    for bad in (
        {**phone, "endpoint": "https://evil.example/fcm/send/" + TOKEN},
        {**phone, "p256dh": b64(b"\x04" + b"\x00" * 64)},
        {"endpoint": phone["endpoint"], "p256dh": phone["p256dh"]},
    ):
        response = private(first, first_csrf, "/web/push/subscribe", bad)
        assert response.status_code == 403 and phone["endpoint"] not in json.dumps(response.json)
    assert bindings(web) == []
    assert private(first, first_csrf, "/web/push/subscribe", phone).json == {"subscribed": True}
    [row] = bindings(web)
    assert row["learner_id"] == web.learner.learner_id and row["session_hash"] == digest(session_of(first))
    assert row["endpoint_hash"] == digest(phone["endpoint"])
    assert row["access_generation"] == web.learner.member()["generation"]
    # Repeating the same request is a no-op; the binding keeps its identifier.
    assert private(first, first_csrf, "/web/push/subscribe", phone).json == {"subscribed": True}
    assert [r["id"] for r in bindings(web)] == [row["id"]]
    # Another account cannot take this browser's subscription while it is still deliverable, and
    # its answers do not say whose it is.
    taken = private(second, second_csrf, "/web/push/subscribe", phone)
    assert taken.status_code == 409 and web.learner.learner_id not in json.dumps(taken.json)
    assert private(second, second_csrf, "/web/push/sync", phone).json == {"subscribed": False}
    assert private(second, second_csrf, "/web/push/unsubscribe", {"endpoint": phone["endpoint"]}).json == {
        "subscribed": False
    }
    assert [r["id"] for r in bindings(web)] == [row["id"]]
    # At most five devices per learner: the oldest makes room.
    for _ in range(5):
        web.clock.now += timedelta(seconds=1)
        assert private(first, first_csrf, "/web/push/subscribe", device()).status_code == 200
    kept = bindings(web, web.learner.learner_id)
    assert len(kept) == 5 and row["id"] not in [r["id"] for r in kept]
    # Turning a device off removes only this learner's own binding.
    newest = kept[-1]
    assert (
        private(first, first_csrf, "/web/push/unsubscribe", {"endpoint": newest["endpoint"]}).status_code
        == 200
    )
    assert newest["id"] not in [r["id"] for r in bindings(web)]


@pytest.mark.postgres
def test_concurrent_registrations_of_one_subscription_leave_one_binding(web):
    first, first_csrf = browser(web, "learner@example.test")
    second, second_csrf = browser(web, "second@example.test")
    phone = device()
    gate = threading.Barrier(3)
    results = []

    def register(client, csrf):
        gate.wait()
        results.append(private(client, csrf, "/web/push/subscribe", phone).status_code)

    threads = [
        threading.Thread(target=register, args=args)
        for args in ((first, first_csrf), (first, first_csrf), (second, second_csrf))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = bindings(web)
    assert len(rows) == 1
    if rows[0]["learner_id"] == web.learner.learner_id:
        assert sorted(results) == [200, 200, 409]
    else:
        assert sorted(results) == [200, 409, 409]


@pytest.mark.postgres
def test_registration_rechecks_the_exact_session_inside_its_transaction(web):
    from skillcoach.web_channel import WebDenied, logout

    runtime = web.bot.runtime
    learner = web.learner.learner_id
    generation = web.learner.member()["generation"]
    # Authenticated, then signed out before the binding transaction: nothing is created.
    first, _ = browser(web, "learner@example.test")
    token = session_of(first)
    authenticated = {"learner_id": learner, "access_generation": generation}
    logout(runtime, token)
    with pytest.raises(WebDenied):
        web_push.subscribe(runtime, authenticated, token, device())
    assert bindings(web) == []
    # Authenticated, then the address changed before sync: the device is not rebound.
    laptop, laptop_csrf = browser(web, "learner@example.test")
    desk = device()
    assert private(laptop, laptop_csrf, "/web/push/subscribe", desk).status_code == 200
    [before] = bindings(web)
    token = session_of(laptop)
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='moved@example.test' WHERE id=%s", (learner,))
    with pytest.raises(WebDenied):
        web_push.sync(runtime, authenticated, token, desk)
    with pytest.raises(WebDenied):
        web_push.subscribe(runtime, authenticated, token, device())
    assert [r["id"] for r in bindings(web)] == [before["id"]]
    remind(web, web.learner)
    assert web.push.attempts == [], "the old binding no longer matches the learner's address"
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET email='learner@example.test' WHERE id=%s", (learner,))
    # Expired sessions cannot register either.
    third, _ = browser(web, "learner@example.test")
    token = session_of(third)
    web.clock.now += timedelta(days=15)
    with pytest.raises(WebDenied):
        web_push.subscribe(runtime, authenticated, token, device())
    web.clock.now -= timedelta(days=15)
    # Sign-out racing a subscription: whichever commits first, no binding of that session survives.
    for _ in range(4):
        racer, _ = browser(web, "learner@example.test")
        token = session_of(racer)
        gate = threading.Barrier(2)

        def opt_in(token=token, gate=gate):
            gate.wait()
            try:
                web_push.subscribe(runtime, authenticated, token, device())
            except WebDenied:
                pass

        def sign_out(token=token, gate=gate):
            gate.wait()
            logout(runtime, token)

        threads = [threading.Thread(target=opt_in), threading.Thread(target=sign_out)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert digest(token) not in {r["session_hash"] for r in bindings(web)}


@pytest.mark.postgres
def test_reminders_name_their_devices_and_reach_only_them(web):
    first, first_csrf = browser(web, "learner@example.test")
    laptop, laptop_csrf = browser(web, "learner@example.test")
    second, second_csrf = browser(web, "second@example.test")
    phone, desk, other = device(), device(), device()
    subscribed(web, (first, first_csrf, phone), (laptop, laptop_csrf, desk), (second, second_csrf, other))
    remind(web, web.learner, web.silent)
    sent = {(endpoint, kind) for _, endpoint, kind in web.push.attempts}
    assert sent == {
        (phone["endpoint"], "mentor"),
        (desk["endpoint"], "mentor"),
        (other["endpoint"], "mentor"),
    }
    rows = push_rows(web)
    assert [row["status"] for row in rows] == ["sent", "sent"]
    for row in rows:
        assert (
            {"kind", "push", "targets", "outcomes"}
            <= set(row["body"])
            <= {"kind", "push", "targets", "outcomes", "scheduled", "scheduled_date"}
        )
        assert row["body"]["push"] == "mentor"
        assert all(item["endpoint"] not in json.dumps(row["body"]) for item in (phone, desk, other))
        expected = {r["id"] for r in bindings(web, row["learner_id"])}
        assert set(row["body"]["targets"]) == expected
        assert row["body"]["outcomes"] == {ident: "accepted" for ident in expected}
    # Email reminders still go out, and push never appears in the conversation.
    assert {mail["to"] for mail in web.email.sent} >= {"learner@example.test", "second@example.test"}
    feed = private(first, first_csrf, "/web/feed").json["messages"]
    assert feed and all("push" not in json.dumps(message) for message in feed)
    # The owner, without a device, gets no push row at all.
    remind(web, web.bot.repo)
    assert len(push_rows(web)) == 2


@pytest.mark.postgres
def test_each_device_is_delivered_once_across_failures_retries_and_turns(web, monkeypatch):
    first, first_csrf = browser(web, "learner@example.test")
    laptop, laptop_csrf = browser(web, "learner@example.test")
    phone, desk = device(), device()
    subscribed(web, (first, first_csrf, phone), (laptop, laptop_csrf, desk))
    ids = {r["endpoint"]: r["id"] for r in bindings(web)}
    # One device accepted, the other's push service failed: the row stays failed and visible, and
    # the retry sends only to the device that has no outcome yet.
    web.push.answers[desk["endpoint"]] = [ExternalError("push_http_503"), "accepted"]
    remind(web, web.learner)
    row = push_rows(web)[-1]
    assert row["status"] == "failed" and row["error_code"] == "push_http_503"
    assert row["body"]["outcomes"] == {ids[phone["endpoint"]]: "accepted"}
    retry_now(web, row)
    row = push_rows(web)[-1]
    assert row["status"] == "sent"
    assert [endpoint for _, endpoint, _ in web.push.attempts].count(phone["endpoint"]) == 1
    assert [endpoint for _, endpoint, _ in web.push.attempts].count(desk["endpoint"]) == 2
    # Out of time after the first device: the row stays pending without spending an attempt, and the
    # next turn continues with the remaining device only.
    web.push.attempts.clear()
    web.push.answers[desk["endpoint"]] = [ExternalError("request_budget_exhausted"), "accepted"]
    remind(web, web.learner, deliver=False)
    web.bot.runtime.deliver_one(Budget(60))  # the email
    assert web.bot.runtime.deliver_one(Budget(60)) is False
    row = push_rows(web)[-1]
    assert row["status"] == "pending" and row["attempts"] == 0 and len(row["body"]["outcomes"]) == 1
    deliver(web)
    assert push_rows(web)[-1]["status"] == "sent"
    assert sorted(endpoint for _, endpoint, _ in web.push.attempts) == sorted(
        [phone["endpoint"], desk["endpoint"]]
    )
    # The real time window: a slow first device leaves the second for the next turn.
    web.push.attempts.clear()
    web.push.answers.clear()
    monkeypatch.setattr(web_push, "ROW_SECONDS", 1.6)
    monkeypatch.setattr(web_push, "CONNECT_SECONDS", 0.3)
    monkeypatch.setattr(web_push, "READ_SECONDS", 0.4)
    web.push.before = lambda target: time.sleep(1.0) if len(web.push.attempts) == 0 else None
    remind(web, web.learner, deliver=False)
    web.bot.runtime.deliver_one(Budget(60))  # the email
    assert web.bot.runtime.deliver_one(Budget(60)) is False
    assert len(web.push.attempts) == 1 and push_rows(web)[-1]["status"] == "pending"
    web.push.before = None
    deliver(web)
    assert len(web.push.attempts) == 2 and push_rows(web)[-1]["status"] == "sent"
    # A device rebound before the retry is not sent the old notification, and the device that
    # already accepted it is not sent it again.
    web.push.attempts.clear()
    web.push.answers[desk["endpoint"]] = ExternalError("push_http_500")
    remind(web, web.learner)
    row = push_rows(web)[-1]
    assert row["status"] == "failed"
    again, again_csrf = browser(web, "learner@example.test")
    assert private(again, again_csrf, "/web/push/sync", desk).json == {"subscribed": True}
    rebound = {r["endpoint"]: r["id"] for r in bindings(web)}[desk["endpoint"]]
    attempts = len(web.push.attempts)
    retry_now(web, row)
    row = push_rows(web)[-1]
    assert len(web.push.attempts) == attempts and row["status"] == "sent"
    assert set(row["body"]["outcomes"].values()) == {"accepted", "stale"}
    assert rebound in {r["id"] for r in bindings(web)}


@pytest.mark.postgres
def test_logout_rebinding_revocation_and_address_change_between_queueing_and_sending(web):
    first, first_csrf = browser(web, "learner@example.test")
    laptop, laptop_csrf = browser(web, "learner@example.test")
    phone, desk = device(), device()
    subscribed(web, (first, first_csrf, phone), (laptop, laptop_csrf, desk))
    # Signing out after the reminder was queued stops that device.
    remind(web, web.learner, deliver=False)
    assert private(first, first_csrf, "/web/logout").status_code == 200
    deliver(web)
    assert [endpoint for _, endpoint, _ in web.push.attempts] == [desk["endpoint"]]
    assert push_rows(web)[-1]["status"] == "sent"
    # The same account signing in again on that browser rebinds it under a new identifier; a
    # reminder queued for the old binding is not sent to it, and its cleanup cannot touch the new one.
    web.push.attempts.clear()
    remind(web, web.learner, deliver=False)
    old = {r["endpoint"]: r["id"] for r in bindings(web)}[desk["endpoint"]]
    again, again_csrf = browser(web, "learner@example.test")
    assert private(again, again_csrf, "/web/push/sync", desk).json == {"subscribed": True}
    new = {r["endpoint"]: r["id"] for r in bindings(web)}[desk["endpoint"]]
    assert new != old
    web.push.answers[desk["endpoint"]] = "gone"
    deliver(web)
    assert web.push.attempts == [] and push_rows(web)[-1]["status"] == "suppressed"
    assert new in {r["id"] for r in bindings(web)}
    del web.push.answers[desk["endpoint"]]
    # An address change between selection and send stops the remaining devices.
    assert private(first, first_csrf, "/web/push/sync", phone).status_code == 403  # signed out
    other, other_csrf = browser(web, "learner@example.test")
    assert private(other, other_csrf, "/web/push/subscribe", phone).status_code == 200
    remind(web, web.learner, deliver=False)

    def change_address(target):
        with web.bot.repo.connection() as conn:
            conn.execute(
                "UPDATE learners SET email='moved@example.test' WHERE id=%s", (web.learner.learner_id,)
            )

    web.push.before = change_address
    deliver(web)
    assert len(web.push.attempts) == 1, "the second device was checked again and skipped"
    assert sorted(push_rows(web)[-1]["body"]["outcomes"].values()) == ["accepted", "stale"]
    web.push.before = None
    with web.bot.repo.connection() as conn:
        conn.execute(
            "UPDATE learners SET email='learner@example.test' WHERE id=%s", (web.learner.learner_id,)
        )
    # Revocation removes every binding and queued reminder; approving again does not revive them.
    web.push.attempts.clear()
    remind(web, web.learner, deliver=False)
    admin = owner_admin(web)
    act(admin, "revoke", web.learner.learner_id)
    deliver(web)
    assert web.push.attempts == [] and bindings(web, web.learner.learner_id) == []
    assert all(row["status"] in ("sent", "suppressed") for row in push_rows(web))


@pytest.mark.postgres
def test_sessions_and_access_must_still_be_current_to_resume_a_device(web):
    first, first_csrf = browser(web, "learner@example.test")
    phone = device()
    subscribed(web, (first, first_csrf, phone))
    # An expired session delivers nothing, even though the binding is kept for a while.
    web.clock.now += timedelta(days=15)
    remind(web, web.learner)
    assert web.push.attempts == [] and len(bindings(web)) == 1
    # Signing in again on that browser resumes it (same learner, access period and address).
    again, again_csrf = browser(web, "learner@example.test")
    assert private(again, again_csrf, "/web/push/sync", phone).json == {"subscribed": True}
    remind(web, web.learner)
    assert [endpoint for _, endpoint, _ in web.push.attempts] == [phone["endpoint"]]
    # After an access change the old binding is not resumed; the device must be turned on again.
    with web.bot.repo.connection() as conn:
        conn.execute("UPDATE learners SET generation=generation+1 WHERE id=%s", (web.learner.learner_id,))
    later, later_csrf = browser(web, "learner@example.test")
    assert private(later, later_csrf, "/web/push/sync", phone).json == {"subscribed": False}
    assert bindings(web) == []
    # An address changed by the owner removes the learner's devices with their sessions.
    assert private(later, later_csrf, "/web/push/subscribe", phone).status_code == 200
    admin = owner_admin(web)
    act(admin, "set_email", web.learner.learner_id, {"email": "new.address@example.test"})
    assert bindings(web, web.learner.learner_id) == []


@pytest.mark.postgres
def test_gone_devices_are_removed_and_failures_are_reported_without_blocking_email(web):
    first, first_csrf = browser(web, "learner@example.test")
    laptop, laptop_csrf = browser(web, "learner@example.test")
    phone, desk = device(), device()
    subscribed(web, (first, first_csrf, phone), (laptop, laptop_csrf, desk))
    web.push.answers[phone["endpoint"]] = "gone"
    remind(web, web.learner)
    assert [r["endpoint"] for r in bindings(web)] == [desk["endpoint"]]
    assert push_rows(web)[-1]["status"] == "sent"
    # A push service outage fails the row visibly for the owner, keeps the device, adds nothing to
    # the learner's conversation and never holds back the email.
    web.push.answers[desk["endpoint"]] = ExternalError("push_http_503")
    remind(web, web.learner)
    row = push_rows(web)[-1]
    assert row["status"] == "failed" and row["error_code"] == "push_http_503"
    assert [r["endpoint"] for r in bindings(web)] == [desk["endpoint"]]
    with web.bot.repo.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM outbox WHERE id LIKE '%%:delivery-error'").fetchone()["n"]
            == 0
        )
        email = conn.execute(
            "SELECT status FROM outbox WHERE job_id=(SELECT job_id FROM outbox WHERE id=%s) AND body->>'kind'='email'",
            (row["id"],),
        ).fetchone()
    assert email["status"] == "sent"
    assert web.bot.repo.failure_counts(web_mode=True, all_learners=True)["deliveries"] >= 1
    # A permanent refusal is recorded for that device and stays visible; it is not retried forever.
    web.push.answers[desk["endpoint"]] = ExternalError("push_http_403", retryable=False)
    remind(web, web.learner)
    refused = push_rows(web)[-1]
    assert refused["status"] == "failed" and refused["error_code"] == "push_http_403"
    assert set(refused["body"]["outcomes"].values()) == {"push_http_403"}
    attempts = len(web.push.attempts)
    retry_now(web, refused)
    assert len(web.push.attempts) == attempts, "a device with an outcome is not sent again"
    # A failing email does not hold back the push either.
    web.push.answers.clear()
    web.email.fail = True
    remind(web, web.learner)
    assert push_rows(web)[-1]["status"] == "sent"


@pytest.mark.postgres
def test_push_sends_hold_no_database_locks(web):
    first, first_csrf = browser(web, "learner@example.test")
    subscribed(web, (first, first_csrf, device()))
    checked, errors = [], []

    def check():
        # A separate thread has its own connection, so a lock held by the sender would block here.
        try:
            with web.bot.repo.connection() as conn:
                conn.execute("SELECT id FROM learners FOR UPDATE NOWAIT")
                conn.execute("SELECT id FROM web_push_subscriptions FOR UPDATE NOWAIT")
                conn.execute("SELECT id FROM outbox FOR UPDATE NOWAIT")
                conn.execute("SELECT learner_id FROM coach_state FOR UPDATE NOWAIT")
                conn.execute("SELECT token_hash FROM web_sessions FOR UPDATE NOWAIT")
            checked.append(True)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(repr(exc))

    def no_locks(target):
        thread = threading.Thread(target=check)
        thread.start()
        thread.join()

    web.push.before = no_locks
    remind(web, web.learner)
    assert errors == [] and checked == [True]


@pytest.mark.postgres
def test_owner_address_change_and_disabled_push_stop_delivery(web):
    owner, owner_csrf = browser(web, "owner@example.test")
    subscribed(web, (owner, owner_csrf, device()))
    remind(web, web.bot.repo, deliver=False)
    web.bot.runtime.config = replace(web.bot.runtime.config, owner_email="new-owner@example.test")
    deliver(web)
    assert web.push.attempts == [] and push_rows(web)[-1]["status"] == "suppressed"
    web.bot.runtime.config = replace(web.bot.runtime.config, owner_email="owner@example.test")
    remind(web, web.bot.repo, deliver=False)
    web.bot.runtime.config = replace(web.bot.runtime.config, web_push_public_key="", web_push_private_key="")
    deliver(web)
    assert web.push.attempts == [] and push_rows(web)[-1]["status"] == "suppressed"
