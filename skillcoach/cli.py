import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import ConfigurationError
from skillcoach.migration import dry_run, load_snapshot
from skillcoach.runtime import STORAGE_ERRORS, Runtime
from skillcoach.scheduler import slot_date
from skillcoach.storage import MembershipChanged, Repository
from skillcoach.timeutil import now_ist, requested_quiz_payload
from skillcoach.web import authorized_update


def schedule_key(kind: str, day: date):
    valid = (
        day.weekday() < 5 if kind in ("lesson", "quiz") else day.weekday() == (5 if kind == "weekly" else 6)
    )
    if not valid:
        raise ValueError(f"{kind} does not run on {day.isoformat()}; no alternate job will be substituted")
    return f"schedule:{kind}:{day.isoformat()}"


def schedule(runtime: Runtime, kind: str, day: date, *, media=True):
    key = schedule_key(kind, day)
    for learner in runtime.repo.active_learners():
        scoped = runtime.repo.for_learner(learner)
        try:
            _, state = scoped.read()
            # A week-long pause that has ended gets this run so the worker can switch coaching back on.
            if not state.paused or (state.pause_until and state.pause_until <= runtime.clock()):
                scoped.enqueue(key, {"type": "schedule", "kind": kind, "date": day.isoformat()})
        except MembershipChanged:
            logging.info("schedule_skipped_access_changed")
    runtime.recover(media=media)
    alert_late(runtime, kind, day)


LATE_AFTER = timedelta(minutes=20)


def alert_late(runtime: Runtime, kind: str, day: date):
    """Tell the owner once when a slot reached learners late or is still waiting after 20 minutes."""
    from skillcoach.scheduler import slot_instant

    due = slot_instant(kind, day)
    now = runtime.clock()
    if now - due < LATE_AFTER:
        return None
    late = [
        row
        for row in runtime.repo.slot_deliveries(schedule_key(kind, day))
        if row["waiting"] or (row["last_sent"] is not None and row["last_sent"] - due > LATE_AFTER)
    ]
    if not late:
        return None
    reached = [row["last_sent"] for row in late if row["last_sent"] is not None]
    worst = round((max(reached) - due).total_seconds() / 60) if reached else None
    text = (
        f"⚠️ Delivery delay: the {day:%a %d %b} {kind} for {len(late)} learner"
        f"{'s' if len(late) > 1 else ''}"
        + (
            f" finished {worst} min after {due:%H:%M} IST."
            if worst is not None
            else f" (due {due:%H:%M} IST)."
        )
        + (
            " Some parts are still waiting; recovery keeps retrying and /status shows the queue."
            if any(row["waiting"] for row in late)
            else ""
        )
    )
    key = f"alert:late:{kind}:{day.isoformat()}"
    if runtime.repo.enqueue(key, {"type": "notice", "text": text}):
        runtime.recover(limit=3, media=False)
    return key


MENU = (
    ("menu", "Home: your next step"),
    ("today", "Today's lesson, quiz and exercises"),
    ("review", "Spaced review of past questions"),
    ("quizzes", "Quizzes to finish this week"),
    ("progress", "Study days, streak and accuracy"),
    ("ask", "Ask the AI tutor"),
    ("dashboard", "Open your private dashboard"),
    ("pause", "Pause scheduled coaching"),
    ("help", "All commands"),
)


def configure_telegram(runtime: Runtime):
    """Idempotently set the bot's command menu and, when configured, the dashboard menu button."""
    runtime.telegram.call(
        "setMyCommands", Budget(), data={"commands": [{"command": c, "description": d} for c, d in MENU]}
    )
    url = runtime.config.private_dashboard_url
    if url:
        runtime.telegram.call(
            "setChatMenuButton",
            Budget(),
            data={"menu_button": {"type": "web_app", "text": "Dashboard", "web_app": {"url": url}}},
        )
    return {"commands": len(MENU), "menu_button": bool(url)}


def email_test(runtime: Runtime):
    """Check SMTP settings by emailing the owner; nothing is stored and no learner is contacted."""
    config = runtime.config
    if not config.email_configured or not config.owner_email:
        raise ConfigurationError("Set OWNER_EMAIL, EMAIL_FROM, SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD.")
    runtime.email.send(
        config.owner_email,
        "SkillCoach email test",
        "SkillCoach can send email with these settings. Web sign-in codes and reminders will arrive "
        "from this address when web mode is switched on.",
        Budget(30),
    )
    return {"sent": True, "to": "OWNER_EMAIL"}


def queue_owner_quiz(runtime: Runtime, due: datetime, topic: str):
    due, payload = requested_quiz_payload(runtime.clock(), due, topic)
    _, state = runtime.repo.read()
    if state.paused:
        raise ValueError("Owner notifications are paused. No quiz was queued; use /unpause explicitly.")
    key = f"requested:quiz:{due.date().isoformat()}"
    created = runtime.repo.enqueue(
        key,
        payload,
        available_at=due,
    )
    return {
        "job": key,
        "created": created,
        "due_at": due.isoformat() if created else None,
        "owner_only": True,
        "existing_request_unchanged": not created,
    }


def polling(runtime: Runtime):
    info = runtime.telegram.call("getWebhookInfo", Budget())
    if info.get("url"):
        raise ConfigurationError("Polling refused: a webhook is registered. This adapter never removes it.")
    offset = None
    while True:
        payload = {"timeout": 0, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        updates = runtime.telegram.call("getUpdates", Budget(), data=payload)
        for update in updates:
            status, data = authorized_update(update)
            if status == "action":
                runtime.repo.accept_update(update["update_id"], data, runtime.config)
                if data.get("callback_id"):
                    from skillcoach.telegram_copies import may_acknowledge

                    try:
                        if may_acknowledge(runtime.repo, runtime.config, data["actor_id"]):
                            runtime.telegram.acknowledge(data["callback_id"], Budget())
                    except ExternalError:
                        logging.warning("poll_callback_ack_failed")
            # Acknowledge only after durable insertion; dedup handles restart replay.
            offset = update["update_id"] + 1
        runtime.recover(limit=50, media=True)
        time.sleep(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private SkillCoach operations; never deploys automatically")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Explicitly apply additive PostgreSQL schema migrations")
    sub.add_parser("bootstrap-fresh", help="Explicit empty-project migration and least-privilege role setup")
    upgrade = sub.add_parser(
        "upgrade-schema", help="Additive existing-owner migration; requires stopped writers"
    )
    upgrade.add_argument("--writers-stopped", action="store_true")
    recover = sub.add_parser("recover", help="Retry persisted processing/delivery; no new scheduled lessons")
    recover.add_argument("--no-media", action="store_true")
    sub.add_parser("status", help="Show non-sensitive durable queue counts")
    announce = sub.add_parser("announce-ready", help="Send one idempotent owner help message for a release")
    announce.add_argument("--release", required=True)
    sub.add_parser("needs-media", help="Exit 0 for queued media/lesson work, 3 if absent")
    sub.add_parser("telegram-status", help="Show Telegram copy health (both mode); states and counts only")
    restore = sub.add_parser(
        "telegram-restore",
        help="After the owner has messaged the bot, let copies go to the owner only until a fresh reply is accepted",
    )
    restore.add_argument("--confirm", action="store_true")
    gate = sub.add_parser(
        "telegram-gate", help="Pause every Telegram copy on purpose before copies start (both mode)"
    )
    gate.add_argument("--confirm", action="store_true")
    copies_off = sub.add_parser(
        "telegram-copies-off",
        help="Before running code without Telegram copies: withdraw every open copy (web mode only)",
    )
    copies_off.add_argument("--confirm", action="store_true")
    sub.add_parser("email-test", help="Send one test email to OWNER_EMAIL to check SMTP settings")
    sub.add_parser("poll", help="Explicit local polling adapter; refuses an active webhook")
    sub.add_parser("configure-telegram", help="Set the bot command menu and dashboard menu button")
    run = sub.add_parser("schedule")
    run.add_argument("kind", choices=("lesson", "quiz", "weekly", "review"))
    run.add_argument("--no-media", action="store_true", help="Leave media for an equipped recovery worker")
    dates = run.add_mutually_exclusive_group()
    dates.add_argument("--date", type=date.fromisoformat, help="Intended Asia/Kolkata date")
    dates.add_argument(
        "--at", type=datetime.fromisoformat, help="Workflow creation timestamp including timezone"
    )
    quiz = sub.add_parser(
        "queue-owner-quiz", help="Queue one owner-only quiz without changing recurring schedules"
    )
    quiz.add_argument("--at", required=True, type=datetime.fromisoformat)
    quiz.add_argument("--topic", required=True)
    importer = sub.add_parser("import-legacy")
    importer.add_argument("snapshot", type=Path)
    importer.add_argument("--apply", action="store_true")
    importer.add_argument(
        "--confirm-digest", help="Digest printed by a reviewed dry run; required with --apply"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "upgrade-schema":
            from skillcoach.bootstrap import upgrade_existing

            if not args.writers_stopped:
                raise ValueError("Pause webhooks and scheduled workers and back up current state first.")
            print(json.dumps(upgrade_existing(database_url()), indent=2))
            return 0
        if args.command == "bootstrap-fresh":
            from skillcoach.bootstrap import bootstrap_fresh

            report = bootstrap_fresh(database_url(), os.getenv("SKILLCOACH_RUNTIME_PASSWORD", ""))
            print(json.dumps(report))
            return 0
        if args.command == "import-legacy":
            snapshot, digest = load_snapshot(args.snapshot)
            report = dry_run(snapshot, digest)
            if not args.apply:
                print(json.dumps(report, indent=2))
                return 0
            if args.confirm_digest != digest:
                raise ValueError("Review a dry run and supply its exact --confirm-digest before --apply")
            repository = Repository(database_url())
            repository.enqueue(f"import:{digest}", {"type": "import", "snapshot": snapshot, "digest": digest})
            # Import is a local transaction with no Telegram, GitHub or AI side effects.
            token = repository.acquire("domain", 60)
            if not token:
                raise ValueError("Worker busy; import remains queued. Run recovery or repeat import later.")
            try:
                from skillcoach.migration import import_snapshot

                revision, state = repository.read()
                state = import_snapshot(state, snapshot, digest)
                repository.finish(f"import:{digest}", token, revision, state, [], [])
            finally:
                repository.release("domain", token)
            print(json.dumps({**report, "writes": True, "status": "imported"}, indent=2))
            return 0
        if args.command == "migrate":
            Repository(database_url()).migrate()
            print("Private schema migrations applied.")
            return 0
        if args.command == "status":
            print(json.dumps(Repository(database_url()).status(all_learners=True), indent=2))
            return 0
        if args.command == "needs-media":
            return 0 if Repository(database_url()).needs_media() else 3
        if args.command in ("telegram-status", "telegram-restore", "telegram-gate", "telegram-copies-off"):
            from skillcoach import telegram_copies
            from skillcoach.config import Config

            config = Config.from_env()
            repository = Repository(database_url())
            if args.command == "telegram-status":
                print(json.dumps(telegram_copies.status(repository, config), indent=2))
                return 0
            if not args.confirm:
                raise ValueError(
                    {
                        "telegram-restore": "Restoration resumes Telegram copies to the owner first",
                        "telegram-gate": "The gate pauses every Telegram copy until restoration",
                        "telegram-copies-off": "This withdraws every open Telegram copy",
                    }[args.command]
                    + "; rerun with --confirm."
                )
            action = {
                "telegram-restore": (telegram_copies.restore, "restored"),
                "telegram-gate": (telegram_copies.gate, "gated"),
                "telegram-copies-off": (telegram_copies.copies_off, "withdrawn"),
            }[args.command]
            result = action[0](repository, config)
            print(json.dumps(result))
            return 0 if result[action[1]] else 4
        runtime = Runtime.from_env()
        if args.command == "email-test":
            print(json.dumps(email_test(runtime)))
            return 0
        if args.command == "configure-telegram":
            print(json.dumps(configure_telegram(runtime)))
            return 0
        if args.command == "queue-owner-quiz":
            print(json.dumps(queue_owner_quiz(runtime, args.at, args.topic), indent=2))
            return 0
        if args.command == "announce-ready":
            if not re.fullmatch(r"[0-9a-f]{7,40}", args.release):
                raise ValueError("--release must be a Git commit identifier.")
            runtime.repo.enqueue(f"maintenance:ready:{args.release}", {"type": "telegram", "text": "/start"})
            runtime.recover(media=False)
        elif args.command == "recover":
            runtime.recover(media=not args.no_media)
        elif args.command == "poll":
            polling(runtime)
        elif args.command == "schedule":
            if args.at and args.at.tzinfo is None:
                raise ValueError("--at must include a timezone")
            if args.date:
                intended = args.date
            elif args.at:
                # A late scheduled run keeps its slot's date; it never claims the next slot's key.
                intended = slot_date(args.kind, args.at)
            else:
                intended = now_ist().date()
            schedule(runtime, args.kind, intended, media=not args.no_media)
        counts = runtime.repo.status(all_learners=True)
        failures = runtime.repo.failure_counts(web_mode=runtime.config.web_mode, all_learners=True)
        print(json.dumps({**counts, "failures": failures}))
        if failures["telegram_history"]:
            print(
                f"{failures['telegram_history']} Telegram deliveries that failed before the switch to web mode "
                "are kept as history; web mode never re-sends them.",
                file=sys.stderr,
            )
        if failures["jobs"] or failures["deliveries"]:
            print(
                "Recoverable failures remain. Inspect private queue error codes; use /retry after fixing configuration.",
                file=sys.stderr,
            )
            return 1
        return 0
    except (ConfigurationError, ExternalError, ValueError, *STORAGE_ERRORS) as exc:
        code = exc.code if isinstance(exc, ExternalError) else type(exc).__name__
        if isinstance(exc, STORAGE_ERRORS):
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate:
                code = f"postgres_{sqlstate}"
            elif "certificate" in str(exc).lower():
                code = "postgres_certificate_validation_failed"
            elif "timeout" in str(exc).lower():
                code = "postgres_connection_timeout"
        logging.error("operation_failed code=%s", code)
        # Database exceptions can contain secrets; print only our validation/configuration messages.
        if isinstance(exc, (ConfigurationError, ValueError)) and not isinstance(exc, ValidationError):
            print(str(exc), file=sys.stderr)
        return 1


def database_url():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgres://")):
        raise ConfigurationError("DATABASE_URL must point to private PostgreSQL.")
    return url


def legacy_schedule(kind: str):
    return main(["schedule", kind, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
