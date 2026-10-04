"""Browser routes for web + email mode. Every endpoint except the static page answers 404 unless
DELIVERY_CHANNEL=web, so the Telegram deployment is unchanged by default."""

import logging
import re
from functools import wraps
from pathlib import Path

log = logging.getLogger(__name__)

TELEGRAM_SCRIPT = re.compile(r'[ \t]*<script src="https://telegram\.org/[^"]*"[^>]*></script>\r?\n?')
# Install metadata for the web dashboard page; /app (the Telegram Mini App) is left unchanged.
APP_HEAD = (
    '  <link rel="manifest" href="/web/manifest.webmanifest">\n'
    '  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">\n'
    '  <meta name="theme-color" content="#f5f7fa" media="(prefers-color-scheme: light)">\n'
    '  <meta name="theme-color" content="#17212b" media="(prefers-color-scheme: dark)">\n'
)
MANIFEST = {
    "id": "/web",
    "name": "SkillCoach",
    "short_name": "SkillCoach",
    "description": "Daily Cloud and DevOps lessons, quizzes and practice with your coach.",
    "start_url": "/web",
    "scope": "/web",
    "display": "standalone",
    "background_color": "#f5f7fa",
    "theme_color": "#f5f7fa",
    "icons": [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {
            "src": "/static/icon-maskable-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ],
}


def register_web(app, runtime_factory):
    from flask import jsonify, request
    from pydantic import ValidationError

    from skillcoach.clients import Budget, ExternalError
    from skillcoach.config import ConfigurationError
    from skillcoach.runtime import STORAGE_ERRORS, _left
    from skillcoach.web_channel import (
        LOGIN_COOKIE,
        SESSION_SECONDS,
        WEB_COOKIE,
        WebCodeIncorrect,
        WebDenied,
        WebLimited,
        WebUnavailable,
        accept_web,
        authenticate,
        csrf_token,
        digest,
        feed,
        keyed,
        logout,
        same_origin,
        start_login,
        verify_login,
        web_payload,
    )
    from skillcoach.web_join import JOIN_COOKIE, deliver_now, start_join, verify_join
    from skillcoach.web_media import serve as serve_media
    from skillcoach.web_media import wake as wake_worker
    from skillcoach.web_push import PushConflict
    from skillcoach.web_push import subscribe as push_subscribe
    from skillcoach.web_push import sync as push_sync
    from skillcoach.web_push import unsubscribe as push_unsubscribe

    class Disabled(Exception):
        pass

    class PushOff(Exception):
        pass

    def endpoint(function):
        @wraps(function)
        def handled(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Disabled:
                return jsonify(error="The web app is not switched on.", enabled=False), 404
            except PushOff:
                return jsonify(error="Notifications are not switched on.", push=False), 404
            except PushConflict as exc:
                return jsonify(error=str(exc)), 409
            except WebCodeIncorrect as exc:
                return jsonify(error=str(exc)), 400
            except WebLimited as exc:
                return jsonify(error=str(exc)), 429
            except WebDenied as exc:
                return jsonify(error=str(exc)), 403
            except WebUnavailable as exc:
                return jsonify(error=str(exc)), 503
            except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
                return jsonify(error="SkillCoach is temporarily unavailable. Try again shortly."), 503

        return handled

    def runtime_on():
        runtime = runtime_factory()
        if not runtime.config.web_mode:
            raise Disabled()
        return runtime

    def push_on():
        runtime = runtime_on()
        if not runtime.config.push_enabled:
            raise PushOff()
        return runtime

    def push_key(runtime):
        return runtime.config.web_push_public_key if runtime.config.push_enabled else None

    def body_of(fields):
        body = request.get_json(silent=True)
        if request.args or not isinstance(body, dict) or not set(body) <= set(fields):
            raise WebDenied("Unexpected request fields. Refresh the page.")
        return body

    def cookie(response, name, value, seconds):
        response.set_cookie(
            name, value, max_age=seconds, secure=True, httponly=True, samesite="Strict", path="/"
        )

    def forget(response, name):
        response.delete_cookie(name, secure=True, httponly=True, samesite="Strict", path="/")

    @app.get("/web")
    def web_page():
        return app.send_static_file("web.html")

    @app.get("/web/practice")
    def web_practice_page():
        """Practice: short answer-first lessons. The page is public; its data needs the /web session."""
        return app.send_static_file("practice.html")

    @app.post("/web/practice/catalog")
    @endpoint
    def web_practice_catalog():
        """The practice path. Read-only: progress stays on the learner's device under an opaque key
        that differs per learner, so people sharing a browser never see each other's progress."""
        from skillcoach.practice import catalog

        runtime = runtime_on()
        session, _ = authenticate(request, runtime, mutate=True)
        body_of(set())
        data = catalog()
        data["progress_key"] = keyed(runtime.config, "practice", session["learner_id"])[:32]
        return jsonify(data)

    @app.post("/web/practice/lesson")
    @endpoint
    def web_practice_lesson():
        from skillcoach.practice import lesson as practice_lesson

        runtime = runtime_on()
        authenticate(request, runtime, mutate=True)
        body = body_of({"topic", "lesson"})
        topic, lesson_id = body.get("topic"), body.get("lesson")
        data = (
            practice_lesson(topic, lesson_id) if isinstance(topic, str) and isinstance(lesson_id, str) else None
        )
        if data is None:
            return jsonify(error="Choose a lesson from the practice path."), 404
        return jsonify(data)

    @app.post("/web/practice/review")
    @endpoint
    def web_practice_review():
        """The questions behind the learner's due spaced-review cards (IDs only; no answers sent)."""
        from skillcoach.practice import REVIEW_LIMIT, review

        runtime = runtime_on()
        authenticate(request, runtime, mutate=True)
        items = body_of({"items"}).get("items")
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= REVIEW_LIMIT
            or not all(isinstance(item, str) and len(item) <= 220 for item in items)
        ):
            raise WebDenied("Choose up to 20 review cards.")
        return jsonify(steps=review(items))

    @app.get("/web/dashboard")
    @endpoint
    def web_dashboard():
        """The private dashboard for web learners: the Mini App page without Telegram's script, so no
        third-party code runs beside private progress. Its data still needs the /web session."""
        runtime_on()
        page = TELEGRAM_SCRIPT.sub(
            "", (Path(app.static_folder) / "dashboard.html").read_text(encoding="utf-8")
        )
        if "telegram.org" in page:
            raise ConfigurationError("The web dashboard page must not load Telegram's script.")
        page = page.replace("</head>", APP_HEAD + "</head>", 1)
        return page, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/web/manifest.webmanifest")
    @endpoint
    def web_manifest():
        runtime_on()
        response = jsonify(MANIFEST)
        response.mimetype = "application/manifest+json"
        return response

    @app.get("/web/sw.js")
    @endpoint
    def web_service_worker():
        """The service worker: an offline notice and notifications only. Served under /web with a
        scope of /web, so it never controls /app, /admin or anything else on this origin."""
        runtime_on()
        response = app.send_static_file("web-sw.js")
        response.headers["Content-Type"] = "text/javascript; charset=utf-8"
        response.headers["Service-Worker-Allowed"] = "/web"
        return response

    @app.get("/web/offline")
    @endpoint
    def web_offline():
        runtime_on()
        return app.send_static_file("web-offline.html")

    @app.get("/web/session")
    @endpoint
    def web_session():
        runtime = runtime_on()
        session, token = authenticate(request, runtime)
        return jsonify(
            authenticated=True,
            csrf=csrf_token(runtime.config, token),
            name="You (owner)" if session["learner_id"] == "owner" else session["display_name"] or "Learner",
            expires_at=session["expires_at"].isoformat(),
            push_key=push_key(runtime),
        )

    @app.post("/web/login/start")
    @endpoint
    def web_login_start():
        same_origin(request)
        body = body_of({"email"})
        runtime = runtime_on()
        data, verifier = start_login(runtime, body.get("email"))
        response = jsonify(data)
        cookie(response, LOGIN_COOKIE, verifier, 600)
        return response

    @app.post("/web/login/verify")
    @endpoint
    def web_login_verify():
        same_origin(request)
        body = body_of({"code"})
        runtime = runtime_on()
        token, expires, member = verify_login(
            runtime, request.cookies.get(LOGIN_COOKIE, ""), body.get("code")
        )
        response = jsonify(
            authenticated=True,
            csrf=csrf_token(runtime.config, token),
            name="You (owner)" if member["id"] == "owner" else member["display_name"] or "Learner",
            expires_at=expires.isoformat(),
            push_key=push_key(runtime),
        )
        cookie(response, WEB_COOKIE, token, SESSION_SECONDS)
        forget(response, LOGIN_COOKIE)
        return response

    @app.post("/web/join/start")
    @endpoint
    def web_join_start():
        same_origin(request)
        body = body_of({"invite", "name", "email"})
        runtime = runtime_on()
        data, verifier = start_join(runtime, body.get("invite"), body.get("name"), body.get("email"))
        response = jsonify(data)
        cookie(response, JOIN_COOKIE, verifier, 600)
        return response

    @app.post("/web/join/verify")
    @endpoint
    def web_join_verify():
        same_origin(request)
        body = body_of({"code"})
        runtime = runtime_on()
        result = verify_join(runtime, request.cookies.get(JOIN_COOKIE, ""), body.get("code"))
        # The owner's "new request" email goes out now rather than at the next worker run.
        deliver_now(runtime)
        response = jsonify(result)
        forget(response, JOIN_COOKIE)
        return response

    @app.post("/web/logout")
    @endpoint
    def web_logout():
        same_origin(request)
        body_of(set())
        runtime = runtime_on()
        logout(runtime, request.cookies.get(WEB_COOKIE, ""))
        response = jsonify(logged_out=True)
        forget(response, WEB_COOKIE)
        return response

    # Notifications: the learner always comes from the signed-in session, never from the request.
    @app.post("/web/push/subscribe")
    @endpoint
    def web_push_subscribe():
        runtime = push_on()
        session, token = authenticate(request, runtime, mutate=True)
        body = body_of({"endpoint", "p256dh", "auth"})
        with runtime.repo.session():
            return jsonify(push_subscribe(runtime, session, token, body))

    @app.post("/web/push/sync")
    @endpoint
    def web_push_sync():
        runtime = push_on()
        session, token = authenticate(request, runtime, mutate=True)
        body = body_of({"endpoint", "p256dh", "auth"})
        with runtime.repo.session():
            return jsonify(push_sync(runtime, session, token, body))

    @app.post("/web/push/unsubscribe")
    @endpoint
    def web_push_unsubscribe():
        runtime = push_on()
        session, _ = authenticate(request, runtime, mutate=True)
        body = body_of({"endpoint"})
        with runtime.repo.session():
            return jsonify(push_unsubscribe(runtime, session, body))

    @app.post("/web/feed")
    @endpoint
    def web_feed():
        runtime = runtime_on()
        session, _ = authenticate(request, runtime, mutate=True)
        body = body_of({"after", "before"})
        cursors = {key: body.get(key) for key in ("after", "before")}
        for value in cursors.values():
            if value is not None and (type(value) is not int or value < 0):
                raise WebDenied("Invalid message position.")
        with runtime.repo.session():
            result = feed(runtime.repo, session, runtime.config, **cursors)
            if result["preparing"] or result["working"]:
                # Only this learner's own due work can ask for a worker (rate-limited, see web_media).
                try:
                    wake_worker(runtime, session)
                except STORAGE_ERRORS:
                    log.warning("media_wake_failed code=storage")
        return jsonify(result)

    @app.route("/web/media/<media_id>", methods=["GET", "HEAD"])
    @endpoint
    def web_media_file(media_id):
        """A video or still from the signed-in learner's own delivered messages. Same-origin only:
        the session cookie is SameSite=Strict and the response is CORP same-origin and never cached."""
        runtime = runtime_on()
        if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            raise WebDenied("Open SkillCoach to watch this video.")
        session, token = authenticate(request, runtime)
        with runtime.repo.session():
            status, headers, data = serve_media(
                runtime,
                session,
                digest(token),
                media_id,
                request.method,
                request.headers.get("Range"),
                request.headers.get("If-Range"),
            )
        response = app.response_class(data, status=status)
        # Set after the body, so a HEAD response keeps the real length.
        for name, value in headers.items():
            response.headers[name] = value
        return response

    @app.post("/web/send")
    @endpoint
    def web_send():
        runtime = runtime_on()
        session, _ = authenticate(request, runtime, mutate=True)
        request_body = request.get_json(silent=True)
        if request.args or not isinstance(request_body, dict):
            raise WebDenied("Unexpected request fields. Refresh the page.")
        payload = web_payload(request_body)
        budget = Budget(20)
        with runtime.repo.session():
            outcome, key = accept_web(runtime.repo, session, request_body["request_id"], payload)
            if outcome == "denied":
                raise WebDenied("Your access changed. Sign in again.")
            # Process and deliver inline so the reply usually appears at once; the scheduled
            # recovery worker finishes anything that does not fit in this request.
            for _ in range(2):
                if _left(budget) < 12 or not runtime.process_one(budget):
                    break
                for _ in range(10):
                    if not runtime.deliver_one(budget):
                        break
            for _ in range(10):
                if not runtime.deliver_one(budget):
                    break
            if outcome == "queued":
                runtime.followup(key, budget)
        return jsonify(status=outcome), 202

    @app.post("/web/lesson")
    @endpoint
    def web_lesson():
        from skillcoach.catalog import TOPICS
        from skillcoach.course_library import page as course_page
        from skillcoach.lesson_delivery import LESSON_ID, page

        runtime = runtime_on()
        session, _ = authenticate(request, runtime, mutate=True)
        body = body_of({"lesson", "topic"})
        if len(body) != 1:
            raise WebDenied("Open one lesson at a time.")
        scoped = runtime.repo.for_learner(session["learner_id"])
        with runtime.repo.session():
            if "topic" in body:
                if not isinstance(body["topic"], str) or body["topic"] not in TOPICS:
                    return jsonify(error="Choose a topic from the lesson library."), 404
                scoped.record_usage("course_page", runtime.clock())
                return jsonify(lesson=course_page(body["topic"]), private=True)
            if not isinstance(body["lesson"], str) or not LESSON_ID.fullmatch(body["lesson"]):
                return jsonify(error="That lesson link is not valid."), 404
            _, state = scoped.read()
            data = page(scoped, state, body["lesson"], runtime.clock())
            if data is None:
                return jsonify(error="This lesson is not in your learning history."), 404
            scoped.record_usage("lesson_page", runtime.clock())
            return jsonify(lesson=data, private=True)
