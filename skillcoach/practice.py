"""Practice: short, answer-first lessons on the web app's learning path (/web/practice).

Lessons are content only. The browser checks answers, schedules spaced reviews and keeps progress on
the learner's device; nothing here calls AI, records answers or writes learner state. Hand-written
lessons live in practice_data/*.json. Every other library topic gets two lessons derived, without AI,
from its bundled course package: its concepts, key terms, end-to-end flow and interview question.

Every step carries a stable item ID (topic|lesson|step) so spaced reviews can fetch it again later.
Text fields use the lesson Markdown subset and are sent as typed spans/blocks, never as HTML."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from skillcoach.catalog import MODULES, TOPICS
from skillcoach.course_library import NOTICE, get_package
from skillcoach.formatting import md_blocks, spans
from skillcoach.models_base import Model

DATA = Path(__file__).with_name("practice_data")
FEATURED = "kubernetes/kubernetes-pods-deployments-and-replica-sets"
DERIVED_NOTICE = "Built automatically from this topic's course notes (" + NOTICE.rstrip(".") + ")."
ITEM = re.compile(r"^([a-z0-9][a-z0-9/-]{0,119})\|([a-z0-9][a-z0-9-]{0,40})\|([a-z0-9][a-z0-9-]{0,40})$")
REVIEW_LIMIT = 20

Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")]
Label = Annotated[str, Field(min_length=1, max_length=80)]
Line = Annotated[str, Field(min_length=1, max_length=600)]
Para = Annotated[str, Field(min_length=1, max_length=2000)]
Token = Annotated[str, Field(min_length=1, max_length=40)]


# Visuals: small diagrams drawn by the browser from data (dual coding), each with a text caption that
# is also its accessible description.


class Box(Model):
    label: Label
    note: Annotated[str, Field(max_length=60)] = ""
    tone: Literal["plain", "accent", "success", "muted", "warn"] = "plain"
    children: list["Box"] = Field(default_factory=list, max_length=6)


class TreeVisual(Model):
    kind: Literal["tree"]
    caption: Line
    boxes: list[Box] = Field(min_length=1, max_length=3)


class SlotRow(Model):
    label: Label
    slots: list[Literal["old", "new", "starting", "stopping"]] = Field(min_length=1, max_length=12)


class SlotsVisual(Model):
    kind: Literal["slots"]
    caption: Line
    rows: list[SlotRow] = Field(min_length=1, max_length=4)


Visual = Annotated[TreeVisual | SlotsVisual, Field(discriminator="kind")]


# Steps ---------------------------------------------------------------------------------------------


class Teach(Model):
    """One idea, briefly, before it is practised."""

    type: Literal["teach"]
    id: Slug
    title: Label
    body: Para
    example: Annotated[str, Field(max_length=2000)] = ""
    visual: Visual | None = None


class Option(Model):
    text: Line
    correct: bool = False
    why: Line


class Choice(Model):
    """Single answer. Every option explains itself, so a wrong pick names the misconception.
    A pretest is asked before teaching (a guess primes learning) and never counts as a mistake."""

    type: Literal["choice"]
    id: Slug
    prompt: Para
    context: Annotated[str, Field(max_length=2000)] = ""
    options: list[Option] = Field(min_length=2, max_length=4)
    explain: Para
    pretest: bool = False

    @model_validator(mode="after")
    def one_answer(self):
        if sum(option.correct for option in self.options) != 1:
            raise ValueError("A choice needs exactly one correct option")
        if len({option.text for option in self.options}) != len(self.options):
            raise ValueError("Choice options must differ")
        return self


class TrueFalse(Model):
    type: Literal["truefalse"]
    id: Slug
    statement: Para
    answer: bool
    explain: Para


class Match(Model):
    type: Literal["match"]
    id: Slug
    prompt: Line
    pairs: list[tuple[Line, Line]] = Field(min_length=3, max_length=5)
    explain: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def distinct(self):
        lefts, rights = [p[0] for p in self.pairs], [p[1] for p in self.pairs]
        if len(set(lefts)) != len(lefts) or len(set(rights)) != len(rights):
            raise ValueError("Match pairs must be distinct on both sides")
        return self


class Order(Model):
    type: Literal["order"]
    id: Slug
    prompt: Line
    steps: list[Line] = Field(min_length=3, max_length=6)
    explain: Para

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.steps)) != len(self.steps):
            raise ValueError("Order steps must differ")
        return self


class Fill(Model):
    """Fill the blanks (___) from a word bank. Every token is unique, so exactly one filling is right."""

    type: Literal["fill"]
    id: Slug
    prompt: Line
    template: Line
    code: bool = False
    answer: list[Token] = Field(min_length=1, max_length=3)
    distractors: list[Token] = Field(min_length=1, max_length=5)
    explain: Para

    @model_validator(mode="after")
    def blanks(self):
        if self.template.count("___") != len(self.answer):
            raise ValueError("Each blank (___) needs exactly one answer token")
        tokens = [*self.answer, *self.distractors]
        if len(set(tokens)) != len(tokens):
            raise ValueError("Word-bank tokens must be unique")
        return self


class Spot(Model):
    """Tap the faulty line of a short manifest or command listing."""

    type: Literal["spot"]
    id: Slug
    prompt: Line
    lang: Annotated[str, Field(pattern=r"^[a-z]{1,12}$")] = "yaml"
    lines: list[Annotated[str, Field(max_length=120)]] = Field(min_length=3, max_length=24)
    answers: list[Annotated[int, Field(ge=0)]] = Field(min_length=1, max_length=3)
    explain: Para

    @model_validator(mode="after")
    def in_range(self):
        if any(index >= len(self.lines) or not self.lines[index].strip() for index in self.answers):
            raise ValueError("Spot answers must point at non-empty lines")
        return self


class Explain(Model):
    """Self-explanation: the learner writes an answer on their device, then checks it against key
    points. The text never leaves the page; only how many points they covered is kept."""

    type: Literal["explain"]
    id: Slug
    prompt: Para
    points: list[Line] = Field(min_length=2, max_length=5)
    model: Annotated[str, Field(max_length=2000)] = ""


Step = Annotated[
    Teach | Choice | TrueFalse | Match | Order | Fill | Spot | Explain, Field(discriminator="type")
]
CHECKED = ("choice", "truefalse", "match", "order", "fill", "spot", "explain")


class Lesson(Model):
    id: Slug
    title: Label
    goal: Line
    # The path node's glyph: a picture of what the lesson is about.
    icon: Literal["pod", "replicaset", "rollout", "rollback", "idea", "target"] = "idea"
    takeaways: list[Line] = Field(min_length=2, max_length=4)
    steps: list[Step] = Field(min_length=4, max_length=20)

    @model_validator(mode="after")
    def coherent(self):
        ids = [step.id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Step IDs must be unique within a lesson")
        if sum(step.type in CHECKED and not getattr(step, "pretest", False) for step in self.steps) < 3:
            raise ValueError("A lesson needs at least three practice questions")
        return self


class Unit(Model):
    """A hand-written practice unit for one library topic."""

    topic: Annotated[str, Field(min_length=3, max_length=120)]
    version: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    review: Line
    references: list[Annotated[str, Field(pattern=r"^https://[^\s]{4,200}$")]] = Field(
        min_length=1, max_length=6
    )
    lessons: list[Lesson] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def known(self):
        if self.topic not in TOPICS:
            raise ValueError("A practice unit must belong to a library topic")
        ids = [lesson.id for lesson in self.lessons]
        if len(set(ids)) != len(ids):
            raise ValueError("Lesson IDs must be unique within a unit")
        return self


@lru_cache(maxsize=1)
def units() -> dict[str, Unit]:
    found = {}
    for path in sorted(DATA.glob("*.json")):
        unit = Unit.model_validate_json(path.read_text(encoding="utf-8"))
        if unit.topic in found:
            raise ValueError("Two practice units claim the same topic")
        found[unit.topic] = unit
    return found


# Lessons derived from a course package ---------------------------------------------------------------

DERIVED = (
    ("core", "Core ideas", "idea"),
    ("apply", "Recall and apply", "target"),
)
TERM = re.compile(r"^(.{1,60}?)\s+[—–-]\s+(.+)$|^([^:`]{1,60}):\s+(.+)$", re.S)


def _gist(text: str, limit: int = 320) -> str:
    """The first sentence of a concept, cut only at a sentence end outside code spans and bold."""
    ticks = bold = 0
    for index, char in enumerate(text):
        if char == "`":
            ticks += 1
        elif text.startswith("**", index):
            bold += 1
        elif (
            char in ".!?"
            and ticks % 2 == 0
            and bold % 2 == 0
            and text[index + 1 : index + 2] == " "
            and re.match(r"[A-Z`*(]", text[index + 2 : index + 3] or "x")
        ):
            sentence = text[: index + 1]
            return sentence if len(sentence) <= limit else text
    return text


def _term(text: str):
    match = TERM.match(text.strip())
    if not match:
        return None
    term, definition = (
        (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    )
    term, definition = term.strip(), definition.strip()
    return (term, definition) if term and definition and len(term) <= 60 else None


def _identify(concepts, index: int, step_id: str) -> Choice:
    target = concepts[index]
    return Choice(
        type="choice",
        id=step_id,
        prompt="Which idea does this describe?",
        context=_gist(target.body),
        options=[
            Option(
                text=concept.name,
                correct=position == index,
                why=(
                    "Yes, that is this idea."
                    if position == index
                    else f"**{concept.name}** is a different idea: {_gist(concept.body, 240)}"
                ),
            )
            for position, concept in enumerate(concepts)
        ],
        explain=f"This describes **{target.name}**.\n\n{target.body}",
    )


@lru_cache(maxsize=256)
def _derived(topic: str) -> tuple[Lesson, ...]:
    package = get_package(topic)
    lesson = package.lesson
    concepts = lesson.concepts[:4]
    title = titles()[topic]
    flow = list(dict.fromkeys(lesson.e2e))[:6]
    core = []
    if len(flow) >= 3:
        # A guess before any teaching (pretesting primes what follows): which step of the flow comes
        # first? Never counted as a mistake, never a review card.
        picks = [0, len(flow) // 2, len(flow) - 1]
        core.append(
            Choice(
                type="choice",
                id="guess-first",
                pretest=True,
                prompt="Take a guess before we start. When this works end to end, which of these happens first?",
                options=[
                    Option(
                        text=flow[index],
                        correct=index == 0,
                        why="Yes, the flow starts here."
                        if index == 0
                        else f"This is step {index + 1} of the flow, so it comes later.",
                    )
                    for index in picks
                ],
                explain="The flow starts with: "
                + flow[0]
                + "\n\nYou'll put the whole flow in order in the next lesson.",
            )
        )
    core.append(Teach(type="teach", id="why", title="Why it matters", body=lesson.why))
    for number in (0, 1):
        concept = concepts[number]
        core.append(Teach(type="teach", id=f"idea-{number + 1}", title=concept.name, body=concept.body))
    core += [_identify(concepts, 0, "check-1"), _identify(concepts, 1, "check-2")]
    for number in range(2, len(concepts)):
        concept = concepts[number]
        core.append(Teach(type="teach", id=f"idea-{number + 1}", title=concept.name, body=concept.body))
    # Checked in reverse order, so the newest idea is not always asked first.
    for number in reversed(range(2, len(concepts))):
        core.append(_identify(concepts, number, f"check-{number + 1}"))
    pairs = [pair for pair in (_term(text) for text in lesson.key_terms) if pair]
    unique = list({pair[0]: pair for pair in pairs}.values())
    if len(unique) >= 3 and len({pair[1] for pair in unique[:5]}) == len(unique[:5]):
        core.append(
            Match(
                type="match",
                id="terms",
                prompt="Match each term to its meaning.",
                pairs=unique[:5],
            )
        )
    apply = [_identify(concepts, 1, "recall-2")]
    if len(flow) >= 3:
        apply.append(
            Order(
                type="order",
                id="flow",
                prompt="Put the end-to-end flow in order."
                if len(flow) == len(lesson.e2e)
                else f"Put the first {len(flow)} steps of the end-to-end flow in order.",
                steps=flow,
                explain="This is the order in which the work happens:\n\n"
                + "\n".join(f"{i}. {step}" for i, step in enumerate(flow, 1)),
            )
        )
    apply.append(_identify(concepts, len(concepts) - 1, f"recall-{len(concepts)}"))
    if lesson.interview_question and len(lesson.interview_points) >= 2:
        apply.append(
            Explain(
                type="explain",
                id="interview",
                prompt="**Interview question:** " + lesson.interview_question,
                points=lesson.interview_points[:5],
            )
        )
    apply.append(Teach(type="teach", id="recap", title="Recap", body=package.core))
    takeaways = [concept.name for concept in concepts]
    return (
        Lesson(
            id="core",
            title=DERIVED[0][1],
            goal=f"Learn the core ideas of {title}, one at a time.",
            icon="idea",
            takeaways=takeaways,
            steps=core,
        ),
        Lesson(
            id="apply",
            title=DERIVED[1][1],
            goal="Recall the ideas, order the end-to-end flow and answer the interview question.",
            icon="target",
            takeaways=takeaways,
            steps=apply,
        ),
    )


def _lessons(topic: str) -> tuple[Lesson, ...]:
    unit = units().get(topic)
    return tuple(unit.lessons) if unit else _derived(topic)


@lru_cache(maxsize=1)
def titles() -> dict[str, str]:
    """Display titles: each course package's own lesson title (properly cased, e.g. "Kubernetes Pods,
    ReplicaSets and Deployments") rather than the catalog's slug-derived title."""
    return {topic: get_package(topic).lesson.title for topic in TOPICS}


def minutes(lesson: Lesson) -> int:
    return max(3, round(len(lesson.steps) * 0.45))


# Views for the browser --------------------------------------------------------------------------------


def _blocks(text: str) -> list[dict]:
    return md_blocks(text) if text else []


def _visual(visual) -> dict | None:
    return visual.model_dump(mode="json") if visual else None


def step_view(topic: str, lesson_id: str, step) -> dict:
    view = {"id": step.id, "type": step.type, "item": f"{topic}|{lesson_id}|{step.id}"}
    if isinstance(step, Teach):
        view.update(
            title=step.title,
            body=_blocks(step.body),
            example=_blocks(step.example),
            visual=_visual(step.visual),
        )
    elif isinstance(step, Choice):
        view.update(
            prompt=_blocks(step.prompt),
            context=_blocks(step.context),
            options=[
                {"text": spans(option.text), "correct": option.correct, "why": spans(option.why)}
                for option in step.options
            ],
            explain=_blocks(step.explain),
            pretest=step.pretest,
        )
    elif isinstance(step, TrueFalse):
        view.update(statement=_blocks(step.statement), answer=step.answer, explain=_blocks(step.explain))
    elif isinstance(step, Match):
        view.update(
            prompt=spans(step.prompt),
            pairs=[[spans(left), spans(right)] for left, right in step.pairs],
            explain=_blocks(step.explain),
        )
    elif isinstance(step, Order):
        view.update(
            prompt=spans(step.prompt),
            steps=[spans(text) for text in step.steps],
            explain=_blocks(step.explain),
        )
    elif isinstance(step, Fill):
        view.update(
            prompt=spans(step.prompt),
            parts=step.template.split("___"),
            code=step.code,
            answer=step.answer,
            tokens=[*step.answer, *step.distractors],
            explain=_blocks(step.explain),
        )
    elif isinstance(step, Spot):
        view.update(
            prompt=spans(step.prompt),
            lang=step.lang,
            lines=step.lines,
            answers=step.answers,
            explain=_blocks(step.explain),
        )
    elif isinstance(step, Explain):
        view.update(
            prompt=_blocks(step.prompt),
            points=[spans(point) for point in step.points],
            model=_blocks(step.model),
        )
    return view


def catalog() -> dict:
    crafted, names = units(), titles()
    modules = []
    for module in MODULES:
        topics = []
        for ident, (owner, _) in TOPICS.items():
            if owner.id != module.id:
                continue
            unit = crafted.get(ident)
            lessons = (
                [
                    {"id": lesson.id, "title": lesson.title, "minutes": minutes(lesson), "icon": lesson.icon}
                    for lesson in unit.lessons
                ]
                if unit
                else [
                    {"id": ident_, "title": name, "minutes": 5, "icon": icon}
                    for ident_, name, icon in DERIVED
                ]
            )
            topics.append({"id": ident, "title": names[ident], "crafted": bool(unit), "lessons": lessons})
        modules.append({"id": module.id, "title": module.title, "topics": topics})
    return {"featured": FEATURED, "modules": modules}


def lesson(topic: str, lesson_id: str) -> dict | None:
    if topic not in TOPICS:
        return None
    module = TOPICS[topic][0]
    lessons = _lessons(topic)
    chosen = next((item for item in lessons if item.id == lesson_id), None)
    if chosen is None:
        return None
    unit = units().get(topic)
    return {
        "topic": {"id": topic, "title": titles()[topic], "module": module.title},
        "crafted": bool(unit),
        "provenance": unit.review if unit else DERIVED_NOTICE,
        "references": unit.references if unit else get_package(topic).lesson.references,
        "lessons": [{"id": item.id, "title": item.title} for item in lessons],
        "lesson": {
            "id": chosen.id,
            "title": chosen.title,
            "goal": chosen.goal,
            "minutes": minutes(chosen),
            "takeaways": [spans(text) for text in chosen.takeaways],
            "steps": [step_view(topic, chosen.id, step) for step in chosen.steps],
        },
    }


def review(items) -> list[dict]:
    """The practice questions behind spaced-review item IDs, in the order asked. Unknown or retired IDs
    and teaching cards are skipped, so changed content never breaks a learner's review queue."""
    steps = []
    for item in list(dict.fromkeys(items))[:REVIEW_LIMIT]:
        match = ITEM.fullmatch(item) if isinstance(item, str) else None
        if not match or match.group(1) not in TOPICS:
            continue
        topic, lesson_id, step_id = match.groups()
        chosen = next((candidate for candidate in _lessons(topic) if candidate.id == lesson_id), None)
        step = next((s for s in chosen.steps if s.id == step_id), None) if chosen else None
        if step is None or step.type not in CHECKED or getattr(step, "pretest", False):
            continue
        view = step_view(topic, lesson_id, step)
        view["topic"] = titles()[topic]
        steps.append(view)
    return steps


def validate_all() -> dict:
    """Build every lesson once (used by tests): hand-written units and all derived topics."""
    counts = {"crafted": 0, "derived": 0, "steps": 0}
    for topic in TOPICS:
        for item in _lessons(topic):
            counts["steps"] += len(item.steps)
        counts["crafted" if topic in units() else "derived"] += 1
    return counts
