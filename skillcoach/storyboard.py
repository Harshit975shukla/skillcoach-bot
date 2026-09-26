"""Validated educational scene data. No generated code, paths, HTML or external rendering."""

import hashlib
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from skillcoach.models import Model

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,20}$")]
Label = Annotated[str, Field(min_length=1, max_length=48)]
NARRATOR_VERSION = "espeak-ng-en-us-150-v1"
RENDERER_VERSION = "scene-renderer-v1"
REFERENCE_HOSTS = {
    "docs.aws.amazon.com",
    "aws.amazon.com",
    "learn.microsoft.com",
    "cloud.google.com",
    "kubernetes.io",
    "docs.docker.com",
    "developer.hashicorp.com",
    "opentofu.org",
    "www.pulumi.com",
    "docs.ansible.com",
    "docs.github.com",
    "docs.gitlab.com",
    "www.jenkins.io",
    "helm.sh",
    "argo-cd.readthedocs.io",
    "fluxcd.io",
    "prometheus.io",
    "grafana.com",
    "opentelemetry.io",
    "sre.google",
    "owasp.org",
    "backstage.io",
    "docs.crossplane.io",
    "kafka.apache.org",
    "mlflow.org",
    "www.finops.org",
    "git-scm.com",
    "docs.python.org",
    "www.kernel.org",
    "www.rfc-editor.org",
    "man7.org",
    "www.gnu.org",
    "redis.io",
    "www.postgresql.org",
}


class Actor(Model):
    id: Identifier
    label: Label


class Edge(Model):
    id: Identifier
    source: Identifier
    target: Identifier
    label: Annotated[str, Field(max_length=30)] = ""
    kind: Literal["request", "control", "replication"] = "request"


class Scene(Model):
    title: Annotated[str, Field(min_length=1, max_length=70)]
    caption: Annotated[str, Field(min_length=1, max_length=180)]
    narration: Annotated[str, Field(min_length=15, max_length=360)]
    active_edges: list[Identifier] = Field(default_factory=list, max_length=8)
    highlights: list[Identifier] = Field(default_factory=list, max_length=6)
    states: dict[Identifier, Literal["healthy", "unhealthy", "starting", "waiting", "complete"]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def bounded_speech(self):
        if len(self.narration.split()) > 55:
            raise ValueError("Each scene must be a short explanation, at most 55 words")
        return self


class Storyboard(Model):
    title: Annotated[str, Field(min_length=1, max_length=100)]
    objective: Annotated[str, Field(min_length=1, max_length=180)]
    pattern: Literal["flow", "decision", "timeline", "comparison"]
    actors: list[Actor] = Field(min_length=2, max_length=6)
    edges: list[Edge] = Field(max_length=8)
    scenes: list[Scene] = Field(min_length=3, max_length=5)
    references: list[Annotated[str, Field(min_length=10, max_length=400)]] = Field(
        min_length=1, max_length=10
    )

    @model_validator(mode="after")
    def coherent_graph(self):
        actors = {actor.id for actor in self.actors}
        edges = {edge.id for edge in self.edges}
        if len(actors) != len(self.actors) or len(edges) != len(self.edges):
            raise ValueError("Actor and edge identifiers must be unique")
        if any(
            edge.source not in actors or edge.target not in actors or edge.source == edge.target
            for edge in self.edges
        ):
            raise ValueError("Every edge must connect two different declared actors")
        for scene in self.scenes:
            if (
                not set(scene.active_edges) <= edges
                or not set(scene.highlights) <= actors
                or not set(scene.states) <= actors
            ):
                raise ValueError("Scenes may only refer to declared actors and edges")
            if not scene.active_edges and not scene.highlights and not scene.states:
                raise ValueError("Each scene must show a meaningful change or focus")
            if any(ord(char) < 32 and char not in "\n\t" for char in scene.narration):
                raise ValueError("Narration contains unsupported control characters")
        for reference in self.references:
            parsed = urlsplit(reference)
            if parsed.scheme != "https" or parsed.hostname not in REFERENCE_HOSTS or parsed.username:
                raise ValueError("References must use an allowlisted official HTTPS documentation host")
        return self


def asset_key(storyboard: Storyboard, learner_id: str, *, voice: bool, shared_reviewed=False):
    data = {
        "storyboard": storyboard.model_dump(),
        "voice": voice,
        "renderer": RENDERER_VERSION,
        "narrator": NARRATOR_VERSION,
        "scope": "shared-reviewed" if shared_reviewed else learner_id,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


# Each tuple is a reviewed normal/failure/recovery explanation, not arbitrary AI-generated motion.
ARCHITECTURE_DATA = {
    "ec2": (
        ["Client", "Application load balancer", "EC2 app in AZ A", "EC2 app in AZ B", "Auto Scaling Group"],
        [(0, 1, "request"), (1, 2, "request"), (1, 3, "request"), (4, 2, "control")],
        [
            (
                "Route healthy traffic",
                "The ALB routes requests to healthy targets across availability zones.",
                "An application load balancer routes requests to healthy registered targets. An Auto Scaling Group maintains the desired instance count across the selected availability zones.",
                [0, 1, 2],
                {2: "healthy", 3: "healthy"},
            ),
            (
                "Detect an application failure",
                "A running VM can still have an unhealthy application.",
                "An EC2 status check does not prove the web application works. Application health checks identify a failed target. With a healthy target and enough capacity in the other zone, requests can continue there.",
                [0, 2],
                {2: "unhealthy", 3: "healthy"},
            ),
            (
                "Replace and warm up",
                "ASG ELB health checks enable app-health-based replacement; new capacity must initialize.",
                "Enable load balancer health checks on the Auto Scaling Group to replace unhealthy application instances. A replacement needs time to boot and become ready. Keep serving traffic from healthy capacity while it initializes.",
                [0, 2, 3],
                {2: "starting", 3: "healthy"},
            ),
            (
                "Return to healthy capacity",
                "Passing readiness checks makes the replacement eligible for traffic.",
                "After the replacement passes target health checks, the load balancer can route requests to it. Configure warm up for measured startup behavior. This animation shows a sequence, not a guaranteed recovery duration.",
                [0, 1, 2],
                {2: "healthy", 3: "healthy"},
            ),
        ],
    ),
    "s3": (
        [
            "Application",
            "Applicable policy evaluation",
            "Private S3 bucket",
            "Versioned object",
            "Lifecycle policy",
        ],
        [(0, 1, "request"), (1, 2, "request"), (2, 3, "request"), (4, 3, "control")],
        [
            (
                "Evaluate access",
                "S3 authenticates the caller and evaluates applicable permissions.",
                "An upload begins with an authenticated request. S3 evaluates applicable identity and resource policies, explicit denies and public access controls. Same account and cross account permission rules differ.",
                [0, 1],
                {},
            ),
            (
                "Store the object",
                "Object Ownership and Block Public Access are different controls.",
                "Bucket owner enforced Object Ownership disables access control lists. Block Public Access separately restricts public grants. Store the object with the chosen encryption and versioning configuration.",
                [1, 2],
                {3: "complete"},
            ),
            (
                "Manage lifecycle",
                "Configured lifecycle rules act on eligible objects and versions.",
                "Lifecycle policies transition or expire eligible objects and versions according to supported rules. Model retrieval time, request charges and minimum storage duration. Use explicit checksum fields rather than assuming every ETag is an object MD5.",
                [3],
                {3: "waiting"},
            ),
        ],
    ),
    "rds": (
        [
            "Application",
            "Traditional RDS primary",
            "Multi-AZ standby",
            "Optional read replica",
            "Backup / restore",
        ],
        [(0, 1, "request"), (1, 2, "replication"), (1, 3, "replication"), (1, 4, "control")],
        [
            (
                "Write to the primary",
                "This diagram is a traditional Multi-AZ DB instance, not a Multi-AZ DB cluster.",
                "The application writes through the primary database endpoint. In a traditional Multi AZ database instance deployment, synchronous replication maintains a standby in another availability zone. That standby does not serve application reads.",
                [0, 1],
                {1: "healthy", 2: "healthy"},
            ),
            (
                "Scale eligible reads",
                "Read replicas use asynchronous replication and can lag.",
                "An optional read replica can offload suitable read traffic. Its asynchronous replication can lag, so route consistency sensitive reads deliberately. A Multi AZ database cluster has a different design with readable replicas; do not confuse the two.",
                [2],
                {3: "healthy"},
            ),
            (
                "Plan recovery",
                "Reconnect after failover; PITR creates a new database endpoint.",
                "Test application reconnection and transaction retries after failover. Backups and point in time recovery address different failure modes. A restore creates a new database, and its timestamp must fall within the reported restorable window.",
                [3],
                {4: "complete"},
            ),
        ],
    ),
    "vpc": (
        [
            "Internet client",
            "Public load balancer",
            "Private application",
            "Private data tier",
            "Public NAT / IGW",
        ],
        [(0, 1, "request"), (1, 2, "request"), (2, 3, "request"), (2, 4, "request")],
        [
            (
                "Enter through the public tier",
                "Routes and security rules determine the allowed path.",
                "A public load balancer accepts permitted client traffic and forwards it to the application tier. Routing, network access controls and security groups must all support the intended path.",
                [0, 1],
                {1: "healthy"},
            ),
            (
                "Keep the data tier private",
                "Permit only the application sources and required database ports.",
                "The application reaches a private data tier through local network routing. Restrict its database security group to the intended application sources and ports. A private subnet is not a substitute for permission and firewall design.",
                [2],
                {3: "healthy"},
            ),
            (
                "Choose outbound connectivity",
                "Public NAT can provide outbound IPv4; service endpoints may avoid that path.",
                "For outbound internet access, a public NAT gateway can provide translation through an internet gateway. A private NAT gateway is different. For supported services, consider VPC endpoints and compare availability, policies and transfer costs.",
                [3],
                {4: "healthy"},
            ),
        ],
    ),
    "iam": (
        [
            "Identity",
            "Temporary credentials",
            "Signed service request",
            "Applicable policies",
            "Allowed action",
            "Denied action",
        ],
        [(0, 1, "control"), (1, 2, "request"), (2, 3, "control"), (3, 4, "control"), (3, 5, "control")],
        [
            (
                "Obtain credentials",
                "Prefer federation and scoped workload roles.",
                "A human or workload obtains scoped credentials through the appropriate credential provider. Roles commonly provide temporary credentials. The client signs the service request; it does not ask IAM to preauthorize every request first.",
                [0, 1],
                {},
            ),
            (
                "Evaluate applicable policies",
                "The principal, action, resource and conditions determine the evaluation.",
                "AWS authenticates the request and evaluates applicable policies. Identity policies, resource policies, boundaries and organization controls have different roles. Same account and cross account evaluation are not a universal requirement for two independent allows.",
                [2],
                {},
            ),
            (
                "Apply the decision",
                "An applicable explicit deny overrides allows.",
                "An applicable explicit deny blocks the action. Otherwise, the required grants and constraints determine access. Troubleshoot the exact principal, action, resource and conditions instead of expanding permissions blindly.",
                [4],
                {5: "complete"},
            ),
        ],
    ),
    "lambda": (
        [
            "Synchronous caller",
            "Lambda function",
            "Async invocation queue",
            "SQS event mapping",
            "Durable state",
            "Failure handling",
        ],
        [
            (0, 1, "request"),
            (2, 1, "request"),
            (3, 1, "request"),
            (1, 4, "request"),
            (2, 5, "control"),
            (3, 5, "control"),
        ],
        [
            (
                "Synchronous invocation",
                "The caller waits; durable state belongs outside the execution environment.",
                "A synchronous caller waits for the function response. Keep durable application state outside the execution environment. Warm reuse is opportunistic, and concurrency or initialization behavior must be measured.",
                [0, 3],
                {1: "healthy"},
            ),
            (
                "Asynchronous delivery",
                "Function errors and throttling use different retry behavior.",
                "For asynchronous invocation, Lambda queues the event. Function errors and throttling or system errors use different retry behavior and configurable event age limits. Handlers must tolerate duplicate delivery.",
                [1, 4],
                {2: "waiting"},
            ),
            (
                "Queue-driven processing",
                "SQS uses visibility and queue redrive, not the Lambda async retry policy.",
                "An SQS event source mapping polls messages and invokes the function in batches. Visibility timeout, partial batch responses and the queue redrive policy control recovery. These are not the same as Lambda asynchronous invocation retries.",
                [2, 5],
                {3: "healthy"},
            ),
        ],
    ),
}


def reviewed_architecture(topic: str) -> Storyboard | None:
    from lesson_content import REFERENCES

    words = re.sub(r"[^a-z0-9]+", " ", topic.casefold()).split()
    key = next((key for key in ARCHITECTURE_DATA if key in words), None)
    if key is None:
        return None
    labels, connections, stages = ARCHITECTURE_DATA[key]
    return Storyboard(
        title=f"{key.upper()} - behavior and trade-offs",
        objective=stages[0][1],
        pattern="decision" if key == "iam" else "flow",
        actors=[Actor(id=f"n{i}", label=label) for i, label in enumerate(labels)],
        edges=[
            Edge(id=f"e{i}", source=f"n{a}", target=f"n{b}", kind=kind)
            for i, (a, b, kind) in enumerate(connections)
        ],
        scenes=[
            Scene(
                title=title,
                caption=caption,
                narration=narration,
                active_edges=[f"e{i}" for i in active],
                highlights=[f"n{i}" for i in states] or ["n0"],
                states={f"n{i}": state for i, state in states.items()},
            )
            for title, caption, narration, active, states in stages
        ],
        references=REFERENCES[key],
    )


def concept_walkthrough(lesson, index: int) -> Storyboard:
    """Narrate exact reviewed concept text in bounded excerpts; never invent a system data path."""
    concept = lesson.concepts[index]
    sentences = re.split(r"(?<=[.!?])\s+", concept.body)
    chunks, current = [], ""
    for sentence in sentences:
        for phrase in re.findall(r".{1,260}(?:\s|$)", sentence + " "):
            phrase = phrase.strip()
            if current and (len(current) + len(phrase) > 320 or len((current + phrase).split()) > 50):
                chunks.append(current)
                current = ""
            current = (current + " " + phrase).strip()
    if current:
        chunks.append(current)
    chunks = chunks[:4]
    while len(chunks) < 3:
        chunks.append(
            "Apply this concept to a safe paper design. Explain the assumptions, compare trade-offs, "
            "and check the official documentation before provisioning resources."
        )
    actors = [
        Actor(id="concept", label=concept.name[:48]),
        Actor(id="mechanism", label="Explain the mechanism"),
        Actor(id="tradeoff", label="Check assumptions and trade-offs"),
        Actor(id="practice", label="Apply and verify"),
    ]
    steps = ["mechanism", "tradeoff", "practice", "practice"]
    return Storyboard(
        title=concept.name[:100],
        objective="Explain this concept and its operational trade-offs.",
        pattern="timeline",
        actors=actors,
        edges=[
            Edge(id="e0", source="concept", target="mechanism", kind="control"),
            Edge(id="e1", source="mechanism", target="tradeoff", kind="control"),
            Edge(id="e2", source="tradeoff", target="practice", kind="control"),
        ],
        scenes=[
            Scene(
                title=f"Concept walkthrough - part {i + 1}",
                caption=text[:177] + ("..." if len(text) > 177 else ""),
                narration=text,
                highlights=["concept", steps[i]],
            )
            for i, text in enumerate(chunks)
        ],
        references=lesson.references,
    )
