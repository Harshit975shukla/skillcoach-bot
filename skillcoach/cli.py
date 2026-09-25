import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from pydantic import ValidationError

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import ConfigurationError
from skillcoach.migration import dry_run, load_snapshot
from skillcoach.runtime import STORAGE_ERRORS, Runtime
from skillcoach.storage import Repository
from skillcoach.timeutil import IST, now_ist
from skillcoach.web import authorized_update


def schedule_key(kind: str, day: date):
    valid = (
        day.weekday() < 5 if kind in ("lesson", "quiz") else day.weekday() == (5 if kind == "weekly" else 6)
    )
    if not valid:
        raise ValueError(f"{kind} does not run on {day.isoformat()}; no alternate job will be substituted")
    return f"schedule:{kind}:{day.isoformat()}"


def schedule(runtime: Runtime, kind: str, day: date, *, media=True):
    runtime.repo.enqueue(schedule_key(kind, day), {"type": "schedule", "kind": kind, "date": day.isoformat()})
    runtime.recover(media=media)


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
            status, data = authorized_update(update, runtime.config.owner_id)
            if status == "action":
                runtime.repo.enqueue(f"telegram:{update['update_id']}", data)
                if data.get("callback_id"):
                    try:
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
    recover = sub.add_parser("recover", help="Retry persisted processing/delivery; no new scheduled lessons")
    recover.add_argument("--no-media", action="store_true")
    sub.add_parser("status", help="Show non-sensitive durable queue counts")
    sub.add_parser("needs-media", help="Exit 0 for queued media/lesson work, 3 if absent")
    sub.add_parser("poll", help="Explicit local polling adapter; refuses an active webhook")
    run = sub.add_parser("schedule")
    run.add_argument("kind", choices=("lesson", "quiz", "weekly", "review"))
    run.add_argument("--no-media", action="store_true", help="Leave media for an equipped recovery worker")
    dates = run.add_mutually_exclusive_group()
    dates.add_argument("--date", type=date.fromisoformat, help="Intended Asia/Kolkata date")
    dates.add_argument(
        "--at", type=datetime.fromisoformat, help="Workflow creation timestamp including timezone"
    )
    importer = sub.add_parser("import-legacy")
    importer.add_argument("snapshot", type=Path)
    importer.add_argument("--apply", action="store_true")
    importer.add_argument(
        "--confirm-digest", help="Digest printed by a reviewed dry run; required with --apply"
    )
    args = parser.parse_args(argv)
    try:
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
            print(json.dumps(Repository(database_url()).status(), indent=2))
            return 0
        if args.command == "needs-media":
            return 0 if Repository(database_url()).needs_media() else 3
        runtime = Runtime.from_env()
        if args.command == "recover":
            runtime.recover(media=not args.no_media)
        elif args.command == "poll":
            polling(runtime)
        elif args.command == "schedule":
            if args.at and args.at.tzinfo is None:
                raise ValueError("--at must include a timezone")
            intended = args.date or (args.at.astimezone(IST).date() if args.at else now_ist().date())
            schedule(runtime, args.kind, intended, media=not args.no_media)
        counts = runtime.repo.status()
        print(json.dumps(counts))
        if any(row["status"] == "failed" and row["count"] for rows in counts.values() for row in rows):
            print(
                "Recoverable failures remain. Inspect private queue error codes; use /retry after fixing configuration.",
                file=sys.stderr,
            )
            return 1
        return 0
    except (ConfigurationError, ExternalError, ValueError, *STORAGE_ERRORS) as exc:
        code = exc.code if isinstance(exc, ExternalError) else type(exc).__name__
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
