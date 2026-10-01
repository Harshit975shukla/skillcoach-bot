// Synthetic private-dashboard fixtures shared by the Telegram and web dashboard browser tests.
// No real learner, email or credential is used.
import { execFileSync } from "node:child_process";

export const LAB_TOKEN = "SC-TEST-TOKN";
export const LESSON_ID = "0123456789abcdef0123";
export const MISSING_LESSON = "fedcba9876543210fedc";
export const spans = text => [{t: "text", v: text}];
export const resources = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from skillcoach.resources import library_view; print(json.dumps(library_view()))"],
  {encoding: "utf8"}));
export const courses = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from skillcoach.course_library import index, page; from skillcoach.catalog import TOPICS; " +
   "topic=next(k for k in TOPICS if k.startswith('linux/')); print(json.dumps({'index':index(),'lesson':page(topic)}))"],
  {encoding: "utf8", maxBuffer: 2 * 1024 * 1024}));
// Real server-side shapes: the certification view and capstone briefs come from the Python modules.
export const growth = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from datetime import datetime; from skillcoach.models import State; " +
   "from skillcoach.certifications import cert_view; from skillcoach.capstones import CAPSTONES; " +
   "from skillcoach.timeutil import IST; " +
   "print(json.dumps({'certification': cert_view(State(cert_track='cka'), datetime(2026, 9, 29, 10, tzinfo=IST)), " +
   "'capstones': [{'id': c.id, 'title': c.title, 'hours': c.hours, 'goal': c.goal, 'status': 'not_started', " +
   "'verified_at': None} for c in CAPSTONES.values()]}))"],
  {encoding: "utf8"}));
Object.assign(growth.certification.track.domains[0], {practice_answers: 10, practice_accuracy: 90, label: "Strong in practice"});
Object.assign(growth.certification.track.domains[1], {practice_answers: 5, practice_accuracy: 40, label: "Needs work"});
Object.assign(growth.certification.track, {overall: 65, covered_domains: 2});
Object.assign(growth.capstones[0], {status: "verified", verified_at: "2026-09-27T10:00:00+05:30"});
Object.assign(growth.capstones[1], {status: "needs_fix", title: "<img src=x onerror='window.pwnedCapstone=true'>"});
export const lessonFixture = {
  id: LESSON_ID, title: "CI pipeline design: stages, artifacts and caching", date: "2026-09-29", available: true,
  review: "Reviewed lesson · 2026-09-28",
  sections: [
    {heading: "Why it matters", blocks: [{type: "p", spans: [{t: "text", v: "Build once, "}, {t: "b", v: "promote"},
      {t: "text", v: " the same artifact.\nSecond line keeps its break."}]}]},
    {heading: "1. Artifacts", blocks: [
      {type: "p", spans: [{t: "text", v: "Use "}, {t: "code", v: "actions/upload-artifact@v7"},
        {t: "text", v: " <img src=x onerror='window.pwnedLesson=true'>"}]},
      {type: "code", lang: "yaml", text: "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo " + "long-line-".repeat(30)},
      {type: "ol", start: 3, items: [spans("Third step"), spans("Fourth step")]},
    ]},
  ],
  exercises: [
    {id: "task-open-1", title: "Build the artifact once", minutes: 8, status: "pending",
      blocks: [{type: "p", spans: [{t: "b", v: "Goal:"}, {t: "text", v: " produce one checksummed artifact."}]}]},
    {id: "task-done-2", title: "Cache dependencies", minutes: 10, status: "done", blocks: [{type: "p", spans: spans("Key the cache.")}]},
  ],
  notes: [{heading: "Cleanup", blocks: [{type: "ul", start: 1, items: [spans("Delete the test repository.")]}]}],
  extension: [{title: "Matrix builds", minutes: 15, blocks: [{type: "p", spans: spans("Optional.")}]}],
  interview: {question: [{type: "p", spans: spans("How would you guarantee the tested artifact is the deployed one?")}],
              points: [[{type: "p", spans: spans("Build once and pass the artifact.")}], [{type: "p", spans: spans("Verify a checksum.")}]]},
  references: ["https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts",
               "javascript:window.pwnedLesson=true"],
  feedback: "up", generated_at: new Date().toISOString(),
  resources: resources.items.filter(r => r.id === "github-actions"),
};
export const fixture = {
  resources,
  courses: courses.index,
  profile: {name: "Synthetic learner", target_role: "Platform engineer", level: "intermediate", setup_complete: true},
  stats: {done: 4, pending: 2, total: 6, streak: 2, minutes_practiced: 65, answers_graded: 1},
  preferences: {paused: false, media: "video"},
  tasks: [
    {id: "test-task-1", title: "Explain health-based traffic routing", skill: "AWS EC2", estimated_minutes: 20,
      assigned_date: "2026-09-26", detail: "Sketch two availability zones.\nExplain how healthy capacity handles requests.",
      detail_blocks: [{type: "p", spans: [{t: "b", v: "Goal:"}, {t: "text", v: " explain routing."}]},
                      {type: "ol", start: 1, items: [spans("Sketch two availability zones.")]}]},
    {id: "test-task-2", title: "Trace a Kubernetes readiness failure", skill: "Kubernetes networking",
      estimated_minutes: 15, assigned_date: "2026-09-26", detail: "Compare pod readiness and liveness."},
    {id: "c".repeat(20), title: "Older optional practice", skill: "Linux", estimated_minutes: 10,
      assigned_date: "2026-09-10", detail: "Review permissions.", earlier: true},
  ],
  progress: {study_days_week: 2, weekly_goal: 4, streak: 3, questions_answered: 10, accuracy: 60,
    lessons_delivered: 3, lessons_understood: 2, exercises_done: 4, labs_verified: 0,
    reviews_answered: 4, review_accuracy: 75, review_due: 2},
  mastery: {summary: {total: 199, started: 3, solid: 1, needs_review: 1},
    states: {[courses.index.modules.find(m => m.id === "linux").topics[0].id]: {state: "needs_review", label: "Needs review"}},
    next: {id: courses.index.modules.find(m => m.id === "linux").topics[0].id,
      title: courses.index.modules.find(m => m.id === "linux").topics[0].title, reason: "Review what slipped"}},
  today: {date: "2026-09-29", catch_up: 2, review_due: 2,
    lesson: {id: LESSON_ID, topic: "CI pipeline design", date: "2026-09-29", delivered: true, today: true, understood: false},
    quiz: {id: LESSON_ID, title: "CI pipeline quiz", date: "2026-09-29", status: "in_progress", answered: 2, total: 5,
      score: null, can_resume: true, deadline: "2026-10-05T00:00:00+05:30"},
    exercises: [{id: "test-task-1", title: "Explain health-based traffic routing", minutes: 20, status: "done"},
                {id: "test-task-2", title: "Trace a Kubernetes readiness failure", minutes: 15, status: "pending"}],
    next: {kind: "quiz", text: "Finish the quiz for “CI pipeline design” (2/5)", callback: "quiz:" + LESSON_ID,
      start: "quiz_" + LESSON_ID, lesson: LESSON_ID}},
  lessons: [{id: LESSON_ID, topic: "CI pipeline design", date: "2026-09-29", delivered: true},
            {id: MISSING_LESSON, topic: "Kubernetes pods", date: "2026-09-28", delivered: false}],
  quizzes: [
    {id: LESSON_ID, title: "CI pipeline quiz", date: "2026-09-29", status: "in_progress",
      answered: 2, total: 5, score: null, can_resume: true, deadline: "2026-10-05T00:00:00+05:30"},
    {id: "2026-09-28", title: "Terraform quiz", date: "2026-09-28", status: "not_started",
      answered: 0, total: 5, score: null, can_resume: true, deadline: "2026-10-05T00:00:00+05:30"},
    {id: "a".repeat(20), title: "Completed quiz", date: "2026-09-25", status: "completed",
      answered: 5, total: 5, score: 4, can_resume: false, deadline: "2026-09-28T00:00:00+05:30"},
    {id: "b".repeat(20), title: "<img src=x onerror='window.pwnedQuiz=true'>", date: "2026-09-24", status: "expired",
      answered: 1, total: 5, score: null, can_resume: false, deadline: "2026-09-28T00:00:00+05:30"},
  ],
  plan: [{date: "2026-09-28", topic: "AWS EC2: instance health and replacement"},
         {date: "2026-09-29", topic: "Kubernetes: readiness and service routing"}],
  skills: [{skill: "AWS EC2", done: 3, total: 4}, {skill: "Kubernetes networking", done: 1, total: 2}],
  recent_interviews: [{question: "How would you diagnose an unhealthy web target?", score: 7,
                       feedback: "Separate instance status from application health."}],
  generated_at: new Date().toISOString(), auth_expires_at: Math.floor(Date.now() / 1000) + 300, private: true,
  bot_url: "https://t.me/SkillCoachTestBot",
  document_csrf: "synthetic-csrf",
  documents: {resume_saved: false, jd_saved: false, can_update: true},
  learning: {stage: "ready", shared: true, plan: {id: "private-plan", version: 1, approved: false, minutes: 30,
    rationale: "Your initial diagnostic supports practice on the fundamentals.",
    sessions: [{day: 1, date: "2026-09-28", topic: "AWS EC2", objective: "Explain health checks", practice: "Draw the flow"}]}},
  labs: {
    enabled: true, template_repo: "synthetic/skillcoach-labs",
    cost_note: "Scenario and code labs are free. Your own AWS account is optional and may cost money.",
    gate: {blocked: true, waiting_since: "2026-10-04T10:00:00+05:30", required_pending: 1},
    carry_available: true,
    items: [
      {id: "lab-synthetic-1", lab_id: "s3-private-presigned", title: "Private S3 object with a presigned link",
        goal: "Serve a private object only through a short-lived presigned URL.", minutes: 30, required: true,
        blocking: true, carried: false, status: "needs_fix", reason: "The link did not return your token.",
        token: LAB_TOKEN, assigned_date: "2026-09-28", verified_at: null, verified_route: null, cleanup: null,
        routes: [
          {route: "scenario", label: "In-app scenario", steps: [], cleanup: [], submit: "", accepts_link: false},
          {route: "code", label: "Code lab (GitHub)", steps: ["Create a repository from the template."], cleanup: [],
            submit: "/submitlab s3-private-presigned https://github.com/<you>/<repository>", accepts_link: true},
          {route: "aws", label: "Your own AWS account", steps: ["Create a private bucket."],
            cleanup: ["Delete the object and bucket."], submit: "/submitlab s3-private-presigned <presigned link>",
            accepts_link: true},
          {route: "local", label: "Practice locally (free, self-checked)", steps: ["Create a scratch folder."],
            cleanup: ["Delete the scratch folder."], submit: "", accepts_link: false},
        ],
        resources: resources.items.filter(r => r.id === "aws-s3-guide"),
        references: ["https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html",
                     "javascript:window.pwnedLab=true"]},
      {id: "lab-synthetic-2", lab_id: "iam-least-privilege", title: "<img src=x onerror='window.pwnedLab=true'>",
        goal: "Scope a policy to one action.", minutes: 25, required: false, blocking: false, carried: false,
        status: "verified", reason: null, token: null, assigned_date: "2026-09-21",
        verified_at: "2026-09-22T10:00:00+05:30", verified_route: "Code lab (GitHub)", cleanup: null, routes: [],
        references: []},
    ],
    catalog: [
      {lab_id: "s3-private-presigned", title: "Private S3 object", minutes: 30, routes: ["scenario", "code", "aws"]},
      {lab_id: "iam-least-privilege", title: "IAM least privilege", minutes: 25, routes: ["scenario", "code"]},
      {lab_id: "vpc-subnet-routing", title: "VPC subnet routing", minutes: 30, routes: ["scenario", "code"]},
    ],
  },
  certification: growth.certification,
  capstones: growth.capstones,
  portfolio: {enabled: true, path: "/portfolio/Ab3dEfGh1jKlMn0p"},
};
