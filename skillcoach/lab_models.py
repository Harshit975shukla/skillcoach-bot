"""Lab data structures shared by the core AWS lab catalog and the per-module lab catalog."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    prompt: str
    options: tuple[str, str, str, str]  # The first option is correct; attempts shuffle the display order.
    explanation: str


@dataclass(frozen=True)
class AwsRoute:
    kind: str
    steps: tuple[str, ...]
    cleanup: tuple[str, ...]
    submit: str


@dataclass(frozen=True)
class CodeRoute:
    steps: tuple[str, ...]


@dataclass(frozen=True)
class LocalRoute:
    """Free, self-checked practice on the learner's own machine. Never submitted or verified."""

    tools: str
    steps: tuple[str, ...]
    cleanup: tuple[str, ...]


@dataclass(frozen=True)
class Lab:
    id: str
    title: str
    topics: tuple[str, ...]
    minutes: int
    goal: str
    references: tuple[str, ...]
    scenario: tuple[Step, Step, Step, Step]
    aws: AwsRoute | None = None
    code: CodeRoute | None = None
    local: LocalRoute | None = None
    routes: tuple[str, ...] = field(init=False)

    def __post_init__(self):
        routes = (
            ["scenario"]
            + (["code"] if self.code else [])
            + (["aws"] if self.aws else [])
            + (["local"] if self.local else [])
        )
        object.__setattr__(self, "routes", tuple(routes))
