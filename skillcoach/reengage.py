"""Gentle re-engagement after missed study days: no guilt, one small next step and an easy pause."""

from datetime import date, datetime, time, timedelta

from skillcoach.adoption import since_resume, weekday_gap
from skillcoach.timeutil import IST, study_day

NUDGE_AFTER, PACE_AFTER = 2, 5
NUDGE_EVERY, PACE_EVERY = timedelta(days=2), timedelta(days=14)
ENCOURAGEMENTS = {
    "progress": "🌟 Your mentor noticed your progress. Small, steady steps add up, so keep going!",
    "checkin": "👋 Your mentor is checking in. No pressure: a 2-minute warm-up is ready whenever you are.",
    "goal": "🎯 You're close to your weekly study goal. One short session gets you there!",
    "welcome": "🙌 Welcome back! Your next step is ready, so pick up right where you left off.",
}


def idle_days(state, now):
    """Scheduled (Mon-Sat) days missed since the last study day or the end of a pause; 0 before any
    lesson arrives."""
    today = study_day(now)
    activity = sorted(set(state.activity))
    if activity:
        return weekday_gap(since_resume(state, activity[-1]), today)
    delivered = sorted(r["date"] for r in state.lessons.values() if r.get("delivered_at") and r.get("date"))
    if not delivered:
        return 0
    return weekday_gap(since_resume(state, date.fromisoformat(delivered[0]) - timedelta(days=1)), today)


def next_step_buttons(service):
    from skillcoach.progress import today_view

    action = today_view(service.state, service.now)["next"]
    rows = []
    if action.get("callback") and action["kind"] in ("quiz", "catch_up", "review", "resume"):
        rows.append([{"text": "▶️ " + action["text"][:60], "callback_data": action["callback"]}])
    rows.append([{"text": "📅 Today", "callback_data": "home:today"}])
    return rows


class Reengage:
    def __init__(self, service):
        self.s = service

    def evaluate(self):
        state, now = self.s.state, self.s.now
        if state.paused:
            return
        idle = idle_days(state, now)
        if idle >= PACE_AFTER and (state.pace_offer_at is None or now - state.pace_offer_at >= PACE_EVERY):
            state.pace_offer_at = state.nudged_at = now
            self.s.say(
                "🌱 Life gets busy, and that's okay. Want to make the next stretch easier? Your progress is saved "
                "either way.",
                buttons=[
                    [{"text": "🌱 Lighter plan: 15-minute sessions", "callback_data": "nudge:light"}],
                    [{"text": "⏸ Pause for a week", "callback_data": "nudge:pause7"}],
                    [{"text": "💪 Keep my plan", "callback_data": "nudge:keep"}],
                ],
            )
        elif idle >= NUDGE_AFTER and (state.nudged_at is None or now - state.nudged_at >= NUDGE_EVERY):
            state.nudged_at = now
            self.s.say(
                "👋 Haven't seen you for a couple of days. No problem! A 2-minute warm-up keeps what you "
                "learned fresh.",
                buttons=next_step_buttons(self.s),
            )

    def respond(self, choice):
        state = self.s.state
        if choice == "light":
            if state.journey:
                state.journey.minutes = 15
            else:
                state.preference = "Lighter pace: about 15 minutes per session."
            self.s.say(
                "🌱 Done. Your next weekly plan will use 15-minute sessions. This week's lessons stay as they "
                "are, so do only what fits."
            )
        elif choice == "pause7":
            if state.paused:
                self.s.say("Scheduled coaching is already paused. /unpause any time.")
                return
            # Resume at the start of the study day a week from now, so that morning's lesson arrives.
            resume = datetime.combine(study_day(self.s.now) + timedelta(days=7), time(4), IST)
            state.paused, state.pause_until = True, resume
            self.s.control = "pause"
            self.s.say(
                f"⏸ Paused until {resume:%a %d %b}. Scheduled coaching resumes automatically that morning, "
                "or send /unpause any time. Your progress is saved."
            )
        elif choice == "keep":
            self.s.say(
                "💪 Great, your plan stays. Here's the quickest next step:", buttons=next_step_buttons(self.s)
            )
        else:
            self.s.say("Unsupported or expired button.")

    def encourage(self, key):
        text = ENCOURAGEMENTS.get(key)
        # Only prepared messages, and never to a learner who paused after the owner confirmed it.
        if text is None or self.s.state.paused:
            return
        self.s.say(text, buttons=next_step_buttons(self.s))

    def resume_if_due(self):
        """End a week-long pause at its first scheduled run after the chosen date."""
        state = self.s.state
        if state.paused and state.pause_until and self.s.now >= state.pause_until:
            state.paused, state.pause_until, state.resumed_at = False, None, self.s.now
            self.s.say(
                "🙌 Welcome back! Your pause has ended, so scheduled coaching is on again. /pause any time."
            )
            from skillcoach.lab_flow import LabFlow

            LabFlow(self.s).resume_planning()
