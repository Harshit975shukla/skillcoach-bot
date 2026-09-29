"""Versioned, bundled lessons. Reading a course never calls AI or GitHub."""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field

from skillcoach.catalog import MODULES, TOPICS, find_topic
from skillcoach.clients import ExternalError
from skillcoach.content_checks import validate_lesson
from skillcoach.models import Lesson, Model, Text
from skillcoach.storyboard import Storyboard

VERSION = "2026-09-29"
VERSIONS = frozenset({"2026-09-29"})
ROOT = Path(__file__).with_name("course_data")
NOTICE = "Prewritten AI-assisted lessons, not independently expert-reviewed. Check current vendor details."
log = logging.getLogger(__name__)


class Package(Model):
    lesson: Lesson
    storyboard: Storyboard
    core: Text = Field(max_length=1700)
    objectives: list[Text] = Field(min_length=2, max_length=4)
    prerequisites: list[Text] = Field(min_length=1, max_length=4)


class ModuleContent(Model):
    version: Text
    lessons: dict[str, Package]


@lru_cache(maxsize=64)
def _module(version, module_id):
    if version not in VERSIONS or module_id not in {m.id for m in MODULES}:
        raise ValueError("Unknown course version or module")
    document = ModuleContent.model_validate_json(
        (ROOT / version / f"{module_id}.json").read_text(encoding="utf-8")
    )
    if document.version != version:
        raise ValueError("Course version mismatch")
    expected = {ident for ident, (module, _) in TOPICS.items() if module.id == module_id}
    if set(document.lessons) != expected:
        raise ValueError("Course module coverage mismatch")
    for package in document.lessons.values():
        if len(package.lesson.tasks) != 4:
            raise ValueError("Stored courses require four progressive exercises")
        validate_lesson(package.lesson)
    return document.lessons


def get_package(topic, version=VERSION):
    entry = find_topic(topic)
    if entry is None:
        return None
    ident, module, _ = entry
    try:
        return _module(version, module.id)[ident].model_copy(deep=True)
    except (OSError, ValueError):
        log.error("course_content_unavailable module=%s", module.id)
        raise ExternalError("course_content_unavailable", retryable=False) from None


def index():
    # Do not advertise a complete library when a deployment omitted or damaged its data files.
    for module in MODULES:
        get_package(next(k for k, (owner, _) in TOPICS.items() if owner.id == module.id))
    return {
        "version": VERSION,
        "notice": NOTICE,
        "total": len(TOPICS),
        "modules": [
            {
                "id": module.id,
                "title": module.title,
                "topics": [
                    {"id": ident, "title": title}
                    for ident, (owner, title) in TOPICS.items()
                    if owner.id == module.id
                ],
            }
            for module in MODULES
        ],
    }


def page(topic, version=VERSION):
    from skillcoach.formatting import md_blocks
    from skillcoach.lesson_delivery import display_name, reference_sections, review_note
    from skillcoach.resources import related_view

    entry = find_topic(topic)
    package = get_package(topic, version)
    if package is None:
        return None
    lesson = package.lesson
    sections, notes = reference_sections(lesson)
    return {
        "id": entry[0],
        "title": lesson.title,
        "date": None,
        "available": True,
        "library": True,
        "version": version,
        "review": review_note(lesson),
        "sections": [
            {
                "heading": "Before you start",
                "blocks": md_blocks("\n".join(f"- {s}" for s in package.prerequisites)),
            },
            {
                "heading": "What you will learn",
                "blocks": md_blocks("\n".join(f"- {s}" for s in package.objectives)),
            },
            *sections,
        ],
        "notes": notes,
        "exercises": [],
        "extension": [
            {
                "title": display_name(task.name),
                "minutes": task.minutes,
                "blocks": md_blocks(
                    f"**Goal:** {task.goal}\n"
                    + "\n".join(f"{i}. {step}" for i, step in enumerate(task.steps, 1))
                ),
            }
            for task in lesson.tasks
        ],
        "interview": {
            "question": md_blocks(lesson.interview_question or ""),
            "points": [md_blocks(point) for point in lesson.interview_points],
        },
        "references": lesson.references,
        "resources": related_view(topic),
        "walkthrough": package.storyboard.model_dump(mode="json"),
        "learn_command": f"/learn {entry[0]}",
        "feedback": None,
    }


def read_text(topic):
    from skillcoach.lesson_delivery import full_reference

    package = get_package(topic)
    if package is None:
        return "Choose a topic with /topics <module_id>, then /read <topic_id>."
    lesson = package.lesson
    return (
        f"**Stored course · {VERSION}**\nReading does not complete tasks or labs.\n\n"
        + full_reference(lesson, lesson.tasks, topic=topic)
        + "\n\n**Interview question**\n"
        + (lesson.interview_question or "")
        + "\n\n**Cost and safety**\n"
        + lesson.safety
        + "\n\n**Cleanup**\n"
        + "\n".join(f"- {step}" for step in lesson.cleanup)
    )
