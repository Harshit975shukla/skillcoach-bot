"""Spaced retrieval: quiz questions come back after 1, 3, 7, 14 and 30 days (Leitner boxes).

Cards reuse questions already validated for a quiz, so reviews cost no AI calls. Review and
mistake-practice answers never change quiz scores.
"""

from datetime import timedelta

from pydantic import Field

from skillcoach.models import Assessment, Question, ReviewCard
from skillcoach.models_base import Model
from skillcoach.timeutil import study_day, week_key

# Days until the next review for boxes 0-4; box 5 means the card is retired (remembered after a month).
INTERVALS = (1, 3, 7, 14, 30)
SESSION_SIZE = 5
QUIZ_KINDS = ("daily", "weekly")


class Practice(Model):
    questions: list[Question] = Field(min_length=1, max_length=5)


def card_id(session_id: str, index: int) -> str:
    from skillcoach.service import stable_id

    return stable_id(f"card:{session_id}:{index}")


def question_for(state, card):
    session = state.assessments.get(card.session)
    return session.questions[card.index] if session and card.index < len(session.questions) else None


def schedule_answer(state, session, index, correct, when):
    """A missed quiz question returns the next study day; a correct daily answer is checked after a week.

    Due dates count from when the question was answered, so older answers keep their real spacing.
    """
    if session.kind not in QUIZ_KINDS:
        return
    ident = card_id(session.id, index)
    if ident in state.review or (correct and session.kind != "daily"):
        return
    box = 2 if correct else 0
    state.review[ident] = ReviewCard(
        id=ident,
        session=session.id,
        index=index,
        box=box,
        due=study_day(when) + timedelta(days=INTERVALS[box]),
    )


def backfill(state):
    """One-time: bring quiz answers given before spaced review existed into the deck."""
    for session in list(state.assessments.values()):
        for index, answer in enumerate(session.answers):
            if index < len(session.questions):
                schedule_answer(state, session, index, answer.correct, answer.created_at)


def record_review(state, ident, correct, now):
    card = state.review.get(ident)
    if card is None:
        return
    card.reviews += 1
    card.last_result = correct
    if correct:
        card.box = min(card.box + 1, 5)
    else:
        card.box, card.lapses = 0, card.lapses + 1
    if card.box < 5:
        card.due = study_day(now) + timedelta(days=INTERVALS[card.box])


def due_cards(state, now):
    today = study_day(now)
    cards = [c for c in state.review.values() if c.box < 5 and c.due <= today and question_for(state, c)]
    return sorted(cards, key=lambda c: (c.due, c.box, c.id))


def review_summary(state, now):
    cards = list(state.review.values())
    return {
        "due": len(due_cards(state, now)),
        "scheduled": sum(c.box < 5 for c in cards),
        "remembered_for_a_month": sum(c.box == 5 for c in cards),
    }


def build_session(state, ident, now):
    from skillcoach.service import stable_id

    cards = due_cards(state, now)[:SESSION_SIZE]
    if not cards:
        return None
    day = now.date()
    return Assessment(
        id=ident,
        kind="review",
        date=day,
        week=week_key(day),
        questions=[question_for(state, c) for c in cards],
        question_ids=[stable_id(f"{ident}:{i}") for i in range(len(cards))],
        cards=[c.id for c in cards],
    )
