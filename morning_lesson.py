"""Runs at 9 AM IST Mon-Fri. Generates and sends daily lesson."""
import json
import base64 as b64lib
import os
import requests
from datetime import datetime, date, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

IST = pytz.timezone("Asia/Kolkata")
REPO = "Harshit975shukla/skillcoach-dashboard"
FILE = "docs/data.json"
GH = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
DASHBOARD = "https://harshit975shukla.github.io/skillcoach-dashboard"
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


def gemini(prompt, max_tokens=1800):
    import time
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    # 6 attempts: sleep 60, 90, 120, 150, 180s between retries on 503/429
    for attempt in range(6):
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if r.status_code in (429, 503) and attempt < 5:
            wait = 60 + 30 * attempt
            print(f"Gemini {r.status_code}, retrying in {wait}s (attempt {attempt+1}/6)")
            time.sleep(wait)
            continue
        raise Exception(f"Gemini {r.status_code}: {r.text[:300]}")
    raise Exception("Gemini failed after 6 attempts")


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4096]},
        timeout=10,
    )


def send_long(text):
    """Send long text splitting only at paragraph boundaries (double newline)."""
    MAX = 4096
    if len(text) <= MAX:
        send(text)
        return
    parts = []
    remaining = text
    while len(remaining) > MAX:
        # Find best split point: last double-newline before limit
        chunk = remaining[:MAX]
        split_pos = chunk.rfind("\n\n")
        if split_pos < 500:
            split_pos = chunk.rfind("\n")
        if split_pos < 100:
            split_pos = MAX
        parts.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()
    if remaining:
        parts.append(remaining)
    for part in parts:
        if part:
            send(part)


# Pre-written, validated Mermaid diagrams per topic — always render correctly
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
    """Send architecture diagram using pre-written Mermaid code (always renders correctly)."""
    mermaid_code = get_diagram_code(topic)
    if not mermaid_code:
        # Fallback: ask Gemini but with very strict simple format
        try:
            prompt = "\n".join([
                "Write a simple Mermaid flowchart for: " + topic.split(":")[0].strip(),
                "STRICT RULES:",
                "- Start with exactly: flowchart TD",
                "- Max 8 nodes",
                "- Node names: letters and numbers ONLY, no spaces, no special chars",
                "- Use quotes for labels: A[\"Label Text\"]",
                "- Output ONLY the Mermaid code, nothing else",
            ])
            mermaid_code = gemini(prompt, 300)
            mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()
        except Exception:
            return

    try:
        encoded = b64lib.urlsafe_b64encode(mermaid_code.encode()).decode()
        diagram_url = f"https://mermaid.ink/img/{encoded}"
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            json={
                "chat_id": CHAT_ID,
                "photo": diagram_url,
                "caption": "Architecture Diagram: " + topic.split(":")[0].strip(),
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print("Diagram send failed:", resp.text[:100])
    except Exception as e:
        print("Diagram skipped:", e)


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

    result = gemini(prompt, 400)
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

    # Build profile context if user has set up their profile
    profile = data.get("profile", {})
    profile_context = ""
    if profile.get("setup_complete") and profile.get("target_role"):
        profile_context = (
            "User's target role: " + profile.get("target_role", "") + ". "
            + "Strong skills (can go lighter on these): " + ", ".join(profile.get("strong_skills", [])[:5]) + ". "
            + "Gap skills (prioritize these): " + ", ".join(profile.get("gap_skills", [])[:5]) + "."
        )

    base_ctx = "\n".join([
        "You are SkillCoach, expert Cloud DevOps & AI Engineer coach for Harshit Shukla (Senior level target).",
        "Be THOROUGH and specific. Plain text only — no asterisks, no hashtags, no markdown.",
        *(([profile_context]) if profile_context else []),
    ])

    # --- PART 1: Concepts + Architecture (sent before diagram) ---
    part1_prompt = "\n".join([
        base_ctx,
        "",
        "Write PART 1 of today's lesson on: " + topic,
        "",
        "GOOD MORNING, HARSHIT! " + day_name + " | " + today_str,
        "Today: " + topic,
        "",
        "WHY THIS MATTERS FOR YOUR INTERVIEW",
        "[2-3 sentences: what Senior DevOps interviewers test, which companies ask this most]",
        "",
        "WHAT IS " + topic.split(":")[0].upper().strip() + "?",
        "[3-4 sentences: precise definition, the problem it solves, how it fits in the ecosystem]",
        "",
        "CONCEPT 1: [name]",
        "[5-6 sentences: what it is, how it works step-by-step internally, real example with numbers, interview trap]",
        "",
        "CONCEPT 2: [name]",
        "[5-6 sentences: definition, when to use vs avoid, what breaks when misconfigured, cost/perf impact]",
        "",
        "CONCEPT 3: [name]",
        "[5-6 sentences: how it differs from alternatives, security angle, best practices, exam gotcha]",
        "",
        "CONCEPT 4: [name - advanced or cross-service integration]",
        "[5-6 sentences: advanced use case, integration with other AWS services, thing most engineers miss]",
        "",
        "HOW IT WORKS END-TO-END",
        "[6-8 numbered steps walking through a complete real operation from start to finish]",
        "[End with: See the architecture diagram below for the visual view.]",
    ])

    # --- PART 2: Tasks + Interview Q&A (sent after diagram) ---
    part2_prompt = "\n".join([
        base_ctx,
        "",
        "Write PART 2 of today's lesson on: " + topic,
        "",
        "HANDS-ON TASKS FOR TODAY",
        "",
        "Task 1 (20 min): [specific actionable task with AWS Console or CLI]",
        "Goal: [what you will learn]",
        "Steps: 1.[step] 2.[step] 3.[step] 4.[step]",
        "",
        "Task 2 (15 min): [read specific doc section or watch specific video segment]",
        "Goal: [what you will learn]",
        "Steps: 1.[step] 2.[step]",
        "",
        "Task 3 (20 min): [write out your interview answer practice]",
        "Goal: [what you will practice]",
        "Steps: 1.[step] 2.[step] 3.[step]",
        "",
        "INTERVIEW QUESTION & STRONG ANSWER",
        "Q: [A real Senior DevOps scenario-based interview question on " + topic + "]",
        "",
        "A: [200-word model answer: include specific AWS limits/numbers, a real trade-off decision, what you did in production. Sound like a senior engineer who has actually operated this at scale.]",
        "",
        "WHAT MAKES THIS ANSWER STRONG:",
        "1. [specific reason]",
        "2. [specific reason]",
        "3. [specific reason]",
        "",
        "KEY TERMS TO USE IN YOUR ANSWER",
        "[10 technical terms, one per line, each with a 1-sentence explanation of what it means]",
    ])

    part1 = gemini(part1_prompt, 1800)
    send_long(part1)

    # Diagram (pre-written, always renders)
    send_diagram(topic)

    part2 = gemini(part2_prompt, 1600)
    send_long(part2)

    # Resources
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
