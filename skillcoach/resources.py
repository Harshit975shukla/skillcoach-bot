"""Curated outbound learning links; no third-party course content is copied or fetched at runtime."""

import re
from dataclasses import asdict, dataclass

from skillcoach.catalog import find_topic

RESOURCE_VERSION = "2026-09-29"
GROUPS = {"cloud": "Cloud", "devops": "DevOps", "linux": "Linux"}
PAGE_SIZE = 4
NOTICE = (
    "Optional external learning, not required SkillCoach labs. Opening a link does not record completion, "
    "practice minutes or mastery, and never blocks quizzes or next week's plan. "
    "Free reading does not mean free cloud usage or certification. Provider access and limits can change."
)
RIGHTS = (
    "Links and original SkillCoach guidance only. Materials belong to their publishers; "
    "free access is not permission to copy, rehost, translate or resell them. No affiliation is implied."
)
ACCOUNTS = {"none": "No account to read", "optional": "Account optional", "required": "Free account required"}
CLOUD_COST = "Reading is free. Creating resources in your own cloud account may cost money; skip deployment."
LOCAL_COST = "Reading is free. Practice locally in a disposable environment, not on a production machine."


@dataclass(frozen=True)
class Resource:
    id: str
    group: str
    title: str
    provider: str
    url: str
    kind: str
    level: str
    account: str
    modules: tuple[str, ...]
    tags: str
    summary: str
    start: str
    cost_note: str
    rights_note: str = "Link only; publisher terms apply."

    def view(self):
        return {
            **asdict(self),
            "account_label": ACCOUNTS[self.account],
            "checked_at": RESOURCE_VERSION,
        }


RESOURCES = (
    Resource(
        "aws-educate",
        "cloud",
        "AWS Educate",
        "Amazon Web Services",
        "https://aws.amazon.com/education/awseducate/",
        "Course collection",
        "beginner",
        "required",
        ("foundations", "aws-core", "aws-data", "aws-platform"),
        "aws cloud fundamentals ec2 vpc rds sqs dynamodb",
        "Self-paced cloud training, videos and provider-managed practice.",
        "Choose an introductory compute, storage or networking activity in AWS Educate.",
        "AWS Educate learning is free. Use its supplied lab environment, not your own billed AWS account.",
    ),
    Resource(
        "aws-well-architected",
        "cloud",
        "AWS Well-Architected Framework",
        "Amazon Web Services",
        "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
        "Guide",
        "intermediate",
        "none",
        ("foundations", "aws-core", "aws-data", "aws-platform", "sre", "finops"),
        "aws architecture reliability security cost sustainability",
        "A framework for reasoning about operational, reliability and cost trade-offs.",
        "Read one pillar and identify a trade-off in a hypothetical service.",
        CLOUD_COST,
    ),
    Resource(
        "azure-cloud-concepts",
        "cloud",
        "Describe cloud concepts",
        "Microsoft Learn",
        "https://learn.microsoft.com/en-us/training/paths/microsoft-azure-fundamentals-describe-cloud-concepts/",
        "Learning path",
        "beginner",
        "optional",
        ("foundations", "azure"),
        "azure cloud models shared responsibility fundamentals",
        "Three introductory modules on cloud concepts, benefits and service models.",
        "Start with the cloud-computing module; sign in only if you want Microsoft to save progress.",
        "Self-paced reading is free. Certification exams and your own Azure resources can cost money.",
    ),
    Resource(
        "google-cloud-overview",
        "cloud",
        "Google Cloud overview",
        "Google Cloud",
        "https://docs.cloud.google.com/docs/overview",
        "Guide",
        "beginner",
        "none",
        ("gcp", "foundations"),
        "gcp google cloud regions zones projects",
        "Understand the structure of Google Cloud and its resource scopes.",
        "Compare global, regional and zonal resources without creating a project.",
        CLOUD_COST,
    ),
    Resource(
        "aws-s3-guide",
        "cloud",
        "Amazon S3: concepts and access",
        "Amazon Web Services",
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html",
        "Documentation",
        "beginner",
        "none",
        ("aws-data",),
        "aws s3 storage objects buckets",
        "An official starting point for S3 storage, consistency and access concepts.",
        "Read the core concepts, then compare them with the SkillCoach S3 scenario.",
        CLOUD_COST,
    ),
    Resource(
        "aws-lambda-guide",
        "cloud",
        "AWS Lambda overview",
        "Amazon Web Services",
        "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html",
        "Documentation",
        "beginner",
        "none",
        ("aws-core", "aws-platform"),
        "aws lambda serverless functions",
        "Learn the service model before studying invocation and failure handling.",
        "Read the overview and sketch an event-to-function flow without deploying it.",
        CLOUD_COST,
    ),
    Resource(
        "aws-iam-guide",
        "cloud",
        "AWS IAM introduction",
        "Amazon Web Services",
        "https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html",
        "Documentation",
        "beginner",
        "none",
        ("aws-core",),
        "aws iam roles policies permissions identity",
        "Separate identity, authentication and authorization in AWS.",
        "Explain why an application should use a role rather than root-user credentials.",
        CLOUD_COST,
    ),
    Resource(
        "pro-git",
        "devops",
        "Pro Git",
        "Scott Chacon and Ben Straub / Git",
        "https://git-scm.com/book/en/v2",
        "Book",
        "beginner",
        "none",
        ("git",),
        "git branches merge rebase commits remotes",
        "A free online book covering Git fundamentals through advanced workflows.",
        "Read Git Basics and try commits and branches in a disposable local repository.",
        LOCAL_COST,
        "Link only. The book is CC BY-NC-SA 3.0; do not copy it into commercial course material.",
    ),
    Resource(
        "github-actions",
        "devops",
        "Quickstart for GitHub Actions",
        "GitHub",
        "https://docs.github.com/en/actions/get-started/quickstart",
        "Tutorial",
        "beginner",
        "optional",
        ("delivery", "git"),
        "github actions ci cd pipeline workflow runners",
        "Learn the relationship between workflow triggers, jobs and steps.",
        "Read the example first; a GitHub account is needed only to run your own workflow.",
        "Reading is free. Runner type, repository visibility and usage affect Actions billing; check limits.",
    ),
    Resource(
        "docker-app",
        "devops",
        "Build and share a containerized application",
        "Docker",
        "https://docs.docker.com/get-started/tutorials/run-an-app/",
        "Tutorial",
        "beginner",
        "optional",
        ("containers",),
        "docker containers images compose ports",
        "Work through containers, a multi-container app and image packaging.",
        "Read first, then use a disposable local app; the full tutorial asks for a Docker account.",
        "Tutorial is free. Check Docker Desktop license eligibility and Docker Hub limits before installing.",
    ),
    Resource(
        "kubernetes-basics",
        "devops",
        "Learn Kubernetes Basics",
        "Kubernetes",
        "https://kubernetes.io/docs/tutorials/kubernetes-basics/",
        "Tutorial",
        "beginner",
        "none",
        ("kubernetes",),
        "kubernetes pods deployments replicas scaling updates debugging",
        "Walk through deployment, scaling, updates and debugging.",
        "Start with the cluster and deployment modules; use a local cluster or a free browser scenario.",
        "Reading is free. Use a local practice cluster; managed cloud clusters can incur charges.",
    ),
    Resource(
        "terraform-docker",
        "devops",
        "Terraform: get started with Docker",
        "HashiCorp",
        "https://developer.hashicorp.com/terraform/tutorials/docker-get-started",
        "Tutorial collection",
        "beginner",
        "none",
        ("iac", "containers"),
        "terraform providers resources state plan apply destroy docker",
        "Learn the Terraform lifecycle using containers rather than cloud resources.",
        "Follow the Docker track locally and destroy only the resources created for that exercise.",
        "Tutorials are free. Local Docker is required; check its license. Other cloud-provider tracks may cost.",
    ),
    Resource(
        "ansible-start",
        "devops",
        "Getting started with Ansible",
        "Ansible community",
        "https://docs.ansible.com/projects/ansible/latest/getting_started/index.html",
        "Tutorial",
        "beginner",
        "none",
        ("iac", "automation"),
        "ansible inventory playbook configuration automation",
        "Learn control nodes, inventories, managed nodes and playbooks.",
        "Read the introduction, then target only disposable local machines you own.",
        LOCAL_COST,
    ),
    Resource(
        "prometheus-start",
        "devops",
        "First steps with Prometheus",
        "Prometheus",
        "https://prometheus.io/docs/introduction/first_steps/",
        "Tutorial",
        "intermediate",
        "none",
        ("observability",),
        "prometheus monitoring metrics scrape exporters",
        "Run a local metrics server and understand scrape configuration.",
        "Read the scrape example and keep a practice server local rather than exposing it publicly.",
        LOCAL_COST,
    ),
    Resource(
        "google-sre-books",
        "devops",
        "Site Reliability Engineering books",
        "Google",
        "https://sre.google/books/",
        "Books",
        "intermediate",
        "none",
        ("sre", "observability"),
        "sre reliability incidents error budgets slo monitoring",
        "Free online reading on reliability engineering and practical operating principles.",
        "Choose Read online, then study one chapter on service objectives or incident response.",
        "Online reading is free. Buying print editions is optional.",
    ),
    Resource(
        "killercoda",
        "devops",
        "Killercoda free scenarios",
        "Killercoda",
        "https://killercoda.com/",
        "Browser practice",
        "beginner",
        "required",
        ("linux", "networking", "containers", "kubernetes"),
        "linux kubernetes containers shell playground",
        "Temporary Linux and Kubernetes environments with community-authored scenarios.",
        "Choose a free scenario, not a paid course, and save your notes before the environment expires.",
        "Free membership has session/queue limits. PLUS and paid Courses are optional, not included.",
    ),
    Resource(
        "argo-cd-start",
        "devops",
        "Getting started with Argo CD",
        "Argo project",
        "https://argo-cd.readthedocs.io/en/stable/getting_started/",
        "Tutorial",
        "intermediate",
        "none",
        ("gitops", "kubernetes"),
        "gitops argo cd reconciliation deployment",
        "Explore Git-driven deployment and reconciliation with a sample application.",
        "Read the requirements; use a disposable local cluster, never your employer's cluster.",
        "Reading is free. A cluster is required to practice; a managed cloud cluster can cost money.",
    ),
    Resource(
        "helm-quickstart",
        "devops",
        "Helm quickstart",
        "Helm",
        "https://helm.sh/docs/intro/quickstart/",
        "Tutorial",
        "intermediate",
        "none",
        ("kubernetes", "gitops"),
        "helm charts releases kubernetes",
        "Learn how charts and releases package a Kubernetes application.",
        "Review a chart's contents before installing it in a disposable local cluster.",
        "Reading is free. Some charts create billable cloud resources; inspect them before installation.",
    ),
    Resource(
        "ubuntu-command-line",
        "linux",
        "The Linux command line for beginners",
        "Canonical / Ubuntu",
        "https://ubuntu.com/tutorials/command-line-for-beginners",
        "Tutorial",
        "beginner",
        "none",
        ("linux", "automation"),
        "shell terminal files pipelines permissions",
        "A guided introduction to navigating files and combining shell commands.",
        "Start in a new temporary practice directory; do not experiment on important files.",
        LOCAL_COST,
    ),
    Resource(
        "bash-manual",
        "linux",
        "Bash reference manual",
        "GNU",
        "https://www.gnu.org/software/bash/manual/bash.html",
        "Reference",
        "intermediate",
        "none",
        ("linux", "automation"),
        "bash shell pipelines quoting scripts exit status",
        "Look up shell expansion, quoting, redirection and scripting behavior.",
        "Read the quoting and exit-status sections alongside a small disposable script.",
        LOCAL_COST,
    ),
    Resource(
        "linux-command-line-book",
        "linux",
        "The Linux Command Line",
        "William Shotts / LinuxCommand.org",
        "https://linuxcommand.org/tlcl.php",
        "Book",
        "beginner",
        "none",
        ("linux", "automation"),
        "linux shell command line scripting files",
        "A freely downloadable Internet edition for command-line learners.",
        "Use the publisher's free Internet edition and start with navigation and file permissions.",
        LOCAL_COST,
        "Link only. Publisher lists CC BY-NC-ND terms; no copying, adaptation or commercial redistribution.",
    ),
    Resource(
        "debian-handbook",
        "linux",
        "The Debian Administrator's Handbook",
        "Raphael Hertzog and Roland Mas / Debian",
        "https://www.debian.org/doc/manuals/debian-handbook/",
        "Book",
        "intermediate",
        "none",
        ("linux",),
        "debian packages apt networking storage administration",
        "A free reference on Debian installation and system administration.",
        "Use concepts for orientation; this linked edition covers Bullseye, so check your release's manuals.",
        LOCAL_COST,
    ),
    Resource(
        "systemd-manual",
        "linux",
        "systemd system and service manager",
        "systemd project",
        "https://www.freedesktop.org/software/systemd/man/latest/systemd.html",
        "Reference",
        "intermediate",
        "none",
        ("linux",),
        "systemd processes services units boot logs",
        "An upstream reference for the Linux service manager and related manuals.",
        "Read about units; compare with your installed systemd version before changing services.",
        LOCAL_COST,
    ),
    Resource(
        "missing-semester",
        "linux",
        "The Missing Semester of Your CS Education",
        "MIT course staff",
        "https://missing.csail.mit.edu/",
        "Course",
        "beginner",
        "none",
        ("linux", "git", "automation"),
        "shell terminal scripting tools debugging git",
        "Public lectures and exercises on the tools used in everyday engineering.",
        "Choose one shell or tooling lecture and try its exercises locally.",
        "Public notes and lectures are free. Any optional third-party tools have their own terms.",
    ),
)


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def search_resources(query=""):
    query = query.strip().casefold()
    if query in ("", "all"):
        return list(RESOURCES)
    direct = next((r for r in RESOURCES if r.id == query), None)
    if direct:
        return [direct]
    if query in GROUPS:
        return [r for r in RESOURCES if r.group == query or query in r.modules]
    topic = find_topic(query)
    if topic:
        return for_topic(query, limit=None)
    if query == "aws":
        return [r for r in RESOURCES if any(m.startswith("aws-") for m in r.modules)]
    modules = [r for r in RESOURCES if query in r.modules]
    if modules:
        return modules
    tokens = _words(query)
    if not tokens:
        return []
    return [
        r
        for r in RESOURCES
        if tokens <= _words(" ".join((r.title, r.provider, r.tags, r.summary, *r.modules)))
    ]


def for_topic(value, limit=3):
    if not value.strip():
        return []
    topic = find_topic(value)
    if topic:
        _, module, title = topic
        candidates = [r for r in RESOURCES if module.id in r.modules]
    else:
        # Legacy authored lessons also accept these short names.
        aliases = {
            "ec2": "aws-core",
            "iam": "aws-core",
            "lambda": "aws-core",
            "vpc": "aws-core",
            "s3": "aws-data",
            "rds": "aws-data",
            "dynamodb": "aws-data",
            "sqs": "aws-platform",
        }
        module = aliases.get(value.strip().casefold())
        candidates = [r for r in RESOURCES if module in r.modules] if module else search_resources(value)
        title = value
    tokens = _words(title) - {"aws", "linux", "kubernetes", "cloud", "and", "the"}
    candidates.sort(key=lambda r: -len(tokens & _words(r.tags)))
    return candidates if limit is None else candidates[:limit]


def related_view(topic):
    return [r.view() for r in for_topic(topic)]


def library_view():
    return {
        "version": RESOURCE_VERSION,
        "notice": NOTICE,
        "rights": RIGHTS,
        "groups": [{"id": key, "label": label} for key, label in GROUPS.items()],
        "items": [r.view() for r in RESOURCES],
    }


def related_text(topic):
    items = for_topic(topic, limit=2)
    if not items:
        return ""
    return (
        "\n\nOptional free learning (external; not tracked):\n"
        + "\n\n".join(
            f"{r.title} - {r.provider}\n{r.url}\n{ACCOUNTS[r.account]}. {r.cost_note}" for r in items
        )
        + "\nMore: /resources. Publisher terms apply."
    )


def resources_text(argument=""):
    argument = argument.strip()
    if not argument:
        return (
            f"Free learning library - {len(RESOURCES)} curated links\n"
            f"Link/access review: {RESOURCE_VERSION} (not a full course audit).\n\n"
            "/resources cloud\n/resources devops\n/resources linux\n"
            "Or search: /resources terraform, /resources aws, /resources <topic_id>.\n"
            "Browse the same library in /dashboard > Free resources.\n\n" + NOTICE + "\n\n" + RIGHTS
        )
    parts = re.fullmatch(r"(.+?)(?:\s+--page\s+([0-9]{1,4}))?", argument)
    if not parts or len(argument) > 240:
        return "Use /resources <category, topic or search> [--page 2]."
    query, number = parts.groups()
    if "--" in query:
        return "Use /resources <category, topic or search> [--page 2]."
    items = search_resources(query)
    if not items:
        return "No curated resources match. Try /resources cloud, /resources devops or /resources linux."
    pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
    page = int(number or 1)
    if not 1 <= page <= pages:
        return f"Page unavailable. This search has {pages} page(s); use /resources {query} --page 1."
    selected = items[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    lines = [f"Free learning - page {page}/{pages}; {len(items)} links. Checked {RESOURCE_VERSION}."]
    for r in selected:
        lines.append(
            f"{r.title} - {r.provider}\n{r.kind} | {r.level} | {ACCOUNTS[r.account]}\n"
            f"{r.summary}\nStart: {r.start}\nCost: {r.cost_note}\n{r.url}"
        )
    lines.append("Optional; opening links does not complete a SkillCoach lab. Publisher terms apply.")
    if page < pages:
        lines.append(f"Next: /resources {query} --page {page + 1}")
    return "\n\n".join(lines)
