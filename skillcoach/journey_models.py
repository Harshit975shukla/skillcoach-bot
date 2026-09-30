"""Private onboarding state and the bounded, reviewable learning-plan contract."""

from datetime import date as Date
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from skillcoach.models_base import Model, Short, Text

REASONS = {
    "foundation": "Establish the foundations before more advanced practice.",
    "diagnostic": "Include targeted practice informed by the initial diagnostic.",
    "goal": "Connect practice to the learner's selected learning goal.",
    "revision": "Revisit a topic instead of treating prior exposure as mastery.",
    "prerequisite": "Build a prerequisite needed by a later session.",
}


class PlanDay(Model):
    topic_id: Short
    objective: Text = Field(max_length=800)
    practice: Text = Field(max_length=800)
    reason: Literal["foundation", "diagnostic", "goal", "revision", "prerequisite"]
    date: Date | None = None
    lesson_key: str | None = None
    understood_at: datetime | None = None

    @model_validator(mode="after")
    def catalog_topic(self):
        from skillcoach.catalog import TOPICS

        if self.topic_id not in TOPICS:
            raise ValueError("Choose an exact topic ID from the supplied catalog")
        return self


class PlanDraft(Model):
    sessions: list[PlanDay] = Field(min_length=5, max_length=5)
    rationale: Text = Field(max_length=2000)


class LearningPlan(PlanDraft):
    id: str
    version: int = Field(ge=1)
    created_at: datetime
    approved_at: datetime | None = None
    expires_at: datetime
    minutes: int = Field(ge=15, le=60)
    level: Literal["beginner", "intermediate", "advanced"]
    timezone: str
    start_now_at: datetime | None = None
    replaces_plan_id: str | None = None
    labs_enabled: bool = False
    # Set when a next-week proposal started on schedule without an explicit tap.
    auto_started_at: datetime | None = None


class Suggestion(Model):
    id: str
    plan_id: str
    topic_id: str
    status: Literal["pending", "accepted", "declined"] = "pending"


class Journey(Model):
    id: str
    stage: Literal[
        "welcome",
        "consent",
        "goal",
        "years",
        "level",
        "minutes",
        "timezone",
        "resume",
        "jd",
        "diagnostic",
        "planning",
        "ready",
        "revision",
        "active",
    ] = "welcome"
    consent_at: datetime | None = None
    goal: str = ""
    years: int | None = None
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    minutes: int = 30
    timezone: str = "Asia/Kolkata"
    resume_text: str = ""
    jd_text: str = ""
    diagnostic_questions: list[dict] = Field(default_factory=list)
    diagnostic_answers: list[str] = Field(default_factory=list)
    diagnostic_rating: dict | None = None
    diagnostic_practice_date: Date | None = None
    revision_request: str = ""
    plans: dict[str, LearningPlan] = Field(default_factory=dict)
    proposed_id: str | None = None
    active_id: str | None = None
    suggestion: Suggestion | None = None
    version: int = 0
    lab_gate_since: datetime | None = None

    def target(self):
        stage = self.stage
        if stage == "diagnostic":
            stage += "-" + str(len(self.diagnostic_answers))
        return {"kind": "onboarding", "session": self.id, "question": stage}
