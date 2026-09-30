"""Browser routes for web + email mode. Every endpoint except the static page answers 404 unless
DELIVERY_CHANNEL=web, so the Telegram deployment is unchanged by default."""

from functools import wraps


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
        accept_web,
        authenticate,
        csrf_token,
        feed,
        logout,
        same_origin,
        start_login,
        verify_login,
        web_payload,
    )

    class Disabled(Exception):
        pass

    def endpoint(function):
        @wraps(function)
        def handled(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Disabled:
                return jsonify(error="The web app is not switched on.", enabled=False), 404
            except WebCodeIncorrect as exc:
                return jsonify(error=str(exc)), 400
            except WebLimited as exc:
                return jsonify(error=str(exc)), 429
            except WebDenied as exc:
                return jsonify(error=str(exc)), 403
            except (ConfigurationError, ValidationError, ExternalError, *STORAGE_ERRORS):
                return jsonify(error="SkillCoach is temporarily unavailable. Try again shortly."), 503

        return handled

    def runtime_on():
        runtime = runtime_factory()
        if not runtime.config.web_mode:
            raise Disabled()
        return runtime

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
        )
        cookie(response, WEB_COOKIE, token, SESSION_SECONDS)
        forget(response, LOGIN_COOKIE)
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
            return jsonify(feed(runtime.repo, session, runtime.config, **cursors))

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
