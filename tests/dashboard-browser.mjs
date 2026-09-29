import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile, mkdtemp, writeFile, rm, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import puppeteer from "puppeteer";

let denied = false;
let uploadPreviews = 0, uploadConfirms = 0, dataRequests = 0, labFailOnce = false, lessonRequests = 0, lessonDenied = false;
const labSubmits = [];
const LAB_TOKEN = "SC-TEST-TOKN";
const LESSON_ID = "0123456789abcdef0123";
const MISSING_LESSON = "fedcba9876543210fedc";
const spans = text => [{t: "text", v: text}];
const resources = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from skillcoach.resources import library_view; print(json.dumps(library_view()))"],
  {encoding: "utf8"}));
const lessonFixture = {
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
const fixture = {
  resources,
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
  ],
  lessons: [{id: LESSON_ID, topic: "CI pipeline design", date: "2026-09-29", delivered: true},
            {id: MISSING_LESSON, topic: "Kubernetes pods", date: "2026-09-28", delivered: false}],
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
};
const server = createServer(async (request, response) => {
  if (request.url === "/app/labs/submit") {
    assert.equal(request.method, "POST");
    assert.equal(request.headers["x-csrf-token"], "synthetic-csrf");
    assert.equal(request.headers["x-telegram-init-data"], "synthetic-signed-launch");
    assert.equal(request.headers.cookie, undefined);
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    assert.deepEqual(Object.keys(body).sort(), ["assignment_id", "request_id", "url"]);
    assert.match(body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    labSubmits.push(body);
    const fail = labFailOnce; labFailOnce = false;
    response.writeHead(fail ? 503 : 200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(fail ? {error: "The check could not start right now."} : {queued: true, duplicate: false}));
    return;
  }
  if (request.url.startsWith("/app/documents/")) {
    assert.equal(request.headers["x-csrf-token"], "synthetic-csrf");
    assert.equal(request.headers["x-telegram-init-data"], "synthetic-signed-launch");
    assert.equal(request.headers.cookie, undefined);
    let raw = ""; for await (const chunk of request) raw += chunk;
    response.writeHead(200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    if (request.url.endsWith("/preview")) {
      uploadPreviews++;
      response.end(JSON.stringify({request_id: "synthetic-id", confirmation: "synthetic-token",
        characters: 150, kind: "resume", can_revise: true, status: "ready"}));
    } else {
      uploadConfirms++;
      const body = JSON.parse(raw);
      assert.equal(body.confirmation, "synthetic-token");
      response.end(JSON.stringify({queued: body.choice !== "cancel", cancelled: body.choice === "cancel"}));
    }
    return;
  }
  if (request.url === "/app/data") {
    dataRequests++;
    response.writeHead(denied ? 403 : 200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(denied ? {error: "Access was revoked. Reopen from Telegram."} : fixture));
    return;
  }
  if (request.url === "/app/lesson") {
    assert.equal(request.method, "POST");
    assert.equal(request.headers.cookie, undefined);
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    assert.deepEqual(Object.keys(body).sort(), ["init_data", "lesson"]);
    lessonRequests++;
    const [status, payload] = lessonDenied ? [403, {error: "Access was revoked. Reopen from Telegram."}]
      : body.lesson === LESSON_ID ? [200, {lesson: lessonFixture, auth_expires_at: fixture.auth_expires_at, private: true}]
      : [404, {error: "This lesson is not in your learning history."}];
    response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(payload));
    return;
  }
  const names = {"/app": ["dashboard.html", "text/html"], "/static/dashboard.css": ["dashboard.css", "text/css"],
                 "/static/dashboard.js": ["dashboard.js", "text/javascript"]};
  const selected = names[request.url.split("?")[0]];
  if (!selected) { response.writeHead(404).end(); return; }
  response.writeHead(200, {"Content-Type": selected[1]});
  response.end(await readFile(join("skillcoach", "static", selected[0])));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  headless: true, args: process.platform === "linux" ? ["--no-sandbox"] : [],
});
const uploadFolder = await mkdtemp(join(tmpdir(), "skillcoach-upload-test-"));
const uploadPath = join(uploadFolder, "synthetic-resume.txt");
await writeFile(uploadPath, "Synthetic experience, projects and skills. ".repeat(5));
try {
  for (const [label, width] of [["mobile", 390], ["desktop", 1100]]) {
    const page = await browser.newPage();
    await page.setViewport({width, height: 900, deviceScaleFactor: 1});
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) {
        request.respond({status: 200, contentType: "text/javascript", body:
          "window.Telegram={WebApp:{initData:'synthetic-signed-launch',colorScheme:'light',ready(){},expand(){},onEvent(){}}};"});
      } else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.goto(origin + "/app");
    await page.waitForFunction(() => !document.getElementById("content").hidden);
    assert.equal(await page.$eval("#learner-name", e => e.textContent), "Synthetic learner");
    assert.equal(await page.$$eval("#tasks > li", e => e.length), 2);
    assert.match(await page.$eval("#plan-status", e => e.textContent), /Awaiting your approval/);
    assert.equal(await page.$eval("#plan-bot-link", e => e.href), "https://t.me/SkillCoachTestBot?start=plan");
    assert.equal(await page.evaluate(() => document.body.classList.contains("telegram-light")), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.equal(await page.$$eval("#resource-list > li", e => e.length), 6);
    await page.click("#resource-more");
    assert.equal(await page.$$eval("#resource-list > li", e => e.length), 12);
    const requestsBeforeSearch = dataRequests;
    await page.type("#resource-search", "terraform");
    assert.equal(await page.$$eval("#resource-list > li", e => e.length), 1);
    assert.match(await page.$eval("#resource-list", e => e.textContent), /local Docker/i);
    assert.equal(await page.$eval("#resource-more", e => e.hidden), true);
    await page.$eval("#resource-search", e => { e.value = "no-match-secret"; e.dispatchEvent(new Event("input")); });
    assert.match(await page.$eval("#resource-list", e => e.textContent), /No matching resources/);
    await page.$eval("#resource-search", e => { e.value = ""; e.dispatchEvent(new Event("input")); });
    await page.select("#resource-group", "linux");
    await page.click("#resource-no-account");
    assert.match(await page.$eval("#resource-count", e => e.textContent), /6 of 6/);
    assert.equal(await page.$eval("#resource-list", e => e.textContent.includes("Killercoda")), false);
    assert.equal(dataRequests, requestsBeforeSearch, "resource filtering makes no API or AI call");
    assert.equal(await page.$$eval("#resource-list a", links => links.every(a =>
      a.target === "_blank" && a.rel.includes("noreferrer") && a.referrerPolicy === "no-referrer"
      && !a.href.includes("synthetic-signed-launch"))), true);
    await page.$eval("#resources", e => e.scrollIntoView());
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `resources-${label}.png`)});
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `dashboard-${label}.png`), fullPage: true});
    }
    // Task details render the Markdown subset as elements, never as literal ** markers.
    assert.equal(await page.$eval("#tasks li:first-child details strong", e => e.textContent), "Goal:");
    assert.equal(await page.evaluate(() => document.getElementById("tasks").textContent.includes("**")), false);
    // Lesson page: open from the list, read every part, then return with nothing left behind.
    assert.equal(await page.$$eval("#lesson-list > li", e => e.length), 2);
    assert.match(await page.$eval("#lesson-list li:nth-child(2)", e => e.textContent), /still being delivered/);
    await page.click("#lesson-list > li:first-child button");
    await page.waitForFunction(() => !document.getElementById("lesson-page").hidden);
    assert.equal(await page.$eval("#content", e => e.hidden), true);
    assert.equal(await page.$eval("#lesson-title", e => e.textContent), lessonFixture.title);
    assert.match(await page.$eval("#lesson-meta", e => e.textContent), /Reviewed lesson/);
    assert.equal(await page.$eval("#lesson-body .prose strong", e => e.textContent), "promote");
    assert.match(await page.$eval("#lesson-body .prose p", e => getComputedStyle(e).whiteSpace), /pre-line/);
    assert.equal(await page.$eval("#lesson-body .code-block code", e => e.textContent.startsWith("jobs:\n  build:")), true);
    assert.equal(await page.$eval("#lesson-body ol[start]", e => e.start), 3);
    assert.equal(await page.evaluate(() => document.querySelectorAll("#lesson-body img").length), 0);
    assert.deepEqual(await page.$$eval("#lesson-exercises li code", e => e.map(c => c.textContent)), ["/complete task-open-1"]);
    assert.equal(await page.$$eval("#lesson-interview details li", e => e.length), 2);
    assert.equal(await page.$eval("#lesson-interview details", e => e.open), false);
    assert.deepEqual(await page.$$eval("#lesson-references a", e => e.map(a => a.href)), [lessonFixture.references[0]]);
    assert.deepEqual(await page.$$eval("#lesson-jump a", e => e.map(a => a.textContent)),
      ["Exercises", "Interview", "References", "Free resources"]);
    assert.equal(await page.$eval("#lesson-resources a", e => e.href), lessonFixture.resources[0].url);
    assert.match(await page.$eval("#lesson-resources", e => e.textContent), /not required practice/);
    assert.match(await page.$eval("#lesson-feedback", e => e.textContent), /“Useful”/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "code scrolls inside its block");
    assert.equal(await page.evaluate(() => window.pwnedLesson), undefined);
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `lesson-${label}.png`), fullPage: true});
    }
    await page.click("#lesson-back");
    assert.equal(await page.$eval("#lesson-view", e => e.hidden), true);
    assert.equal(await page.$eval("#content", e => e.hidden), false);
    assert.equal(await page.$eval("#lesson-body", e => e.children.length), 0);
    await page.click("#lesson-list > li:nth-child(2) button");
    await page.waitForFunction(() => document.getElementById("lesson-status").textContent.includes("not in your learning history"));
    assert.equal(await page.$eval("#lesson-page", e => e.hidden), true);
    await page.click("#lesson-back");
    assert.equal(await page.$eval("#content", e => e.hidden), false);
    await (await page.$("#document-file")).uploadFile(uploadPath);
    await page.click("#document-preview-button");
    await page.waitForFunction(() => !document.getElementById("document-preview").hidden);
    assert.equal(await page.$eval("#document-choice", e => e.value), "keep");
    const beforeConfirm = uploadConfirms;
    await page.$eval("#document-confirm", e => { e.click(); e.click(); });
    await page.waitForFunction(() => document.getElementById("document-status").textContent.includes("queued"));
    assert.equal(uploadConfirms, beforeConfirm + 1);
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    for (const step of ["preview", "confirm"]) {
      await (await page.$("#document-file")).uploadFile(uploadPath);
      if (step === "confirm") {
        await page.click("#document-preview-button");
        await page.waitForFunction(() => !document.getElementById("document-preview").hidden);
      }
      await page.evaluate(step => {
        const original = window.fetch;
        window.fetch = (url, options) => {
          if (url === "/app/documents/" + step) {
            window.fetch = original;
            return new Promise(resolve => { window.pendingUpload = resolve; });
          }
          return original(url, options);
        };
        document.getElementById(step === "preview" ? "document-preview-button" : "document-confirm").click();
      }, step);
      await page.waitForFunction(() => typeof window.pendingUpload === "function");
      // Normal refresh must not invalidate an active upload or strand disabled controls.
      await page.$eval("#refresh", e => e.click());
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: true});
        document.dispatchEvent(new Event("visibilitychange"));
        window.pendingUpload({ok: true, json: async () => ({request_id: "stale", confirmation: "stale",
          characters: 999, can_revise: true, queued: true})});
        delete window.pendingUpload;
      });
      await new Promise(resolve => setTimeout(resolve, 30));
      assert.equal(await page.$eval("#document-preview", e => e.hidden), true);
      assert.equal(await page.$eval("#document-preview-summary", e => e.textContent), "");
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: false});
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await page.waitForFunction(() => !document.getElementById("content").hidden);
      assert.equal(await page.$eval("#document-file", e => e.disabled), false);
      assert.equal(await page.$eval("#document-kind", e => e.disabled), false);
      assert.equal(await page.$eval("#document-confirm", e => e.disabled), false);
    }
    // Labs: pending lab, gate, escaping, safe references and catalog.
    assert.equal(await page.$$eval("#lab-items > li", e => e.length), 2);
    assert.equal(await page.$eval("#lab-count", e => e.textContent), "1 pending");
    assert.equal(await page.$eval("#lab-gate", e => e.hidden), false);
    assert.match(await page.$eval("#lab-gate", e => e.textContent), /waiting for 1 required lab.*\/labcarry/);
    assert.equal(await page.$eval("#lab-items .lab-token code", e => e.textContent), LAB_TOKEN);
    assert.equal(await page.$$eval("#lab-items .lab-token", e => e.length), 1);
    assert.match(await page.$eval("#lab-items .lab-state.blocking", e => e.textContent), /Needed before next week/);
    assert.equal(await page.$$eval("#lab-items > li:nth-child(2) .task-title *", e => e.length), 0);
    assert.deepEqual(await page.$$eval("#lab-items .lab-refs a", e => e.map(a => a.href)),
                     ["https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html"]);
    assert.deepEqual(await page.$$eval("#lab-catalog li code", e => e.map(c => c.textContent)), ["/lab vpc-subnet-routing"]);
    assert.match(await page.$eval("#lab-cost", e => e.textContent), /may cost money/);
    assert.equal(await page.$$eval(".lab-input", e => e.length), 1);
    assert.equal(await page.evaluate(() => window.pwnedLab), undefined);
    const submitsBefore = labSubmits.length;
    await page.$eval(".lab-input", e => { e.value = "http://example.com/not-https"; });
    await page.click(".lab-button");
    assert.match(await page.$eval("#lab-status", e => e.textContent), /https:\/\//);
    assert.equal(labSubmits.length, submitsBefore);
    // A failed check keeps the request ID so retrying the same link cannot queue a second job.
    const labLink = "https://github.com/synthetic-learner/labs";
    labFailOnce = true;
    await page.$eval(".lab-input", (e, link) => { e.value = link; }, labLink);
    await page.click(".lab-button");
    await page.waitForFunction(() => document.getElementById("lab-status").textContent.includes("retries the same request"));
    assert.equal(await page.$eval(".lab-button", e => e.disabled), false);
    const beforeData = dataRequests;
    await page.click(".lab-button");
    await page.waitForFunction(() => document.getElementById("lab-status").textContent.includes("Check submitted"));
    assert.equal(labSubmits.length, submitsBefore + 2);
    const [failed, retried] = labSubmits.slice(-2);
    assert.equal(retried.request_id, failed.request_id);
    assert.deepEqual(retried, {request_id: failed.request_id, assignment_id: "lab-synthetic-1", url: labLink});
    for (let wait = 0; dataRequests === beforeData && wait < 100; wait++) await new Promise(r => setTimeout(r, 20));
    assert.ok(dataRequests > beforeData, "a successful lab submit refreshes the dashboard");
    await page.waitForFunction(() => !document.querySelector(".lab-button").disabled);
    // While a check is in flight, controls lock, a double click sends once and refresh waits.
    await page.$eval(".lab-input", (e, link) => { e.value = link + "-2"; }, labLink);
    await page.evaluate(() => {
      const original = window.fetch;
      window.labCalls = 0;
      window.fetch = (url, options) => {
        if (url === "/app/labs/submit") {
          window.labCalls++;
          window.fetch = original;
          return new Promise(resolve => { window.pendingLab = resolve; });
        }
        return original(url, options);
      };
      const button = document.querySelector(".lab-button");
      button.click(); button.click();
    });
    await page.waitForFunction(() => typeof window.pendingLab === "function");
    assert.equal(await page.evaluate(() => window.labCalls), 1);
    assert.equal(await page.$eval(".lab-button", e => e.disabled), true);
    const busyData = dataRequests;
    await page.$eval("#refresh", e => e.click());
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(dataRequests, busyData);
    // Hiding the page clears every lab detail; a late response cannot repopulate private state.
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: true});
      document.dispatchEvent(new Event("visibilitychange"));
      window.pendingLab({ok: true, json: async () => ({queued: true, duplicate: false})});
      delete window.pendingLab;
    });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(await page.$$eval("#lab-items > li", e => e.length), 0);
    assert.equal(await page.$$eval("#resource-list > li", e => e.length), 0);
    assert.equal(await page.$eval("#resource-search", e => e.value), "");
    assert.equal(await page.$eval("#lab-status", e => e.textContent), "");
    assert.equal(await page.evaluate(token => document.body.textContent.includes(token), LAB_TOKEN), false);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: false});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForFunction(() => !document.getElementById("content").hidden);
    assert.equal(await page.$eval(".lab-button", e => e.disabled), false);
    assert.equal(await page.$eval(".lab-input", e => e.value), "");
    fixture.profile.name = "<img src=x onerror='window.pwned=true'>";
    await page.click("#refresh");
    await page.waitForFunction(() => document.getElementById("learner-name").textContent.startsWith("<img"));
    assert.equal(await page.$eval("#learner-name", e => e.children.length), 0);
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    denied = true;
    await page.click("#refresh");
    await page.waitForFunction(() => document.getElementById("content").hidden);
    assert.equal(await page.$$eval("#tasks > li", e => e.length), 0);
    assert.equal(await page.$$eval("#lab-items > li", e => e.length), 0);
    assert.equal(await page.$eval("#plan-rationale", e => e.textContent), "");
    assert.match(await page.$eval("#notice", e => e.textContent), /revoked/);
    denied = false;
    fixture.profile.name = "Synthetic learner";
    await page.evaluate(() => { window.Telegram.WebApp.initData = ""; });
    await page.click("#refresh");
    assert.match(await page.$eval("#notice", e => e.textContent), /Open this private dashboard/);
    await page.close();
  }
  const stale = await browser.newPage();
  await stale.setRequestInterception(true);
  stale.on("request", request => {
    if (request.url().startsWith("https://telegram.org/")) {
      request.respond({status: 200, contentType: "text/javascript", body:
        "window.Telegram={WebApp:{initData:'synthetic',colorScheme:'light',ready(){},expand(){},onEvent(){}}};"});
    } else if (request.url().startsWith(origin)) request.continue();
    else request.abort();
  });
  await stale.goto(origin + "/app");
  await stale.waitForFunction(() => !document.getElementById("content").hidden);
  await stale.evaluate(() => {
    window.fetch = () => new Promise(resolve => { window.delayedRefresh = resolve; });
    document.getElementById("refresh").click();
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await stale.evaluate(fixture => window.delayedRefresh({ok: true, json: async () => fixture}), fixture);
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(await stale.$eval("#content", e => e.hidden), true);
  assert.equal(await stale.$eval("#plan-rationale", e => e.textContent), "");
  await stale.close();
  // A lesson link from Telegram opens straight into that lesson and clears it when hidden.
  const direct = await browser.newPage();
  await direct.setRequestInterception(true);
  direct.on("request", request => {
    if (request.url().startsWith("https://telegram.org/")) {
      request.respond({status: 200, contentType: "text/javascript", body:
        "window.backShown=0;window.Telegram={WebApp:{initData:'synthetic',colorScheme:'dark',ready(){},expand(){},onEvent(){}," +
        "BackButton:{show(){window.backShown++},hide(){window.backShown=0},onClick(f){window.backClick=f}}}};"});
    } else if (request.url().startsWith(origin)) request.continue();
    else request.abort();
  });
  await direct.setViewport({width: 390, height: 900, deviceScaleFactor: 1});
  await direct.goto(`${origin}/app?lesson=${LESSON_ID}`);
  await direct.waitForFunction(() => !document.getElementById("lesson-page").hidden);
  assert.equal(await direct.$eval("#content", e => e.hidden), true);
  assert.ok(await direct.evaluate(() => window.backShown > 0));
  if (process.env.DASHBOARD_SCREENSHOT_DIR) {
    await direct.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, "lesson-dark-mobile.png"), fullPage: true});
  }
  await direct.evaluate(() => {
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  assert.equal(await direct.$eval("#lesson-view", e => e.hidden), true);
  assert.equal(await direct.evaluate(() => document.body.textContent.includes("guarantee the tested artifact")), false);
  const reopened = lessonRequests;
  await direct.evaluate(() => {
    Object.defineProperty(document, "hidden", {configurable: true, value: false});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await direct.waitForFunction(() => !document.getElementById("lesson-page").hidden);
  assert.equal(lessonRequests, reopened + 1);
  await direct.evaluate(() => window.backClick());
  assert.equal(await direct.$eval("#content", e => e.hidden), false);
  assert.equal(await direct.evaluate(() => window.backShown), 0);
  lessonDenied = true;
  await direct.click("#lesson-list > li:first-child button");
  await direct.waitForFunction(() => !document.getElementById("notice").hidden);
  assert.match(await direct.$eval("#notice", e => e.textContent), /revoked/);
  assert.equal(await direct.$eval("#lesson-view", e => e.hidden), true);
  assert.equal(await direct.$eval("#content", e => e.hidden), true);
  lessonDenied = false;
  await direct.close();
  console.log("Private dashboard mobile/desktop, lesson page, labs, text escaping, revocation clearing and direct-open checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
  await rm(uploadPath);
  await rmdir(uploadFolder);
}
