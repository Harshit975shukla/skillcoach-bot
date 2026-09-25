"""Runs at 9 AM IST Mon-Fri. Sends daily lesson using pre-written content."""
import json
import base64 as b64lib
import os
import sys
import requests
from datetime import datetime, date, timedelta
import pytz

sys.path.insert(0, os.path.dirname(__file__))
from lesson_content import LESSONS, get_lesson, get_concept_diagrams

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
DASHBOARD = "https://harshit975shukla.github.io/skillcoach-dashboard"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"

RESOURCES = {
    "ec2": {
        "docs": "https://docs.aws.amazon.com/ec2/index.html",
        "video": "YouTube: 'AWS EC2 Tutorial' by TechWorld with Nana",
        "practice": "https://aws.amazon.com/getting-started/hands-on/launch-a-virtual-machine/",
        "cheatsheet": "https://digitalcloud.training/amazon-ec2/",
    },
    "vpc": {
        "docs": "https://docs.aws.amazon.com/vpc/index.html",
        "video": "YouTube: 'AWS VPC Beginner to Pro' by Stephane Maarek",
        "practice": "https://aws.amazon.com/getting-started/hands-on/build-vpc-web-server/",
        "cheatsheet": "https://digitalcloud.training/amazon-vpc/",
    },
    "iam": {
        "docs": "https://docs.aws.amazon.com/iam/index.html",
        "video": "YouTube: 'AWS IAM Tutorial' by Be A Better Dev",
        "practice": "https://aws.amazon.com/getting-started/hands-on/control-access-to-aws-resources/",
        "cheatsheet": "https://digitalcloud.training/aws-iam/",
    },
    "s3": {
        "docs": "https://docs.aws.amazon.com/s3/index.html",
        "video": "YouTube: 'Amazon S3 Tutorial' by TechWorld with Nana",
        "practice": "https://aws.amazon.com/getting-started/hands-on/backup-to-s3-cli/",
        "cheatsheet": "https://digitalcloud.training/amazon-s3/",
    },
    "rds": {
        "docs": "https://docs.aws.amazon.com/rds/index.html",
        "video": "YouTube: 'AWS RDS Tutorial' by Stephane Maarek",
        "practice": "https://aws.amazon.com/getting-started/hands-on/create-mysql-db/",
        "cheatsheet": "https://digitalcloud.training/amazon-rds/",
    },
    "lambda": {
        "docs": "https://docs.aws.amazon.com/lambda/index.html",
        "video": "YouTube: 'AWS Lambda Tutorial' by TechWorld with Nana",
        "practice": "https://aws.amazon.com/getting-started/hands-on/run-serverless-code/",
        "cheatsheet": "https://digitalcloud.training/aws-lambda/",
    },
    "kubernetes": {
        "docs": "https://kubernetes.io/docs/home/",
        "video": "YouTube: 'Kubernetes Tutorial for Beginners' by TechWorld with Nana",
        "practice": "https://killercoda.com/playgrounds/scenario/kubernetes",
        "cheatsheet": "https://kubernetes.io/docs/reference/kubectl/cheatsheet/",
    },
    "terraform": {
        "docs": "https://developer.hashicorp.com/terraform/docs",
        "video": "YouTube: 'Terraform Course' by TechWorld with Nana",
        "practice": "https://developer.hashicorp.com/terraform/tutorials",
        "cheatsheet": "https://spacelift.io/blog/terraform-cheatsheet",
    },
    "docker": {
        "docs": "https://docs.docker.com/",
        "video": "YouTube: 'Docker Tutorial for Beginners' by TechWorld with Nana",
        "practice": "https://labs.play-with-docker.com/",
        "cheatsheet": "https://dockerlabs.collabnix.com/docker/cheatsheet/",
    },
    "cicd": {
        "docs": "https://docs.github.com/en/actions",
        "video": "YouTube: 'CI/CD Pipeline Tutorial' by TechWorld with Nana",
        "practice": "https://github.com/skills/hello-github-actions",
        "cheatsheet": "https://www.jenkins.io/doc/book/",
    },
    "prometheus": {
        "docs": "https://prometheus.io/docs/introduction/overview/",
        "video": "YouTube: 'Prometheus Tutorial' by TechWorld with Nana",
        "practice": "https://killercoda.com/playgrounds/scenario/prometheus",
        "cheatsheet": "https://promlabs.com/promql-cheat-sheet/",
    },
    "genai": {
        "docs": "https://cloud.google.com/vertex-ai/docs",
        "video": "YouTube: 'LangChain Tutorial' by TechWorld with Nana",
        "practice": "https://ai.google.dev/gemini-api/docs/get-started/tutorial",
        "cheatsheet": "https://www.deeplearning.ai/short-courses/",
    },
}


def get_resources(topic):
    topic_lower = topic.lower()
    for key, res in RESOURCES.items():
        if key in topic_lower:
            return res
    return {
        "docs": "https://docs.aws.amazon.com/",
        "video": "YouTube: Search '" + topic.split(":")[0].strip() + " tutorial' by TechWorld with Nana",
        "practice": "https://killercoda.com/",
        "cheatsheet": "https://devhints.io/",
    }


def get_data():
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{FILE}", headers=GH, timeout=15)
    raw = r.json()
    return json.loads(b64lib.b64decode(raw["content"]).decode()), raw["sha"]


def push_data(data, sha, msg):
    content = b64lib.b64encode(json.dumps(data, indent=2).encode()).decode()
    requests.put(
        f"https://api.github.com/repos/{REPO}/contents/{FILE}",
        headers=GH,
        json={"message": msg, "content": content, "sha": sha},
        timeout=20,
    )


def _groq_call(prompt, max_tokens):
    import time
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    for attempt in range(3):
        r = requests.post(GROQ_URL, json=body, headers=headers, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        if r.status_code in (429, 503) and attempt < 2:
            time.sleep(30 + 15 * attempt)
            continue
        raise Exception(f"Groq {r.status_code}: {r.text[:200]}")
    raise Exception("Groq failed")


def _gemini_call(prompt, max_tokens):
    import time
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens}}
    for attempt in range(4):
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if r.status_code in (429, 503) and attempt < 3:
            time.sleep(60 + 30 * attempt)
            continue
        raise Exception(f"Gemini {r.status_code}: {r.text[:200]}")
    raise Exception("Gemini failed")


def ai(prompt, max_tokens=600):
    """Try Groq first (14,400 RPD free). Fall back to Gemini on failure."""
    if GROQ_API_KEY:
        try:
            return _groq_call(prompt, max_tokens)
        except Exception as e:
            print(f"Groq unavailable ({e}), falling back to Gemini")
    if GEMINI_API_KEY:
        return _gemini_call(prompt, max_tokens)
    raise Exception("No AI API key configured")


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4096]},
        timeout=10,
    )


def send_long(text):
    MAX = 4096
    if len(text) <= MAX:
        send(text)
        return
    remaining = text
    while len(remaining) > MAX:
        chunk = remaining[:MAX]
        split_pos = chunk.rfind("\n\n")
        if split_pos < 500:
            split_pos = chunk.rfind("\n")
        if split_pos < 100:
            split_pos = MAX
        send(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()
    if remaining:
        send(remaining)


# Pre-written Mermaid diagrams (always render correctly)
DIAGRAMS = {
    "rds": """flowchart TD
    App[Application] --> ALB[Load Balancer]
    ALB --> EC2a[EC2 App Server 1]
    ALB --> EC2b[EC2 App Server 2]
    EC2a --> RDS_P[(RDS Primary\nMulti-AZ)]
    EC2b --> RDS_P
    RDS_P -->|sync replication| RDS_S[(RDS Standby\nAZ-2)]
    RDS_P -->|async replication| RR1[(Read Replica\nRegion-1)]
    RDS_P --> S3[(S3 Auto Backups\n7-35 day retention)]
    CW[CloudWatch\nAlarms] --> RDS_P""",

    "s3": """flowchart LR
    Client[Client / App] --> API[S3 API]
    API --> Bucket[S3 Bucket]
    Bucket --> STD[Standard\nHot Data]
    Bucket --> IA[Standard-IA\nInfrequent Access]
    Bucket --> Glacier[Glacier\nArchive 90+ days]
    LC[Lifecycle Policy] -->|auto move| IA
    IA -->|auto move| Glacier
    Bucket --> VER[Versioning]
    Bucket --> BP[Bucket Policy\n+ IAM]
    BP --> KMS[KMS Encryption]""",

    "ec2": """flowchart TD
    User[User Request] --> R53[Route 53]
    R53 --> ALB[Application Load Balancer]
    ALB --> ASG[Auto Scaling Group]
    ASG --> EC2a[EC2 t3.medium\nAZ-1]
    ASG --> EC2b[EC2 t3.medium\nAZ-2]
    ASG --> EC2c[EC2 t3.medium\nAZ-3]
    EC2a --> EBS[(EBS Volume\ngp3 SSD)]
    EC2a --> RDS[(RDS DB)]
    CW[CloudWatch] -->|scale out| ASG
    SG[Security Group\nPort 443 only] --> ALB""",

    "vpc": """flowchart TD
    IGW[Internet Gateway] --> PubSub1[Public Subnet\nAZ-1 10.0.1.0/24]
    IGW --> PubSub2[Public Subnet\nAZ-2 10.0.2.0/24]
    PubSub1 --> NAT[NAT Gateway]
    PubSub1 --> ALB[Load Balancer]
    NAT --> PrivSub1[Private Subnet\nAZ-1 10.0.3.0/24]
    NAT --> PrivSub2[Private Subnet\nAZ-2 10.0.4.0/24]
    PrivSub1 --> EC2[EC2 App Servers]
    PrivSub2 --> RDS[(RDS Database)]
    NACL[Network ACL] --> PubSub1
    SG[Security Groups] --> EC2""",

    "iam": """flowchart TD
    User[IAM User] -->|assume| Role[IAM Role]
    Group[IAM Group] -->|has| Policy[IAM Policy]
    User -->|member of| Group
    Role -->|attached| Policy
    Policy -->|allow/deny| S3[S3 Bucket]
    Policy -->|allow/deny| EC2[EC2 Actions]
    Policy -->|allow/deny| RDS[RDS Actions]
    STS[STS Token Service] -->|temp credentials| Role
    SP[Service Principal\ne.g. Lambda] -->|assume| Role
    MFA[MFA Device] -->|required for| User""",

    "lambda": """flowchart LR
    Trigger[Event Trigger\nAPI GW / S3 / SQS] --> Lambda[Lambda Function\nNode/Python/Java]
    Lambda -->|read/write| DDB[(DynamoDB)]
    Lambda -->|send| SQS[SQS Queue]
    Lambda -->|store| S3[S3 Bucket]
    Lambda -->|call| ExtAPI[External API]
    CW[CloudWatch Logs] --> Lambda
    VPC[VPC Config\noptional] --> Lambda
    Role[Execution Role\nIAM] --> Lambda
    Concurrency[Reserved\nConcurrency] --> Lambda""",

    "kubernetes": """flowchart TD
    User[kubectl / CI-CD] --> API[API Server]
    API --> ETCD[(etcd\nCluster State)]
    API --> SCH[Scheduler]
    API --> CM[Controller Manager]
    SCH --> Node1[Worker Node 1]
    SCH --> Node2[Worker Node 2]
    Node1 --> Pod1[Pod\nApp Container]
    Node1 --> Pod2[Pod\nSidecar]
    Node2 --> Pod3[Pod\nReplica]
    SVC[Service\nClusterIP/LB] --> Pod1
    SVC --> Pod3
    Ingress[Ingress Controller] --> SVC""",

    "terraform": """flowchart TD
    Dev[Developer] -->|terraform plan| TF[Terraform Core]
    TF -->|read| State[State File\nS3 Backend]
    TF -->|lock| DDB[(DynamoDB\nState Lock)]
    TF -->|create/update| AWS[AWS Provider]
    AWS --> EC2[EC2 Resources]
    AWS --> VPC[VPC Resources]
    AWS --> RDS[RDS Resources]
    TF -->|plan output| PR[Code Review\nPR Approval]
    PR -->|terraform apply| TF
    TF -->|update| State""",

    "docker": """flowchart LR
    Dev[Developer] -->|docker build| Image[Docker Image]
    Image -->|docker push| Registry[Container Registry\nECR / DockerHub]
    Registry -->|docker pull| Host[Docker Host]
    Host --> C1[Container 1\nApp]
    Host --> C2[Container 2\nNginx]
    Host --> C3[Container 3\nRedis]
    C1 <-->|network| C2
    C1 <-->|network| C3
    Vol[(Docker Volume\nPersistent Data)] --> C1
    ENV[Env Vars\n.env / Secrets] --> C1""",

    "cicd": """flowchart LR
    Dev[Developer] -->|git push| GH[GitHub Repo]
    GH -->|webhook| CI[CI Runner\nGitHub Actions]
    CI --> Test[Run Tests]
    CI --> Lint[Code Lint]
    CI --> Build[Build Docker\nImage]
    Build -->|push| ECR[ECR Registry]
    ECR -->|deploy| ECS[ECS / EKS\nProduction]
    CI -->|notify| Slack[Slack Alert]
    Gate[Manual Approval\nProd Gate] --> ECS""",

    "prometheus": """flowchart TD
    Apps[App Instances] -->|/metrics endpoint| Prom[Prometheus Server]
    Prom -->|scrape every 15s| Apps
    Prom -->|store| TSDB[(Time Series DB\nLocal Storage)]
    Prom -->|evaluate| Rules[Alert Rules]
    Rules -->|fire| AM[Alertmanager]
    AM -->|route| Slack[Slack]
    AM -->|route| PD[PagerDuty]
    Grafana[Grafana Dashboard] -->|PromQL query| Prom
    SD[Service Discovery\nK8s / EC2] --> Prom""",

    "genai": """flowchart TD
    User[User Query] --> API[API Gateway]
    API --> Orch[Orchestrator\nLangChain / Custom]
    Orch --> Embed[Embedding Model]
    Embed --> VS[(Vector Store\nPinecone / OpenSearch)]
    VS -->|top-k docs| Orch
    Orch --> LLM[LLM\nClaude / GPT / Gemini]
    Orch --> Cache[Semantic Cache\nRedis]
    LLM --> Response[Response to User]
    Monitor[Observability\nPrompt logs + latency] --> LLM""",
}


def get_diagram_code(topic):
    topic_lower = topic.lower()
    for key, code in DIAGRAMS.items():
        if key in topic_lower:
            return code
    return None


def send_diagram(topic):
    """Send overall architecture diagram for the topic."""
    mermaid_code = get_diagram_code(topic)
    if not mermaid_code:
        try:
            prompt = "\n".join([
                "Write a simple Mermaid flowchart for: " + topic.split(":")[0].strip(),
                "STRICT RULES: start with 'flowchart TD', max 8 nodes, alphanumeric node names only, output Mermaid code only",
            ])
            mermaid_code = ai(prompt, 300)
            mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()
        except Exception:
            return
    send_mermaid_diagram(mermaid_code, "Full Architecture: " + topic.split(":")[0].strip())


def format_lesson_header(lesson, topic, day_name, today_str):
    """Header message: greeting + why + what."""
    lines = [
        "GOOD MORNING, HARSHIT! " + day_name + " | " + today_str,
        "Today: " + topic,
        "",
        "WHY THIS MATTERS FOR YOUR INTERVIEW",
        lesson["why"],
        "",
        "WHAT IS " + lesson["title"].split(":")[0].upper().strip() + "?",
        lesson["what"],
    ]
    return "\n".join(lines)


def format_concept(concept, num):
    """Single concept block."""
    return "CONCEPT " + str(num) + ": " + concept["name"] + "\n\n" + concept["body"]


def format_e2e(lesson):
    """End-to-end flow section."""
    lines = ["HOW IT WORKS END-TO-END", ""]
    lines += lesson["e2e"]
    lines += ["", "See the full architecture diagram above for the visual view."]
    return "\n".join(lines)


def send_mermaid_diagram(mermaid_code, caption):
    """Download from mermaid.ink and upload as file to Telegram."""
    try:
        encoded = b64lib.urlsafe_b64encode(mermaid_code.encode()).decode()
        diagram_url = f"https://mermaid.ink/img/{encoded}"
        img = requests.get(diagram_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if img.status_code != 200:
            print("mermaid.ink fetch failed:", img.status_code)
            return
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": ("diagram.jpg", img.content, img.headers.get("Content-Type", "image/jpeg"))},
            timeout=30,
        )
        if resp.status_code != 200:
            print("Diagram send failed:", resp.text[:100])
    except Exception as e:
        print("Diagram skipped:", e)


def format_tasks_and_terms(lesson):
    """Build Part 2 message (tasks + key terms) from pre-written content."""
    lines = ["HANDS-ON TASKS FOR TODAY", ""]
    for task in lesson["tasks"]:
        lines.append(task["name"])
        lines.append("Goal: " + task["goal"])
        for i, step in enumerate(task["steps"], 1):
            lines.append(str(i) + ". " + step)
        lines.append("")

    lines += ["KEY TERMS TO KNOW", ""]
    for term in lesson["key_terms"]:
        lines.append(term)

    return "\n".join(lines)


def generate_interview_qa(topic, profile_context=""):
    """One small Gemini call for a personalized interview Q&A."""
    prompt_parts = [
        "You are SkillCoach, a Cloud DevOps interview coach. Plain text only, no asterisks, no markdown.",
        "",
        "Write one Senior DevOps interview Q&A for the topic: " + topic,
    ]
    if profile_context:
        prompt_parts.append(profile_context)
    prompt_parts += [
        "",
        "INTERVIEW QUESTION & STRONG ANSWER",
        "Q: [A real scenario-based Senior DevOps interview question on " + topic.split(":")[0].strip() + "]",
        "",
        "A: [150-word model answer: include specific AWS limits/numbers, a real trade-off, what you did in production. Sound like a senior engineer who has operated this at scale.]",
        "",
        "WHAT MAKES THIS ANSWER STRONG:",
        "1. [specific reason]",
        "2. [specific reason]",
        "3. [specific reason]",
    ]
    return "\n".join(prompt_parts)


def generate_week_plan(data, sha, start_date):
    curriculum = data.get("curriculum", {})
    done_topics = list(curriculum.get("daily_lessons", {}).values())
    scores = data.get("weekly_scores", {})
    pref = data.get("next_week_preference", "")
    days = [(start_date + timedelta(days=i)).isoformat() for i in range(6)]

    prompt = "\n".join([
        "You are a Cloud DevOps curriculum planner. Return only valid JSON, no markdown.",
        "",
        "Create a 6-day Cloud DevOps learning plan for Harshit Shukla targeting Senior Cloud DevOps & AI Engineer.",
        "Topics already covered: " + (", ".join(done_topics) if done_topics else "None - first week"),
        "Past test scores: " + (json.dumps(scores) if scores else "No tests yet"),
        "User preference: " + (pref if pref else "Follow logical progression"),
        "",
        "Progression: No topics -> AWS Core (EC2, VPC, IAM, S3, RDS).",
        "AWS done -> Containers + Kubernetes. K8s done -> Terraform + CI/CD.",
        "CI/CD done -> Observability + SRE. All done -> GenAI/LLMOps + System Design.",
        "",
        "Return ONLY a JSON object:",
        "{",
        '  "' + days[0] + '": "Specific Topic: Sub-topic",',
        '  "' + days[1] + '": "Specific Topic: Sub-topic",',
        '  "' + days[2] + '": "Specific Topic: Sub-topic",',
        '  "' + days[3] + '": "Specific Topic: Sub-topic",',
        '  "' + days[4] + '": "Specific Topic: Sub-topic",',
        '  "' + days[5] + '": "Weekly Review: Practice Questions"',
        "}",
    ])

    result = ai(prompt, 400)
    try:
        plan = json.loads(result[result.find("{"):result.rfind("}") + 1])
    except Exception:
        topics = [
            "AWS EC2: Instance Types & Auto Scaling",
            "AWS VPC: Networking & Security Groups",
            "AWS IAM: Roles, Policies & Best Practices",
            "AWS S3: Storage Classes & Lifecycle",
            "AWS RDS: Multi-AZ & Read Replicas",
            "AWS Review: Practice Questions",
        ]
        plan = dict(zip(days, topics))

    curr = data.get("curriculum", {})
    curr.setdefault("week_plan", {}).update(plan)
    curr["week_number"] = curr.get("week_number", 0) + 1
    data["curriculum"] = curr
    data["next_week_preference"] = ""
    push_data(data, sha, "Week " + str(curr["week_number"]) + " plan generated")
    return plan


def main():
    data, sha = get_data()
    today = date.today()
    today_str = today.isoformat()
    day_name = datetime.now(IST).strftime("%A")

    curriculum = data.get("curriculum", {})
    week_plan = curriculum.get("week_plan", {})
    topic = week_plan.get(today_str)

    if not topic:
        send("Generating your learning plan for this week...")
        monday = today - timedelta(days=today.weekday())
        generate_week_plan(data, sha, monday)
        data, sha = get_data()
        topic = data.get("curriculum", {}).get("week_plan", {}).get(today_str)

    if not topic:
        send("No topic found for today (" + today_str + "). Use /learn <topic> to study manually.")
        return

    res = get_resources(topic)

    # Profile context for personalization
    profile = data.get("profile", {})
    profile_context = ""
    if profile.get("setup_complete") and profile.get("target_role"):
        profile_context = (
            "User's target role: " + profile.get("target_role", "") + ". "
            + "Strong skills: " + ", ".join(profile.get("strong_skills", [])[:5]) + ". "
            + "Gap skills to prioritize: " + ", ".join(profile.get("gap_skills", [])[:5]) + "."
        )

    # Look up pre-written lesson
    lesson = get_lesson(topic)

    if lesson:
        # --- PRE-WRITTEN PATH: zero API calls for core content ---
        print("Using pre-written lesson for:", topic)
        concept_diagrams = get_concept_diagrams(topic)

        # Header: greeting + why + what
        send_long(format_lesson_header(lesson, topic, day_name, today_str))

        # Each concept + its own diagram
        for i, concept in enumerate(lesson["concepts"]):
            send_long(format_concept(concept, i + 1))
            if i < len(concept_diagrams):
                send_mermaid_diagram(
                    concept_diagrams[i],
                    "Concept " + str(i + 1) + ": " + concept["name"]
                )

        # End-to-end flow + full architecture diagram
        send_long(format_e2e(lesson))
        send_diagram(topic)

        # Tasks + Key Terms (pre-written)
        part2 = format_tasks_and_terms(lesson)
        send_long(part2)

        # Interview Q&A: ONE small Gemini call (~500 tokens)
        try:
            qa_prompt = generate_interview_qa(topic, profile_context)
            qa_result = ai(qa_prompt, 500)
            send_long(qa_result)
        except Exception as e:
            print("Interview Q&A skipped (Gemini unavailable):", e)
            # Fallback: generic Q&A tip
            send(
                "INTERVIEW TIP\n\n"
                "Practice answering this aloud: 'Walk me through how " + topic.split(":")[0].strip()
                + " works in a production environment you have managed. "
                "What would you do differently now?'\n\n"
                "Aim for a 3-minute structured answer: context, decision, outcome."
            )

    else:
        # --- FALLBACK: Gemini-generated lesson for unknown topics ---
        print("No pre-written lesson for:", topic, "- using Gemini fallback")

        base_ctx = "\n".join([
            "You are SkillCoach, expert Cloud DevOps & AI Engineer coach for Harshit Shukla (Senior level target).",
            "Be THOROUGH and specific. Plain text only - no asterisks, no hashtags, no markdown.",
            *(([profile_context]) if profile_context else []),
        ])

        part1_prompt = "\n".join([
            base_ctx, "",
            "Write PART 1 of today's lesson on: " + topic, "",
            "GOOD MORNING, HARSHIT! " + day_name + " | " + today_str,
            "Today: " + topic, "",
            "WHY THIS MATTERS FOR YOUR INTERVIEW",
            "[2-3 sentences]", "",
            "WHAT IS " + topic.split(":")[0].upper().strip() + "?",
            "[3-4 sentences]", "",
            "CONCEPT 1: [name]",
            "[5-6 sentences with real numbers and interview traps]", "",
            "CONCEPT 2: [name]", "[5-6 sentences]", "",
            "CONCEPT 3: [name]", "[5-6 sentences]", "",
            "CONCEPT 4: [advanced/cross-service]", "[5-6 sentences]", "",
            "HOW IT WORKS END-TO-END",
            "[6-8 numbered steps]",
            "[End with: See the architecture diagram below for the visual view.]",
        ])

        part2_prompt = "\n".join([
            base_ctx, "",
            "Write PART 2 of today's lesson on: " + topic, "",
            "HANDS-ON TASKS FOR TODAY", "",
            "Task 1 (20 min): [specific AWS Console or CLI task]",
            "Goal: [what you will learn]",
            "Steps: 1.[step] 2.[step] 3.[step] 4.[step]", "",
            "Task 2 (15 min): [doc or video task]",
            "Goal: [what you will learn]",
            "Steps: 1.[step] 2.[step]", "",
            "Task 3 (20 min): [interview answer practice]",
            "Goal: [what you will practice]",
            "Steps: 1.[step] 2.[step] 3.[step]", "",
            "INTERVIEW QUESTION & STRONG ANSWER",
            "Q: [A real Senior DevOps scenario-based question on " + topic + "]", "",
            "A: [200-word model answer with specific AWS limits/numbers, production experience]", "",
            "WHAT MAKES THIS ANSWER STRONG:",
            "1. [specific reason]",
            "2. [specific reason]",
            "3. [specific reason]", "",
            "KEY TERMS TO USE IN YOUR ANSWER",
            "[10 terms, one per line, each with a 1-sentence explanation]",
        ])

        part1 = ai(part1_prompt, 1800)
        send_long(part1)
        send_diagram(topic)
        part2 = ai(part2_prompt, 1600)
        send_long(part2)

    # Resources footer (always sent)
    resources_msg = "\n".join([
        "RESOURCES: " + topic.split(":")[0].strip(),
        "",
        "Official Docs: " + res["docs"],
        "Video Tutorial: " + res["video"],
        "Hands-on Lab: " + res["practice"],
        "Cheat Sheet: " + res["cheatsheet"],
        "",
        "Evening quiz at 6 PM IST - 5 questions on today's topic!",
        "Use /ask <question> anytime for doubts.",
        "",
        "Dashboard: " + DASHBOARD,
    ])
    send(resources_msg)

    # Update curriculum state
    curr = data.get("curriculum", {})
    curr.setdefault("daily_lessons", {})[today_str] = topic
    curr["last_topic"] = topic
    data["curriculum"] = curr
    data["last_updated"] = datetime.now(IST).isoformat()
    push_data(data, sha, "Morning lesson: " + topic)
    print("Lesson sent:", topic)


if __name__ == "__main__":
    main()
