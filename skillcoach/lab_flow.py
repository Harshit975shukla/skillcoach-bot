"""Hands-on lab assignment, in-app scenarios and evidence checks. Required labs carry forward, never block."""

import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from skillcoach.lab_checks import message
from skillcoach.labs import (
    COST,
    LABS,
    ROUTE_LABELS,
    TEMPLATE_BLOBS,
    lab_steps,
    labs_for_topic,
    new_token,
    required_quota,
    url_digest,
)

DAILY_CHECKS = 12
DAILY_ATTEMPTS = 3
CARRY_DAYS = 28
PASS_MARK = 3
LETTERS = "ABCD"


def active_plan(state):
    from skillcoach.journey import approved_plan

    return approved_plan(state)


def active_keys(state):
    plan = active_plan(state)
    return {d.lesson_key for d in plan.sessions if d.lesson_key} if plan else set()


def pending_required(state):
    """Required, unverified labs from the current week or carried over from an earlier one."""
    keys = active_keys(state)
    return [
        a
        for a in state.labs.values()
        if a.required and a.status != "verified" and (a.carried_at is not None or a.lesson_key in keys)
    ]


def blocking(state, config):
    """Nothing holds planning any more; unfinished required labs carry forward instead."""
    return []


def carry_forward(state, now):
    """Carry a finished week's unverified required labs into the next week, without limits."""
    carried = [a for a in pending_required(state) if a.carried_at is None]
    for item in carried:
        item.carried_at = now
    return carried


def canonical_link(url):
    parts = urlsplit(url)
    return parts.scheme.lower() + "://" + (parts.hostname or "") + parts.path


def week_finished(state):
    plan = active_plan(state)
    return bool(plan and all(state.lessons.get(d.lesson_key, {}).get("delivered_at") for d in plan.sessions))


def lab_view(state, config, now):
    """Private learner dashboard DTO. Never includes submitted URLs or digests."""
    from skillcoach.resources import related_view

    open_required = pending_required(state) if config.labs_enabled else []
    items = []
    for a in sorted(state.labs.values(), key=lambda x: (x.status == "verified", x.assigned_date, x.id)):
        lab = LABS.get(a.lab_id)
        if not lab:
            continue
        routes = []
        # Verified labs need no steps, and their steps would re-expose the token.
        for route in lab.routes if a.status != "verified" else ():
            steps, cleanup, submit = lab_steps(lab, route, a.token, config.labs_template_repo)
            routes.append(
                {
                    "route": route,
                    "label": ROUTE_LABELS[route],
                    "steps": steps,
                    "cleanup": cleanup,
                    "submit": submit,
                    "accepts_link": route not in ("scenario", "local"),
                }
            )
        items.append(
            {
                "id": a.id,
                "lab_id": lab.id,
                "title": lab.title,
                "goal": lab.goal,
                "minutes": lab.minutes,
                "required": a.required,
                "blocking": False,
                "carried": a.carried_at is not None,
                "status": a.status,
                "reason": message(a.result_code) if a.status == "needs_fix" else None,
                "token": a.token if a.status != "verified" else None,
                "assigned_date": a.assigned_date.isoformat(),
                "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                "verified_route": ROUTE_LABELS.get(a.route) if a.status == "verified" else None,
                "cleanup": a.cleanup,
                "routes": routes,
                "references": list(lab.references),
                "resources": related_view(lab.topics[0]),
            }
        )
    return {
        "enabled": config.labs_enabled,
        "template_repo": config.labs_template_repo,
        "cost_note": COST,
        "gate": {"blocked": False, "waiting_since": None, "required_pending": len(open_required)},
        "carry_available": False,
        "items": items[:40],
        "catalog": [
            {"lab_id": lab.id, "title": lab.title, "minutes": lab.minutes, "routes": list(lab.routes)}
            for lab in LABS.values()
        ],
    }


def admin_counts(state, enabled):
    """Owner-safe counts only: no tokens, links, routes, answers or result details."""
    labs = list(state.labs.values())
    return {
        "required": sum(a.required for a in labs),
        "verified": sum(a.status == "verified" for a in labs),
        "pending": sum(a.status != "verified" for a in labs),
        "gate_blocked": False,
    }


class LabSubmitError(ValueError):
    pass


def queue_submission(runtime, identity, request_id, assignment_id, url):
    """Queue one dashboard lab check as a durable job bound to the learner's current access generation."""
    from uuid import UUID

    from psycopg.types.json import Jsonb

    from skillcoach.models import State

    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise LabSubmitError("A valid request identifier is required.") from None
    if (
        not isinstance(assignment_id, str)
        or not 0 < len(assignment_id) <= 64
        or not isinstance(url, str)
        or not 0 < len(url) <= 2048
        or any(c.isspace() for c in url)
        or not url.startswith("https://")
    ):
        raise LabSubmitError("Paste one complete https:// link for this lab.")
    learner, generation, _ = identity
    key = f"labsubmit:{learner}:{request_id}"
    with runtime.repo.connection() as conn:
        member = conn.execute("SELECT * FROM learners WHERE id=%s FOR UPDATE", (learner,)).fetchone()
        if not member or member["status"] != "active" or member["generation"] != generation:
            raise LabSubmitError("Access changed. Reopen your personal dashboard.")
        existing = conn.execute(
            "SELECT payload FROM jobs WHERE id=%s AND learner_id=%s", (key, learner)
        ).fetchone()
        if existing:
            if existing["payload"].get("assignment_id") != assignment_id:
                raise LabSubmitError("That request was already used for another lab. Refresh and try again.")
            return {"queued": True, "duplicate": True}
        if not runtime.config.labs_enabled:
            raise LabSubmitError("Hands-on labs are temporarily turned off. Lessons and quizzes continue.")
        row = conn.execute("SELECT body FROM coach_state WHERE learner_id=%s", (learner,)).fetchone()
        item = State.model_validate(row["body"]).labs.get(assignment_id)
        if item is None or item.lab_id not in LABS:
            raise LabSubmitError("That lab is no longer available. Refresh your dashboard.")
        if item.status == "verified":
            raise LabSubmitError("This lab is already verified. No new check was queued.")
        busy = conn.execute(
            "SELECT 1 FROM jobs WHERE learner_id=%s AND payload->>'type'='lab' "
            "AND (status IN ('pending','running') OR (status='failed' AND attempts<5)) LIMIT 1",
            (learner,),
        ).fetchone()
        if busy:
            raise LabSubmitError(
                "A lab check is already queued. Wait for its result before submitting again."
            )
        recent = conn.execute(
            "SELECT count(*) AS n FROM jobs WHERE learner_id=%s AND payload->>'type'='lab' "
            "AND created_at>now()-interval '1 day'",
            (learner,),
        ).fetchone()["n"]
        if recent >= DAILY_CHECKS:
            raise LabSubmitError("You reached today's limit of 12 lab checks. Try again tomorrow.")
        conn.execute(
            "INSERT INTO jobs(id,payload,learner_id,access_generation) VALUES (%s,%s,%s,%s)",
            (
                key,
                Jsonb({"type": "lab", "action": "submit", "assignment_id": assignment_id, "url": url}),
                learner,
                generation,
            ),
        )
    return {"queued": True, "duplicate": False}


class LabFlow:
    def __init__(self, service):
        self.s = service

    @property
    def state(self):
        return self.s.state

    @property
    def config(self):
        return self.s.config

    def checker(self):
        if getattr(self.s, "labs", None) is None:
            from skillcoach.lab_checks import LabChecker

            self.s.labs = LabChecker(self.config)
        return self.s.labs

    def today(self):
        return self.s.now.date()

    # Assignment -----------------------------------------------------------------------------

    def assign(self, topic, key, day, session, study_plan):
        from skillcoach.service import stable_id

        if session is None or study_plan is None or not study_plan.labs_enabled:
            return
        if not self.config.labs_enabled:
            return
        verified = {a.lab_id for a in self.state.labs.values() if a.status == "verified"}
        lab = next((item for item in labs_for_topic(topic) if item.id not in verified), None)
        if lab is None:
            return
        keys = {d.lesson_key for d in study_plan.sessions if d.lesson_key}
        used = sum(a.required for a in self.state.labs.values() if a.lesson_key in keys)
        required = used < required_quota(study_plan.minutes)
        existing = next(
            (a for a in self.state.labs.values() if a.lab_id == lab.id and a.status != "verified"), None
        )
        if existing and existing.lesson_key is not None:
            return
        if existing:
            item = existing
        else:
            from skillcoach.models import LabAssignment

            item = LabAssignment(
                id=stable_id(f"lab:{key}:{lab.id}"),
                lab_id=lab.id,
                token=new_token(),
                assigned_date=day,
            )
            self.state.labs[item.id] = item
        item.lesson_key, item.plan_id, item.required = key, study_plan.id, required
        self.announce(item, lesson=True)

    def announce(self, item, *, lesson=False):
        lab = LABS[item.lab_id]
        routes = ", ".join(ROUTE_LABELS[r] for r in lab.routes)
        status = (
            "REQUIRED LAB — it carries forward if unfinished; your plan never waits for it."
            if item.required
            else "OPTIONAL LAB — extra practice; it does not block your plan."
        )
        self.s.say(
            ("HANDS-ON LAB\n" if lesson else "")
            + f"{lab.title} (~{lab.minutes} min)\n{status}\n\nGoal: {lab.goal}\n"
            f"Your lab token: {item.token}\nChoose any one route: {routes}.\n"
            "The in-app scenario is free, needs no cloud account and verifies the lab. "
            + (
                "Practice locally repeats it hands-on with free tools on your own machine (self-checked).\n"
                if lab.local
                else "Code labs run free on GitHub. Your own AWS account is optional and may cost money.\n"
            )
            + "Quizzes are sent whether or not you finish labs.\n"
            f"Details and progress: /lab {lab.id} or the Labs section of /dashboard.",
            buttons=self.route_buttons(item),
        )

    def route_buttons(self, item):
        lab = LABS[item.lab_id]
        labels = {
            "scenario": "Start in-app scenario",
            "code": "Code lab steps",
            "aws": "My AWS account steps",
            "local": "Practice locally (free)",
        }
        return [[{"text": labels[r], "callback_data": f"lab:{item.id}:{r}"}] for r in lab.routes]

    def find(self, lab_id):
        return next(
            (
                a
                for a in sorted(self.state.labs.values(), key=lambda x: x.status == "verified")
                if a.lab_id == lab_id
            ),
            None,
        )

    # Commands -------------------------------------------------------------------------------

    def command(self, cmd, arg):
        if not self.config.labs_enabled and cmd != "labs":
            self.s.say("Hands-on labs are temporarily turned off. Lessons, quizzes and plans continue.")
            return
        if cmd == "labs":
            self.list()
        elif cmd == "lab":
            self.show(arg)
        elif cmd == "submitlab":
            parts = arg.split()
            if len(parts) != 2:
                self.s.say("Use /submitlab <lab_id> <link>. See /labs for your lab IDs.")
            else:
                self.submit(parts[0].lower(), parts[1])
        elif cmd == "labcleanup":
            parts = arg.split()
            if len(parts) != 2:
                self.s.say("Use /labcleanup <lab_id> <the same link you verified>.")
            else:
                self.cleanup(parts[0].lower(), parts[1])
        elif cmd == "labcarry":
            self.carry()

    def list(self):
        if not self.config.labs_enabled:
            self.s.say("Hands-on labs are temporarily turned off. Lessons, quizzes and plans continue.")
            return
        lines = []
        for a in sorted(self.state.labs.values(), key=lambda x: (x.status == "verified", x.assigned_date)):
            lab = LABS.get(a.lab_id)
            if not lab:
                continue
            label = {"pending": "pending", "needs_fix": "needs a fix", "verified": "verified"}[a.status]
            flags = ("required" if a.required else "optional") + (", carried" if a.carried_at else "")
            lines.append(f"{lab.id}: {lab.title} — {label} ({flags})")
        assigned = {a.lab_id for a in self.state.labs.values()}
        available = [lab for lab in LABS.values() if lab.id not in assigned]
        text = "YOUR LABS\n" + ("\n".join(lines) if lines else "No labs assigned yet.")
        if available:
            text += "\n\nMore labs you can start any time (optional):\n" + "\n".join(
                f"{lab.id}: {lab.title} (~{lab.minutes} min)" for lab in available
            )
        text += (
            "\n\nUse /lab <lab_id> for steps. Labs never block quizzes or your next week: "
            "unfinished required labs carry forward."
        )
        self.s.say(text)

    def show(self, lab_id):
        from skillcoach.service import stable_id

        lab_id = lab_id.strip().lower()
        if not lab_id:
            self.list()
            return
        lab = LABS.get(lab_id)
        if not lab:
            self.s.say("Unknown lab. Use /labs to see lab IDs.")
            return
        item = self.find(lab.id)
        if item is None:
            from skillcoach.models import LabAssignment

            item = LabAssignment(
                id=stable_id(f"lab:optional:{self.s.job['id']}:{lab.id}"),
                lab_id=lab.id,
                token=new_token(),
                assigned_date=self.today(),
            )
            self.state.labs[item.id] = item
        if item.status == "verified":
            self.s.say(
                f"{lab.title}\nVerified on {item.verified_at.astimezone(self.s.now.tzinfo):%d %b %Y} "
                f"via {ROUTE_LABELS.get(item.route, 'lab')}."
                + (
                    f"\nCleanup reminder: delete the AWS resources, then /labcleanup {lab.id} <link>."
                    if item.cleanup == "reminder"
                    else ""
                )
            )
            return
        self.announce(item)

    def route_details(self, assignment_id, route):
        from skillcoach.resources import related_text

        item = self.state.labs.get(assignment_id)
        if not item or item.lab_id not in LABS or route not in LABS[item.lab_id].routes:
            self.s.say("That lab button is no longer current. Use /labs.")
            return
        lab = LABS[item.lab_id]
        if route == "scenario":
            self.start(item)
            return
        steps, cleanup, submit = lab_steps(lab, route, item.token, self.config.labs_template_repo)
        text = f"{lab.title} — {ROUTE_LABELS[route]}\n\n" + "\n".join(
            f"{i}. {step}" for i, step in enumerate(steps, 1)
        )
        if route == "local":
            text += (
                "\n\nCLEANUP\n"
                + "\n".join(f"- {step}" for step in cleanup)
                + "\n\nThis route is self-checked practice on your own machine: nothing is deployed, charged or "
                "submitted. Verify the lab with the in-app scenario."
                + "\n\nOfficial references:\n"
                + "\n".join(lab.references)
            )
            self.s.say(
                text,
                buttons=[[{"text": "Start in-app scenario", "callback_data": f"lab:{item.id}:scenario"}]],
            )
            return
        if route == "aws":
            text += (
                "\n\n"
                + COST
                + "\n\nCLEANUP (do this right after verification)\n"
                + "\n".join(f"- {step}" for step in cleanup)
            )
        else:
            text += (
                "\n\nSkillCoach checks the public repository, the protected test and workflow files, your "
                "token file and the GitHub Actions result. It is a learning check, not a proctored exam."
            )
        text += "\n\nSubmit: " + submit + "\nOr paste the link in the Labs section of /dashboard."
        text += "\n\nOfficial references:\n" + "\n".join(lab.references)
        text += related_text(lab.topics[0])
        self.s.say(text)

    # In-app scenario ------------------------------------------------------------------------

    def start(self, item):
        from skillcoach.models import LabAttempt
        from skillcoach.service import stable_id

        if item.status == "verified":
            self.s.say("This lab is already verified. Use /labs for others.")
            return
        if self.state.focus == "lab":
            self.s.say("A lab scenario is already in progress. Answer its latest step or /cancel.")
            return
        if self.state.focus:
            self.s.say("Finish or /cancel your current question before starting a lab scenario.")
            return
        failed = sum(
            a.assignment_id == item.id and a.date == self.today() and a.status == "failed"
            for a in self.state.lab_attempts.values()
        )
        if failed >= DAILY_ATTEMPTS:
            self.s.say("You have used today's three scenario attempts for this lab. Try again tomorrow.")
            return
        rng = secrets.SystemRandom()
        cutoff = self.today() - timedelta(days=14)
        self.state.lab_attempts = {
            key: value
            for key, value in self.state.lab_attempts.items()
            if value.status == "active" or value.date >= cutoff
        }
        attempt = LabAttempt(
            id=stable_id(f"labattempt:{self.s.job['id']}:{item.id}"),
            assignment_id=item.id,
            date=self.today(),
            order=[rng.sample(range(4), 4) for _ in range(4)],
        )
        self.state.lab_attempts[attempt.id] = attempt
        self.state.active_lab, self.state.focus = attempt.id, "lab"
        lab = LABS[item.lab_id]
        self.s.say(
            f"LAB SCENARIO: {lab.title}\nFour decisions. Pass with {PASS_MARK}/4 or better. "
            "Buttons are bound to each step; /cancel stops without penalty."
        )
        self.show_step(attempt)

    def show_step(self, attempt):
        item = self.state.labs[attempt.assignment_id]
        lab = LABS[item.lab_id]
        index = len(attempt.answers)
        step = lab.scenario[index]
        order = attempt.order[index]
        self.s.say(
            f"Step {index + 1}/4\n\n{step.prompt}\n\n"
            + "\n".join(f"{LETTERS[i]}) {step.options[o]}" for i, o in enumerate(order))
            + "\n\nChoose a button, or reply A, B, C or D.",
            target=self.state.target(),
            buttons=[
                [{"text": LETTERS[i], "callback_data": f"ls:{attempt.id}:{index}:{i}"} for i in range(4)]
            ],
        )

    def answer(self, attempt_id, step, choice):
        target = {"kind": "lab", "session": attempt_id, "question": str(step)}
        if target != self.state.target() or choice not in range(4):
            self.s.say(
                "That lab answer is stale or there is no active lab step. Use the newest step's buttons."
            )
            return
        attempt = self.state.lab_attempts[attempt_id]
        if attempt.date != self.today():
            attempt.status = "expired"
            self.state.active_lab, self.state.focus = None, None
            self.s.say("That lab scenario expired at midnight. Start it again with /lab. Nothing was graded.")
            return
        item = self.state.labs[attempt.assignment_id]
        lab = LABS[item.lab_id]
        scenario = lab.scenario[step]
        correct = attempt.order[step][choice] == 0
        attempt.answers.append(correct)
        self.s.answers.append((attempt.id, f"step-{step}"))
        self.s.say(
            ("Correct." if correct else "Not quite. Best answer: " + scenario.options[0])
            + "\n\n"
            + scenario.explanation
        )
        if len(attempt.answers) < 4:
            self.show_step(attempt)
            return
        score = sum(attempt.answers)
        attempt.completed_at = self.s.now
        self.state.active_lab, self.state.focus = None, None
        self.s.practice()
        if item.status == "verified":
            # Verified by another route while this attempt ran: record practice only, keep the evidence.
            attempt.status = "passed" if score >= PASS_MARK else "failed"
            self.s.say(
                f"Scenario practice result: {score}/4. {lab.title} was already verified, so its "
                "verification is unchanged."
            )
            return
        if score >= PASS_MARK:
            attempt.status = "passed"
            self.verified(item, "scenario", ["scenario-pass"])
            self.s.say(f"Lab scenario passed: {score}/4. {lab.title} is verified.")
        else:
            attempt.status = "failed"
            item.status, item.result_code = "needs_fix", "scenario_failed"
            left = DAILY_ATTEMPTS - sum(
                a.assignment_id == item.id and a.date == self.today() and a.status == "failed"
                for a in self.state.lab_attempts.values()
            )
            self.s.say(
                f"Lab scenario result: {score}/4. You need {PASS_MARK}/4. Review the explanations above"
                + (
                    f", then try again ({left} attempt{'s' if left != 1 else ''} left today)."
                    if left
                    else ". Try again tomorrow."
                ),
                buttons=[[{"text": "Try again", "callback_data": f"lab:{item.id}:scenario"}]]
                if left
                else None,
            )

    def text(self, value):
        letter = value.strip().upper().rstrip(").")
        target = self.s.payload.get("target")
        if letter not in LETTERS or not target or target.get("kind") != "lab":
            self.s.say("Reply A, B, C or D for the current lab step, or /cancel.")
            return
        self.answer(target["session"], int(target["question"]), LETTERS.index(letter))

    def interrupt(self, reason):
        attempt = self.state.lab_attempts.get(self.state.active_lab or "")
        if attempt and attempt.status == "active":
            attempt.status = "cancelled"
        if self.state.focus == "lab":
            self.state.focus = None
        self.state.active_lab = None
        if reason:
            self.s.say(reason)

    # Link evidence --------------------------------------------------------------------------

    def rate_limited(self):
        today = self.today()
        tz = self.s.now.tzinfo
        self.state.lab_checks = [
            c for c in self.state.lab_checks if c.astimezone(tz).date() >= today - timedelta(days=1)
        ]
        return sum(c.astimezone(tz).date() == today for c in self.state.lab_checks) >= DAILY_CHECKS

    def submit(self, lab_id, url, assignment_id=None):
        lab = LABS.get(lab_id)
        item = self.state.labs.get(assignment_id) if assignment_id else (self.find(lab_id) if lab else None)
        if item is not None:
            lab = LABS.get(item.lab_id)
        if not lab or item is None:
            self.s.say("Open the lab first with /lab <lab_id> to get your token. Use /labs for IDs.")
            return
        if item.status == "verified":
            self.s.say(f"{lab.title} is already verified. No new check was run.")
            return
        route = "code" if url.lower().startswith("https://github.com/") else "aws"
        if route not in lab.routes:
            self.record(item, {"code": "url_not_allowed"})
            return
        cached = self.s.repo.cached(self.s.job["id"], "lab-check")
        if cached is None:
            if self.rate_limited():
                self.s.say("You reached today's limit of 12 lab checks. Try again tomorrow.")
                return
            if route == "code":
                protected = TEMPLATE_BLOBS[lab.id]
                result = self.checker().github(lab, protected, url, item.token, self.s.budget)
            else:
                result = self.checker().aws(lab.aws, url, item.token, self.s.budget)
            result = {
                "code": str(result.get("code", "unreachable")),
                "checks": list(result.get("checks", []))[:12],
                "at": self.s.now.isoformat(),
            }
            self.s.repo.cache(self.s.job["id"], "lab-check", result, self.s.token)
        else:
            result = cached
        # State rolls back when a job fails, so the committed attempt records the cached check time.
        self.state.lab_checks.append(datetime.fromisoformat(result.get("at") or self.s.now.isoformat()))
        if result["code"] != "verified":
            self.record(item, result)
            return
        self.verified(item, route, result["checks"])
        self.s.practice()
        if route == "aws":
            item.cleanup = "reminder"
            item.url_digest = url_digest(item.token, canonical_link(url))
            steps = "\n".join("- " + step for step in lab.aws.cleanup)
            self.s.say(
                f"Lab verified from your AWS account: {lab.title}.\n\nDelete the resources now to avoid "
                f"charges:\n{steps}\nSkillCoach never needs your credentials."
            )
        else:
            self.s.say(f"Code lab verified: {lab.title}. The protected tests passed on GitHub Actions.")

    def record(self, item, result):
        item.status, item.result_code = "needs_fix", result["code"]
        self.s.say(
            f"Lab not verified yet: {message(result['code'])}\nFix it and submit again, or use the free in-app scenario from /lab {item.lab_id}."
        )

    def verified(self, item, route, checks):
        item.status, item.route, item.result_code = "verified", route, "verified"
        item.checks, item.verified_at = checks, self.s.now

    def cleanup(self, lab_id, url):
        item = self.find(lab_id)
        lab = LABS.get(lab_id)
        if not item or not lab or not lab.aws or item.route != "aws" or item.status != "verified":
            self.s.say("Cleanup confirmation applies only to labs verified from your own AWS account.")
            return
        if item.cleanup == "confirmed":
            self.s.say("Cleanup is already confirmed for this lab.")
            return
        digest = url_digest(item.token, canonical_link(url))
        if not item.url_digest or not secrets.compare_digest(digest, item.url_digest):
            self.s.say(message("cleanup_mismatch"))
            return
        cached = self.s.repo.cached(self.s.job["id"], "lab-cleanup")
        if cached is None:
            if self.rate_limited():
                self.s.say("You reached today's limit of 12 lab checks. Try again tomorrow.")
                return
            result = self.checker().cleanup(lab.aws, url, item.token, self.s.budget)
            cached = {"code": str(result.get("code", "unreachable")), "at": self.s.now.isoformat()}
            self.s.repo.cache(self.s.job["id"], "lab-cleanup", cached, self.s.token)
        self.state.lab_checks.append(datetime.fromisoformat(cached.get("at") or self.s.now.isoformat()))
        if cached["code"] == "cleaned":
            item.cleanup = "confirmed"
            self.s.say(
                "Cleanup confirmed: the link no longer serves your token. Also check AWS Billing and Cost "
                "Explorer for anything else you created."
            )
        else:
            self.s.say(message(cached["code"]))

    # Carry-forward -------------------------------------------------------------------------

    def carry(self):
        pending = pending_required(self.state) if self.config.labs_enabled else []
        self.s.say(
            "Required labs now carry forward automatically, so your plan never waits for them."
            + (
                "\nStill open: " + ", ".join(f"{LABS[a.lab_id].title} (/lab {a.lab_id})" for a in pending)
                if pending
                else "\nNo required labs are open."
            )
        )

    def resume_planning(self):
        """Plan the next week when a finished week has no proposal yet (e.g. after /unpause)."""
        from skillcoach.journey import Learning

        j = self.state.journey
        if (
            not j
            or j.stage != "active"
            or j.proposed_id
            or self.state.paused
            or not week_finished(self.state)
            or self.s.control
        ):
            return
        j.lab_gate_since = None
        j.stage = "planning"
        j.revision_request = "Propose the next study week from recent practice and diagnostic evidence."
        Learning(self.s).followup("propose")
        self.s.say(
            "Preparing next week's plan. It starts automatically at your next 09:00 IST lesson slot "
            "unless you change it."
        )

    def quiz_reminder(self, day):
        pending = pending_required(self.state) if self.config.labs_enabled else []
        if day.weekday() == 4 and pending:
            self.s.say(
                "Reminder: "
                + ", ".join(LABS[a.lab_id].title for a in pending)
                + " is still open. It carries forward if unfinished, so nothing waits on it. The quiz below "
                "does not depend on it. /labs"
            )

    # Durable dashboard job ------------------------------------------------------------------

    def job(self):
        payload = self.s.payload
        if payload.get("action") != "submit":
            raise ValueError("Unsupported lab job")
        if not self.config.labs_enabled:
            self.s.say("Hands-on labs are temporarily turned off. Lessons, quizzes and plans continue.")
            return
        item = self.state.labs.get(payload.get("assignment_id", ""))
        if item is None:
            self.s.say("That lab is no longer available. Refresh your dashboard.")
            return
        self.submit(item.lab_id, payload.get("url", ""), item.id)
