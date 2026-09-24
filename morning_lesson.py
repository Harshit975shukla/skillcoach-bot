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

# Curated resources per topic keyword
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
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=body, timeout=90)
    if r.status_code != 200:
        raise Exception(f"Gemini {r.status_code}: {r.text[:300]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4096]},
        timeout=10,
    )


def send_diagram(topic):
    """Generate Mermaid diagram via Gemini and send as image via mermaid.ink."""
    try:
        mermaid_prompt = "\n".join([
            "Generate a simple Mermaid architecture diagram for: " + topic,
            "Rules:",
            "- Use 'flowchart TD' or 'graph LR' format",
            "- Max 8 nodes, keep it simple and clear",
            "- Show how the components connect/interact",
            "- Return ONLY the Mermaid code, no explanation, no markdown fences",
            "Example format:",
            "flowchart TD",
            "    A[Client] --> B[Load Balancer]",
            "    B --> C[EC2 Instance 1]",
            "    B --> D[EC2 Instance 2]",
        ])
        mermaid_code = gemini(mermaid_prompt, 300)

        # Clean up - remove markdown fences if present
        mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()

        # Encode for mermaid.ink
        encoded = b64lib.urlsafe_b64encode(mermaid_code.encode()).decode()
        diagram_url = f"https://mermaid.ink/img/{encoded}"

        # Send as photo
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
            # Fallback: send diagram as text
            send("Architecture Overview:\n\n" + mermaid_code)
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

    # --- Message 1: Core Concepts ---
    msg1_prompt = "\n".join([
        "You are SkillCoach, an expert Cloud DevOps & AI Engineer interview coach for Harshit Shukla (targeting Senior level).",
        "Be thorough, specific, and interview-focused. Plain text only, no markdown symbols.",
        "",
        "Write Part 1 of today's lesson for " + day_name + " on: " + topic,
        "",
        "Format exactly:",
        "",
        "GOOD MORNING, HARSHIT! " + day_name + ", " + today_str,
        "Topic: " + topic,
        "",
        "WHY THIS MATTERS FOR YOUR INTERVIEW",
        "[2 sentences on why interviewers ask about this topic and what they look for]",
        "",
        "CONCEPT 1: [Name]",
        "[4-5 sentences: what it is, how it works internally, when to use it, common pitfalls]",
        "",
        "CONCEPT 2: [Name]",
        "[4-5 sentences: what it is, how it works, real-world use case, interview angle]",
        "",
        "CONCEPT 3: [Name]",
        "[4-5 sentences: what it is, how it differs from alternatives, when NOT to use it]",
        "",
        "KEY TERMS TO USE IN YOUR ANSWER",
        "[List 6-8 specific technical terms interviewers love to hear, one per line]",
    ])

    # --- Message 2: Tasks + Interview Q&A ---
    msg2_prompt = "\n".join([
        "You are SkillCoach, an expert Cloud DevOps & AI Engineer interview coach for Harshit Shukla.",
        "Plain text only.",
        "",
        "Write Part 2 of today's lesson on: " + topic,
        "",
        "Format exactly:",
        "",
        "HANDS-ON TASKS FOR TODAY",
        "",
        "Task 1 (20 min): [Specific actionable task name]",
        "Goal: [What you will learn from doing this]",
        "Steps:",
        "  1. [Specific step]",
        "  2. [Specific step]",
        "  3. [Specific step]",
        "",
        "Task 2 (15 min): [Reading/watching task]",
        "Goal: [What you will learn]",
        "Steps:",
        "  1. [Specific step]",
        "  2. [Specific step]",
        "",
        "Task 3 (20 min): [Interview prep task - write out your answer]",
        "Goal: [What you will practice]",
        "Steps:",
        "  1. [Specific step]",
        "  2. [Specific step]",
        "  3. [Specific step]",
        "",
        "COMMON INTERVIEW QUESTION",
        "Q: [A real, commonly-asked interview question on " + topic + "]",
        "",
        "STRONG ANSWER:",
        "[A model 150-word answer that would impress a senior interviewer. Include specific details, numbers, and real-world context]",
        "",
        "WHAT MAKES THIS ANSWER STRONG:",
        "[2-3 bullets explaining why this answer works]",
    ])

    msg1 = gemini(msg1_prompt, 1200)
    send(msg1)

    # Send diagram
    send_diagram(topic)

    msg2 = gemini(msg2_prompt, 1200)
    send(msg2)

    # --- Message 3: Resources ---
    resources_msg = "\n".join([
        "RESOURCES: " + topic.split(":")[0].strip(),
        "",
        "Official Docs:",
        res["docs"],
        "",
        "Video Tutorial:",
        res["video"],
        "",
        "Hands-on Practice:",
        res["practice"],
        "",
        "Cheat Sheet:",
        res["cheatsheet"],
        "",
        "Evening quiz at 6 PM IST on this topic!",
        "Use /ask <question> if you have doubts now.",
        "",
        DASHBOARD,
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
