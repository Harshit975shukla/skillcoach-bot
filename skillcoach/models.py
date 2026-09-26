from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=16000)]
Short = Annotated[str, Field(min_length=1, max_length=300)]
Percent = Annotated[int, Field(strict=True, ge=0, le=100)]
Score = Annotated[int, Field(strict=True, ge=0, le=10)]
Choice = Literal["A", "B", "C", "D"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumeInfo(Model):
    name: Short
    current_role: Short
    target_role: Short
    level: Literal["beginner", "intermediate", "advanced", "unassessed"]
    years_experience: Annotated[int, Field(strict=True, ge=0, le=80)]
    skills: list[Short] = Field(max_length=30)


class Readiness(Model):
    readiness_score: Percent
    strong_skills: list[Short] = Field(max_length=30)
    gap_skills: list[Short] = Field(max_length=30)
    summary: Text
    skill_ratings: dict[Short, Annotated[int, Field(strict=True, ge=0, le=5)]]


class GapAnalysis(Readiness):
    target_role: Short


class Profile(ResumeInfo):
    resume_text: str = ""
    jd_text: str = ""
    readiness: Readiness | None = None
    readiness_basis: Literal["diagnostic", "resume-jd", "unavailable"] = "unavailable"


class OpenQuestion(Model):
    skill: Short
    question: Text


class Diagnostic(Model):
    questions: list[OpenQuestion] = Field(min_length=5, max_length=5)


class Draft(Model):
    id: str
    stage: Literal["resume", "jd", "diagnostic"] = "resume"
    resume_text: str = ""
    resume_info: ResumeInfo | None = None
    questions: list[OpenQuestion] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)


class Question(Model):
    question: Text
    options: dict[Choice, Short]
    answer: Choice
    explanation: Text
    topic: Short

    @model_validator(mode="after")
    def complete_options(self):
        if set(self.options) != {"A", "B", "C", "D"}:
            raise ValueError("Exactly A, B, C, D options are required")
        if len(set(self.options.values())) != 4:
            raise ValueError("Options must be distinct")
        return self


class Questions(Model):
    questions: list[Question] = Field(min_length=5, max_length=10)


class Answer(Model):
    question_id: str
    given: Choice
    correct: bool
    created_at: datetime


class Assessment(Model):
    id: str
    kind: Literal["daily", "weekly"]
    date: date
    week: str
    status: Literal["active", "completed", "expired", "cancelled"] = "active"
    questions: list[Question]
    question_ids: list[str]
    answers: list[Answer] = Field(default_factory=list)
    completed_at: datetime | None = None


class InterviewFeedback(Model):
    score: Score
    accuracy: Score
    reasoning: Score
    communication: Score
    feedback: Text
    model_answer: Text


class Interview(Model):
    id: str
    question: OpenQuestion
    status: Literal["active", "completed", "cancelled"] = "active"
    answer: str | None = None
    feedback: InterviewFeedback | None = None
    completed_at: datetime | None = None


class ResumeFeedback(Model):
    score: Percent
    issues: list[Short] = Field(max_length=20)
    wins: list[Short] = Field(max_length=20)
    summary: Text


class Task(Model):
    id: str
    origin: str
    title: Short
    skill: Short
    detail: str
    assigned_date: date
    estimated_minutes: Annotated[int, Field(strict=True, ge=0, le=480)] = 20
    actual_minutes: Annotated[int, Field(strict=True, ge=0, le=1440)] = 0
    status: Literal["pending", "done", "skipped"] = "pending"
    completed_at: datetime | None = None


class LessonTask(Model):
    name: Short
    goal: Text
    steps: list[Text] = Field(min_length=1, max_length=12)
    minutes: Annotated[int, Field(strict=True, ge=1, le=120)] = 20


class Concept(Model):
    name: Short
    body: Text


class Lesson(Model):
    title: Short
    why: Text
    what: Text
    concepts: list[Concept] = Field(min_length=4, max_length=4)
    e2e: list[Text] = Field(min_length=4, max_length=12)
    tasks: list[LessonTask] = Field(min_length=2, max_length=4)
    key_terms: list[Text] = Field(min_length=3, max_length=15)
    safety: Text
    cleanup: list[Text] = Field(min_length=1, max_length=12)
    references: list[Text] = Field(min_length=1, max_length=15)
    reviewed_at: str


class WeekPlan(Model):
    days: dict[date, Short]
    rationale: Text

    def validate_dates(self, monday: date):
        from datetime import timedelta

        if set(self.days) != {monday + timedelta(days=i) for i in range(6)}:
            raise ValueError("Plan must contain exactly Monday-Saturday dates for the requested week")
        return self


class State(Model):
    profile: Profile | None = None
    draft: Draft | None = None
    focus: Literal["draft", "assessment", "interview"] | None = None
    active_assessment: str | None = None
    active_interview: str | None = None
    paused: bool = False
    media: Literal["video", "static"] = "video"
    voice: bool = False
    preference: str = ""
    plans: dict[str, WeekPlan] = Field(default_factory=dict)
    lessons: dict[str, dict] = Field(default_factory=dict)
    tasks: dict[str, Task] = Field(default_factory=dict)
    assessments: dict[str, Assessment] = Field(default_factory=dict)
    interviews: dict[str, Interview] = Field(default_factory=dict)
    resume_feedback: ResumeFeedback | None = None
    activity: list[date] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    legacy_archive: dict = Field(default_factory=dict)

    def target(self) -> dict | None:
        if self.focus == "draft" and self.draft:
            return {
                "kind": self.draft.stage,
                "session": self.draft.id,
                "question": str(len(self.draft.answers)),
            }
        if self.focus == "assessment" and self.active_assessment:
            item = self.assessments[self.active_assessment]
            if item.status == "active" and len(item.answers) < len(item.questions):
                return {
                    "kind": "assessment",
                    "session": item.id,
                    "question": item.question_ids[len(item.answers)],
                }
        if self.focus == "interview" and self.active_interview:
            item = self.interviews[self.active_interview]
            if item.status == "active":
                return {"kind": "interview", "session": item.id, "question": item.id}
        return None
