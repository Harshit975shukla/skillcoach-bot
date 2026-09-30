"""Evidence-based roadmap states per catalog topic. They describe practice evidence, not certification."""

from collections import defaultdict

from skillcoach.review import QUIZ_KINDS, due_cards
from skillcoach.timeutil import study_day

LABELS = {"learning": "Learning", "needs_review": "Needs review", "solid": "Solid"}


def lesson_topic(record):
    from skillcoach.catalog import TOPICS, find_topic

    topic_id = record.get("topic_id")
    if topic_id not in TOPICS:
        found = find_topic(record.get("topic", ""))
        topic_id = found[0] if found else None
    return topic_id if topic_id in TOPICS else None


def topic_evidence(state):
    """Per topic: delivered lessons, quiz/review/practice results in time order, and card boxes."""
    by_date = defaultdict(set)
    delivered = set()
    for record in state.lessons.values():
        topic_id = lesson_topic(record)
        if topic_id and record.get("date"):
            by_date[record["date"]].add(topic_id)
            if record.get("delivered_at"):
                delivered.add(topic_id)

    def topics_for(session):
        if session.kind == "practice" and session.source in state.assessments:
            session = state.assessments[session.source]
        return by_date.get(session.date.isoformat(), set()) if session.kind == "daily" else set()

    results = defaultdict(list)
    for session in state.assessments.values():
        if session.kind == "weekly":
            continue
        for index, answer in enumerate(session.answers):
            if session.kind == "review":
                card = state.review.get(session.cards[index]) if index < len(session.cards) else None
                source = state.assessments.get(card.session) if card else None
                topics = topics_for(source) if source else set()
            else:
                topics = topics_for(session)
            for topic_id in topics:
                results[topic_id].append((answer.created_at, answer.correct))
    boxes = defaultdict(list)
    for card in state.review.values():
        source = state.assessments.get(card.session)
        if source and source.kind in QUIZ_KINDS:
            for topic_id in topics_for(source):
                boxes[topic_id].append(card)
    return delivered, results, boxes


def mastery_view(state, now):
    from skillcoach.catalog import TOPICS

    delivered, results, boxes = topic_evidence(state)
    due = {c.id for c in due_cards(state, now)}
    states = {}
    for topic_id in delivered:
        recent = [correct for _, correct in sorted(results.get(topic_id, []))[-10:]]
        cards = boxes.get(topic_id, [])
        accuracy = sum(recent) / len(recent) if recent else None
        if any(c.id in due for c in cards) or (accuracy is not None and len(recent) >= 2 and accuracy < 0.6):
            states[topic_id] = "needs_review"
        elif (
            accuracy is not None
            and len(recent) >= 4
            and accuracy >= 0.8
            and any(c.box >= 3 for c in cards)
            and not any(c.box == 0 for c in cards)
        ):
            # Solid needs a question remembered a week later, not just a good first quiz.
            states[topic_id] = "solid"
        else:
            states[topic_id] = "learning"
    order = list(TOPICS)  # Module order, then syllabus order within each module.
    review_first = next((key for key in order if states.get(key) == "needs_review"), None)
    latest = max(
        (record for record in state.lessons.values() if lesson_topic(record) and record.get("delivered_at")),
        key=lambda r: r.get("date", ""),
        default=None,
    )
    upcoming = None
    if latest:
        start = order.index(lesson_topic(latest))
        upcoming = next((key for key in order[start + 1 :] + order[:start] if key not in states), None)
    recommended = review_first or upcoming or next((key for key in order if key not in states), None)
    return {
        "states": {key: {"state": value, "label": LABELS[value]} for key, value in states.items()},
        "summary": {
            "total": len(TOPICS),
            "started": len(states),
            "solid": sum(v == "solid" for v in states.values()),
            "needs_review": sum(v == "needs_review" for v in states.values()),
        },
        "next": {
            "id": recommended,
            "title": TOPICS[recommended][1],
            "reason": "Review what slipped" if recommended == review_first else "Next on your roadmap",
        }
        if recommended
        else None,
        "as_of": study_day(now).isoformat(),
    }
