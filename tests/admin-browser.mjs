import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

let authenticated = false, approved = false, executions = 0, authRequests = 0;
let loginChallenge = null, loginStarts = 0, statusFailures = 0;
let telegramFrameEnabled = false, rejectTelegramFrame = false;
const memoryRequests = [];
const received = [];
const previewId = "b286e036-b0a5-4844-b0c2-8044a20c2389";
const learningFixture = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from skillcoach.admin_learning import materials; from skillcoach.config import Config; " +
   "from skillcoach.course_library import page; from skillcoach.catalog import TOPICS; " +
   "topic=next(k for k in TOPICS if k.startswith('linux/')); " +
   "print(json.dumps({'materials':materials(Config('postgresql://test-only','fake-token',42,'a'*32)), 'lesson':page(topic)}))"],
  {encoding: "utf8", maxBuffer: 2 * 1024 * 1024}));
const topic = {id: learningFixture.lesson.id, title: learningFixture.lesson.title};
const learnerFixture = learner => ({
  learner, learning: {shared: learner !== "u_aaaaaaaaaaaa", status: "active", streak: 2, sessions_practiced: 1},
  upcoming: {status: learner === "u_aaaaaaaaaaaa" ? "Learner consent is required." : "Forecast only, not queued.",
    slots: [{kind: "lesson", title: "Lesson", at: "2026-09-30T09:00:00+05:30", topic, detail: "Timing depends on worker execution."}]},
  lessons: [{id: "0123456789abcdef0123", topic, date: "2026-09-29", source: "library", version: "2026-09-29",
    delivered_at: null, tasks_done: 0, tasks_total: 2}],
  lesson_next: "0123456789abcdef0123",
  deliveries: [{title: "Lesson", status: "Partially sent", processing: "done", created_at: "2026-09-29T03:30:00Z",
    messages: {total: 4, sent: 1, pending: 2, failed: 1, suppressed: 0}, media_sent: 0, last_sent_at: "2026-09-29T03:31:00Z"}],
  delivery_next: "100", generated_at: new Date().toISOString(),
  notice: "Transport records are not proof of reading or mastery.",
});
const fixture = {
  learners: [
    {id: "owner", name: "You (owner)", status: "active", last_interaction: "2026-09-26T05:00:00Z",
      ai_operations_today: 2, progress: {done: 3, assigned: 5, quizzes_completed: 1, lessons_delivered: 2, paused: false}},
    {id: "u_aaaaaaaaaaaa", name: "Invited learner", status: "pending", last_interaction: null,
      ai_operations_today: 0, progress: {done: 0, assigned: 0, quizzes_completed: 0, lessons_delivered: 0, paused: false}},
    {id: "u_bbbbbbbbbbbb", name: "<img src=x onerror='window.pwned=true'>", status: "active",
      last_interaction: "2026-09-26T04:30:00Z", ai_operations_today: 1,
      progress: {done: 2, assigned: 3, quizzes_completed: 1, lessons_delivered: 1, paused: true}},
  ],
  invitations: [{id: "i_aaaaaaaaaaaa", label: "Study group invitation", status: "open", expires_at: "2026-09-27T05:00:00Z"}],
  jobs: [{learner_id: "owner", status: "pending", kind: "schedule", scheduled_kind: "quiz",
          available_at: "2026-09-26T12:30:00Z", error_code: null, attempts: 0}],
  deliveries: [],
  audit: [{action: "invite", subject_id: "i_aaaaaaaaaaaa", source: "Telegram", created_at: "2026-09-26T05:00:00Z"}],
  actions: {invite: "Create invitation", approve: "Approve invited learner", reject: "Reject pending request",
            revoke: "Revoke learner access", send_lesson: "Send a full lesson", schedule_quiz: "Schedule a quiz",
            owner_command: "Run a command in your own bot chat", retry: "Retry failed work"},
  owner_commands: {help: "Help", learn: "Full lesson", topics: "Browse catalogue"},
  limits: {members: 10, ai_operations_per_learner: 40},
  generated_at: new Date().toISOString(),
  privacy: "Only participation and operational summaries are shown. Private documents and answers are excluded.",
  topics: {"aws-core/ec2": "AWS EC2"},
};
fixture.learners[0].learning = {
  shared: true, status: "active", plan_id: "synthetic-plan", version: 1, minutes: 30, sessions_practiced: 0,
  basis: "Initial diagnostic and selected goal.", active_days_this_week: 1, streak: 1, last_practice: "2026-09-26",
  labs: {required: 1, verified: 0, pending: 1, gate_blocked: true},
  sessions: [{day: 1, topic: "AWS EC2", reason: "Build foundational practice.", date: "2026-09-28",
    delivered: false, tasks_done: 0, tasks_total: 0, learner_understood: false}],
  assessments: [{date: "2026-09-26", kind: "daily", correct: 3, total: 5}],
};
fixture.actions.suggest_plan = "Suggest a plan topic";
const session = () => ({authenticated: true, csrf: "synthetic-csrf", expires_at: new Date(Date.now() + 900000).toISOString()});
const server = createServer(async (request, response) => {
  let raw = "";
  for await (const chunk of request) raw += chunk;
  const body = raw ? JSON.parse(raw) : {};
  if (request.url === "/frame") {
    response.writeHead(200, {"Content-Type": "text/html"});
    response.end('<iframe title="Telegram-like frame" src="https://embedded-admin.invalid/admin"></iframe>');
    return;
  }
  if (request.url.startsWith("/admin/") && !request.url.endsWith(".js")) {
    response.setHeader("Content-Type", "application/json");
    response.setHeader("Cache-Control", "no-store");
    const output = (code, value) => { response.writeHead(code); response.end(JSON.stringify(value)); };
    if (request.url === "/admin/session") {
      authRequests += 1;
      return output(authenticated ? 200 : 403, authenticated ? session() : {error: "Sign in"});
    }
    if (request.url === "/admin/login/start") {
      loginStarts += 1;
      loginChallenge = {code: "AB12CD", telegram_url: "https://t.me/SkillCoachTestBot?start=admin_login_test",
        expires_at: new Date(Date.now() + 300000).toISOString()};
      return output(200, loginChallenge);
    }
    if (request.url === "/admin/login/pin/start") {
      loginStarts += 1;
      loginChallenge = {pending: true, authenticated: false, method: "pin", attempts_remaining: 3,
        expires_at: new Date(Date.now() + 300000).toISOString(), resend_at: new Date(Date.now() + 60000).toISOString()};
      return output(200, loginChallenge);
    }
    if (request.url === "/admin/login/pin/verify") {
      if (!loginChallenge) return output(403, {error: "Request a PIN first."});
      assert.deepEqual(Object.keys(body), ["pin"]);
      if (body.pin !== "0042") return output(400, {error: "Incorrect PIN. 2 attempts remaining."});
      authenticated = true; loginChallenge = null;
      return output(200, session());
    }
    if (request.url === "/admin/login/status") {
      if (statusFailures > 0) { statusFailures -= 1; return output(503, {error: "Temporary sign-in interruption"}); }
      if (!loginChallenge) return output(403, {error: "Start a sign-in request from this browser first."});
      if (approved) { authenticated = true; loginChallenge = null; }
      return output(200, authenticated ? session() : {pending: true, authenticated: false, ...loginChallenge});
    }
    if (!authenticated) return output(403, {error: "Owner session expired"});
    if (request.headers["x-csrf-token"] !== "synthetic-csrf") return output(403, {error: "CSRF missing"});
    if (request.url === "/admin/data") return output(200, fixture);
    if (request.url === "/admin/materials") return output(200, learningFixture.materials);
    if (request.url === "/admin/course") {
      assert.deepEqual(body, {topic: topic.id, version: "2026-09-29"});
      return output(200, {lesson: learningFixture.lesson});
    }
    if (request.url === "/admin/learner") {
      const data = learnerFixture(body.learner);
      if (body.lesson_before) { data.lessons[0].date = "2026-09-28"; data.lesson_next = null; }
      if (body.delivery_before) { data.deliveries[0].status = "Sent to Telegram"; data.delivery_next = null; }
      return output(200, data);
    }
    if (request.url === "/admin/action/preview") {
      received.push(body);
      return output(200, {request_id: previewId, confirmation: "server-bound-token",
        expires_at: new Date(Date.now() + 300000).toISOString(), state: "preview",
        preview: {title: "Create invitation", recipient: "You (owner)", recipient_id: "owner",
                  details: ["One-use invitation: " + body.arguments.label], warnings: ["Approval is still required."],
                  delivery: "The result appears here."}});
    }
    if (request.url === "/admin/action/execute") {
      executions += 1;
      assert.deepEqual(body, {request_id: previewId, confirmation: "server-bound-token"});
      return output(200, {state: "handled", messages: [
        "Invitation created. https://t.me/SkillCoachTestBot?start=invite_" + "a".repeat(32)
      ]});
    }
    if (request.url === "/admin/logout") { authenticated = false; return output(200, {logged_out: true}); }
    return output(404, {error: "Unknown route"});
  }
  const file = request.url === "/admin" ? "admin.html" : request.url.replace("/static/", "");
  if (!["admin.html", "admin.css", "admin.js", "dashboard.css", "lesson-content.js"].includes(file)) {
    response.writeHead(404).end(); return;
  }
  response.writeHead(200, {"Content-Type": file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html"});
  response.end(await readFile(join("skillcoach", "static", file)));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await puppeteer.launch({headless: true, executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
                                       args: process.platform === "linux" ? ["--no-sandbox"] : []});
try {
  for (const [name, width] of [["mobile", 390], ["desktop", 1280]]) {
    authenticated = false; approved = false; executions = 0; loginChallenge = null;
    const page = await browser.newPage();
    page.on("pageerror", error => console.error("Admin browser page error:", error.message));
    await page.emulateMediaFeatures([{name: "prefers-reduced-motion", value: "reduce"}]);
    await page.setViewport({width, height: 900, deviceScaleFactor: 1});
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) {
        request.respond({status: 200, contentType: "text/javascript", body: ""});
      } else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.goto(origin + "/admin");
    await page.waitForFunction(() => !document.getElementById("login").hidden);
    assert.equal(await page.$eval("#console", e => e.hidden), true);
    assert.equal(await page.$$eval("#members tr", e => e.length), 0);
    await page.click("#start-login");
    await page.waitForFunction(() => !document.getElementById("pin-form").hidden);
    assert.equal(await page.$eval("#resend-pin", e => e.disabled), true);
    await page.type("#login-pin", "0042");
    await page.click("#verify-pin");
    await page.waitForFunction(() => !document.getElementById("console").hidden);
    assert.equal(await page.$$eval("#members tr", e => e.length), 3);
    assert.equal(await page.$$eval("#members img", e => e.length), 0);
    assert.ok(await page.evaluate(() => document.body.textContent.includes(
      "Labs: 0 verified · 1 pending · 1 required · next week waits for required labs")));
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.select("#learner-select", "owner");
    await page.waitForFunction(() => !document.getElementById("learner-detail").hidden);
    await page.evaluate(data => {
      const original = window.fetch;
      window.fetch = (url, options) => {
        if (url === "/admin/learner" && JSON.parse(options.body).learner === "owner") {
          window.fetch = original;
          return new Promise(resolve => { window.__lateLearner = () => resolve(
            new Response(JSON.stringify(data), {status: 200})); });
        }
        return original(url, options);
      };
    }, learnerFixture("owner"));
    await page.click("#learner-refresh");
    await page.waitForFunction(() => typeof window.__lateLearner === "function");
    await page.select("#learner-select", "u_aaaaaaaaaaaa");
    await page.waitForFunction(() => document.getElementById("learner-status").textContent.includes("consent"));
    await page.evaluate(() => window.__lateLearner());
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await page.$eval("#learner-detail", e => e.hidden), true);
    assert.equal(await page.$$eval("#learner-lessons > li", e => e.length), 0);
    await page.select("#learner-select", "owner");
    await page.waitForFunction(() => !document.getElementById("learner-detail").hidden);
    assert.match(await page.$eval("#learner-lessons", e => e.textContent), /No completed lesson-delivery receipt/);
    assert.match(await page.$eval("#learner-deliveries", e => e.textContent), /Partially sent/);
    assert.match(await page.$eval("#learner-upcoming", e => e.textContent), /09:00|9:00/);
    await page.click("#lessons-more");
    await page.waitForFunction(() => document.getElementById("lessons-more").hidden);
    assert.equal(await page.$$eval("#learner-lessons > li", e => e.length), 2);
    await page.click("#deliveries-more");
    await page.waitForFunction(() => document.getElementById("deliveries-more").hidden);
    assert.equal(await page.$$eval("#learner-deliveries > li", e => e.length), 2);
    await page.select("#learner-select", "u_aaaaaaaaaaaa");
    await page.waitForFunction(() => document.getElementById("learner-status").textContent.includes("consent"));
    assert.equal(await page.$eval("#learner-detail", e => e.hidden), true);
    assert.equal(await page.$$eval("#learner-lessons > li", e => e.length), 0);
    await page.click("#materials-load");
    await page.waitForFunction(() => !document.getElementById("materials-index").hidden);
    assert.match(await page.$eval("#materials-status", e => e.textContent), /199 lessons/);
    assert.equal(await page.$$eval("#admin-course-list > li", e => e.length), 10);
    await page.click("#admin-course-more");
    assert.equal(await page.$$eval("#admin-course-list > li", e => e.length), 20);
    await page.select("#admin-course-module", "linux");
    assert.equal(await page.$$eval("#admin-course-list > li", e => e.length), 8);
    await page.type("#admin-course-search", "no-such-topic");
    assert.match(await page.$eval("#admin-course-list", e => e.textContent), /No matching/);
    await page.$eval("#admin-course-search", e => { e.value = ""; e.dispatchEvent(new Event("input")); });
    await page.click("#admin-course-list button");
    try {
      await page.waitForFunction(() => !document.getElementById("course-review").hidden, {timeout: 5000});
    } catch {
      throw new Error("Course preview failed: " + await page.$eval("#materials-status", e => e.textContent)
        + " / " + await page.$eval("#message", e => e.textContent));
    }
    assert.equal(await page.$eval("#course-review-title", e => e.textContent), learningFixture.lesson.title);
    assert.match(await page.$eval("#course-review-body", e => e.textContent), /Cleanup/);
    assert.equal(await page.$$eval("#course-review-body .course-diagram svg", e => e.length), 1);
    await page.click("#course-review-body .course-controls button:last-child");
    assert.match(await page.$eval("#lesson-walkthrough h3", e => e.textContent), /^2 \//);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.ADMIN_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.ADMIN_SCREENSHOT_DIR, `admin-course-${name}.png`), fullPage: true});
    }
    await page.click("#course-review-close");
    await page.select("#learner-select", "owner");
    await page.waitForFunction(() => !document.getElementById("learner-detail").hidden);
    if (process.env.ADMIN_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.ADMIN_SCREENSHOT_DIR, `admin-${name}.png`), fullPage: true});
    }
    await page.select("#action-kind", "invite");
    await page.type('[name="label"]', "Browser test");
    await page.click("#preview-action");
    try {
      await page.waitForFunction(() => !document.getElementById("action-preview").hidden, {timeout: 5000});
    } catch {
      throw new Error("Preview failed: " + await page.$eval("#message", e => e.textContent));
    }
    assert.equal(executions, 0);
    assert.equal(await page.$eval("#execute-action", e => e.disabled), true);
    assert.match(await page.$eval("#preview-recipient", e => e.textContent), /owner/);
    await page.click("#confirm-checkbox");
    await page.$eval("#execute-action", e => { e.click(); e.click(); });
    await page.waitForFunction(() => !document.getElementById("action-result").hidden);
    assert.equal(executions, 1);
    assert.match(await page.$eval("#invite-url", e => e.value), /start=invite_/);
    await page.evaluate(data => {
      const original = window.fetch;
      window.fetch = (url, options) => {
        if (url === "/admin/data") {
          window.fetch = original;
          return new Promise(resolve => { window.__lateData = () => resolve(new Response(JSON.stringify(data), {status: 200})); });
        }
        return original(url, options);
      };
    }, fixture);
    await page.click("#refresh");
    await page.waitForFunction(() => typeof window.__lateData === "function");
    await page.click("#logout");
    await page.waitForFunction(() => document.getElementById("console").hidden);
    assert.equal(await page.$$eval("#members tr", e => e.length), 0);
    assert.equal(await page.$$eval("#learner-lessons > li", e => e.length), 0);
    assert.equal(await page.$$eval("#admin-course-list > li", e => e.length), 0);
    assert.equal(await page.$eval("#course-review-body", e => e.textContent), "");
    assert.equal(await page.$eval("#invite-url", e => e.value), "");
    await page.evaluate(() => window.__lateData());
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await page.$eval("#console", e => e.hidden), true);
    assert.equal(await page.$$eval("#members tr", e => e.length), 0);
    await page.close();
    console.log(`Admin ${name} interaction checks passed.`);
  }
  for (const reason of ["reload-pending", "reload-approved", "hidden-return", "temporary-error", "hidden-exchange"]) {
    authenticated = false; approved = false; loginChallenge = null; loginStarts = 0; statusFailures = 0;
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) request.respond({status: 200, contentType: "text/javascript", body: ""});
      else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.goto(origin + "/admin");
    await page.waitForFunction(() => !document.getElementById("login").hidden);
    await page.evaluate(async () => {
      await fetch("/admin/login/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    });
    await page.reload();
    await page.waitForFunction(() => document.getElementById("login-code").textContent === "AB12CD");
    if (reason === "reload-pending") {
      await page.reload();
      await page.waitForFunction(() => document.getElementById("login-code").textContent === "AB12CD");
      assert.equal(await page.$eval("#start-login", e => e.hidden), true);
      assert.equal(await page.$eval("#console", e => e.hidden), true);
    }
    if (reason === "hidden-return") {
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: true});
        document.dispatchEvent(new Event("visibilitychange"));
      });
    }
    if (reason === "temporary-error") {
      statusFailures = 1;
      await page.click("#check-login");
      await page.waitForFunction(() => document.getElementById("message").textContent.includes("Temporary sign-in interruption"));
      assert.equal(await page.$eval("#login-challenge", e => e.hidden), false);
    }
    if (reason === "hidden-exchange") {
      await page.evaluate(() => {
        const original = window.fetch;
        window.fetch = async (url, options) => {
          const response = await original(url, options);
          if (url !== "/admin/login/status") return response;
          window.fetch = original;
          window.__exchangeSignal = options.signal;
          return new Promise(resolve => { window.__finishExchange = () => resolve(response); });
        };
      });
    }
    approved = true;
    if (reason === "reload-approved") await page.reload();
    else if (reason === "hidden-return") {
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: false});
        document.dispatchEvent(new Event("visibilitychange"));
      });
    } else if (reason === "hidden-exchange") {
      await page.click("#check-login");
      await page.waitForFunction(() => typeof window.__finishExchange === "function");
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: true});
        document.dispatchEvent(new Event("visibilitychange"));
        window.__finishExchange();
      });
      await new Promise(resolve => setTimeout(resolve, 100));
      assert.equal(await page.evaluate(() => window.__exchangeSignal.aborted), false);
      assert.equal(await page.$eval("#console", e => e.hidden), true);
      assert.equal(await page.$$eval("#members tr", e => e.length), 0);
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: false});
        document.dispatchEvent(new Event("visibilitychange"));
      });
    } else if (reason !== "temporary-error") await page.click("#check-login");
    await page.waitForFunction(() => !document.getElementById("console").hidden);
    assert.equal(loginStarts, 1, "Recovery must not replace the approved request");
    await page.close();
    console.log(`Admin browser sign-in recovery passed: ${reason}.`);
  }
  for (const reason of ["reload", "incorrect-pin", "hidden-verification"]) {
    authenticated = false; approved = false; loginChallenge = null; loginStarts = 0;
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) request.respond({status: 200, contentType: "text/javascript", body: ""});
      else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.goto(origin + "/admin");
    await page.waitForFunction(() => !document.getElementById("login").hidden);
    await page.click("#start-login");
    await page.waitForFunction(() => !document.getElementById("pin-form").hidden);
    if (reason === "reload") {
      await page.reload();
      await page.waitForFunction(() => !document.getElementById("pin-form").hidden);
      assert.equal(await page.$eval("#approval-challenge", e => e.hidden), true);
    }
    if (reason === "incorrect-pin") {
      await page.type("#login-pin", "9999");
      await page.click("#verify-pin");
      await page.waitForFunction(() => document.getElementById("message").textContent.includes("Incorrect PIN"));
      assert.equal(await page.$eval("#login-pin", e => e.value), "");
      assert.equal(await page.$eval("#console", e => e.hidden), true);
    }
    if (reason === "hidden-verification") {
      await page.evaluate(() => {
        const original = window.fetch;
        window.fetch = async (url, options) => {
          const response = await original(url, options);
          if (url !== "/admin/login/pin/verify") return response;
          window.fetch = original; window.__exchangeSignal = options.signal;
          return new Promise(resolve => { window.__finishExchange = () => resolve(response); });
        };
      });
    }
    await page.type("#login-pin", "0042");
    await page.click("#verify-pin");
    if (reason === "hidden-verification") {
      await page.waitForFunction(() => typeof window.__finishExchange === "function");
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: true});
        document.dispatchEvent(new Event("visibilitychange"));
        window.__finishExchange();
      });
      await new Promise(resolve => setTimeout(resolve, 100));
      assert.equal(await page.evaluate(() => window.__exchangeSignal.aborted), false);
      assert.equal(await page.$eval("#console", e => e.hidden), true);
      assert.equal(await page.$eval("#login-pin", e => e.value), "");
      await page.evaluate(() => {
        Object.defineProperty(document, "hidden", {configurable: true, value: false});
        document.dispatchEvent(new Event("visibilitychange"));
      });
    }
    await page.waitForFunction(() => !document.getElementById("console").hidden);
    assert.equal(loginStarts, 1);
    assert.equal(await page.$eval("#login-pin", e => e.value), "");
    await page.close();
    console.log(`Admin PIN sign-in passed: ${reason}.`);
  }
  for (const reason of ["expiry", "hidden", "late-login"]) {
    authenticated = true;
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) request.respond({status: 200, contentType: "text/javascript", body: ""});
      else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.evaluateOnNewDocument((reason, data) => {
      const timeout = window.setTimeout;
      window.setTimeout = (handler, delay, ...args) => {
        if (delay > 800000 && delay <= 900000) window.__expireSession = handler;
        return timeout(handler, delay, ...args);
      };
      if (reason === "late-login") {
        const original = window.fetch;
        window.fetch = (url, options) => url === "/admin/session"
          ? new Promise(resolve => { window.__lateLogin = () => resolve(new Response(JSON.stringify({
            authenticated: true, csrf: "synthetic-csrf", expires_at: new Date(Date.now() + 900000).toISOString()
          }), {status: 200})); })
          : original(url, options);
      }
      window.__fixture = data;
    }, reason, fixture);
    await page.goto(origin + "/admin");
    if (reason === "late-login") {
      await page.waitForFunction(() => typeof window.__lateLogin === "function");
    } else {
      await page.waitForFunction(() => !document.getElementById("console").hidden);
      await page.click("#materials-load");
      await page.waitForFunction(() => !document.getElementById("materials-index").hidden);
      await page.select("#learner-select", "owner");
      await page.waitForFunction(() => !document.getElementById("learner-detail").hidden);
      await page.evaluate(() => {
        const original = window.fetch;
        window.fetch = (url, options) => {
          if (url === "/admin/data") {
            window.fetch = original;
            return new Promise(resolve => { window.__lateData = () => resolve(
              new Response(JSON.stringify(window.__fixture), {status: 200})); });
          }
          return original(url, options);
        };
      });
      await page.click("#refresh");
      await page.waitForFunction(() => typeof window.__lateData === "function");
    }
    await page.evaluate(reason => {
      if (reason === "expiry") window.__expireSession();
      else {
        Object.defineProperty(document, "hidden", {configurable: true, value: true});
        document.dispatchEvent(new Event("visibilitychange"));
      }
      if (reason === "late-login") window.__lateLogin();
      else window.__lateData();
    }, reason);
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await page.$eval("#console", e => e.hidden), true);
    assert.equal(await page.$$eval("#members tr", e => e.length), 0);
    assert.equal(await page.$$eval("#admin-course-list > li", e => e.length), 0);
    assert.equal(await page.$$eval("#learner-lessons > li", e => e.length), 0);
    await page.close();
    console.log(`Admin stale-response check passed: ${reason}.`);
  }
  const framePage = await browser.newPage();
  await framePage.setRequestInterception(true);
  framePage.on("request", async request => {
    const host = new URL(request.url()).hostname;
    if (host === "embedded-admin.invalid") {
      const path = new URL(request.url()).pathname;
      if (path === "/admin/telegram-session") {
        authRequests += 1;
        assert.equal(request.method(), "POST");
        assert.deepEqual(JSON.parse(request.postData()), {init_data: "synthetic-owner-launch"});
        request.respond({status: rejectTelegramFrame ? 403 : 200, contentType: "application/json", body: JSON.stringify(
          rejectTelegramFrame ? {error: "Only the owner can open administration."} :
          {authenticated: true, transport: "telegram", session_token: "tg_" + "x".repeat(43),
           csrf: "memory-csrf", expires_at: new Date(Date.now() + 300000).toISOString()}
        )});
        return;
      }
      if (path === "/admin/data" || path === "/admin/logout") {
        memoryRequests.push({path, headers: request.headers()});
        assert.equal(request.headers()["x-admin-session"], "tg_" + "x".repeat(43));
        assert.equal(request.headers()["x-telegram-init-data"], "synthetic-owner-launch");
        assert.equal(request.headers()["x-csrf-token"], "memory-csrf");
        assert.equal(request.headers().cookie, undefined);
        request.respond({status: 200, contentType: "application/json",
          body: JSON.stringify(path === "/admin/logout" ? {logged_out: true} : fixture)});
        return;
      }
      const file = path === "/admin" ? "admin.html" : path.replace("/static/", "");
      if (!["admin.html", "admin.css", "admin.js", "dashboard.css", "lesson-content.js"].includes(file)) {
        authRequests += 1;
        request.respond({status: 403, contentType: "application/json", body: '{"error":"No iframe authentication"}'});
      } else request.respond({status: 200,
        contentType: file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html",
        body: await readFile(join("skillcoach", "static", file))});
    } else if (request.url().startsWith("https://telegram.org/")) request.respond({
      status: 200, contentType: "text/javascript", body: telegramFrameEnabled
        ? "window.Telegram={WebApp:{initData:'synthetic-owner-launch',colorScheme:'light',ready(){},onEvent(){}}};" : ""
    });
    else if (host === "127.0.0.1") request.continue();
    else request.abort();
  });
  const priorAuthRequests = authRequests;
  await framePage.goto(origin + "/frame");
  const embedded = framePage.frames().find(frame => frame.url().includes("embedded-admin.invalid") && frame.url().endsWith("/admin"));
  assert.ok(embedded, `Cross-site frame was not loaded: ${framePage.frames().map(frame => frame.url()).join(", ")}`);
  await embedded.waitForFunction(() => !document.getElementById("open-browser").hidden);
  assert.equal(await embedded.$eval("#console", e => e.hidden), true);
  assert.equal(await embedded.$eval("#start-login", e => e.hidden), true);
  assert.equal(await embedded.$eval("#open-browser", e => e.target), "_blank");
  assert.equal(authRequests, priorAuthRequests);
  telegramFrameEnabled = true;
  await framePage.setCookie({name: "__Host-skillcoach-admin", value: "unrelated-strict-cookie",
                            url: "https://embedded-admin.invalid/", secure: true, path: "/", sameSite: "Strict"});
  await framePage.reload();
  let miniapp = framePage.frames().find(frame => frame.url().includes("embedded-admin.invalid") && frame.url().endsWith("/admin"));
  await miniapp.waitForFunction(() => !document.getElementById("console").hidden);
  assert.equal(await miniapp.$$eval("#members tr", rows => rows.length), 3);
  assert.ok(memoryRequests.some(item => item.path === "/admin/data"));
  assert.equal(await miniapp.evaluate(() => localStorage.length + sessionStorage.length), 0);
  await miniapp.click("#logout");
  await miniapp.waitForFunction(() => document.getElementById("console").hidden);
  assert.ok(memoryRequests.some(item => item.path === "/admin/logout"));
  assert.equal(await miniapp.$$eval("#members tr", rows => rows.length), 0);
  const afterLogoutRequests = authRequests;
  await miniapp.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(authRequests, afterLogoutRequests);
  rejectTelegramFrame = true;
  await framePage.reload();
  miniapp = framePage.frames().find(frame => frame.url().includes("embedded-admin.invalid") && frame.url().endsWith("/admin"));
  await miniapp.waitForFunction(() => !document.getElementById("open-browser").hidden);
  assert.equal(await miniapp.$eval("#console", e => e.hidden), true);
  assert.match(await miniapp.$eval("#message", e => e.textContent), /Only the owner/);
  await framePage.close();
  const nativePage = await browser.newPage();
  let expiredLaunchAttempts = 0;
  await nativePage.setRequestInterception(true);
  nativePage.on("request", request => {
    if (request.url().startsWith("https://telegram.org/")) {
      request.respond({status: 200, contentType: "text/javascript",
        body: "window.Telegram={WebApp:{initData:'expired-owner-launch',colorScheme:'light',ready(){},onEvent(){}}};"});
    } else if (request.url() === origin + "/admin/telegram-session") {
      expiredLaunchAttempts += 1;
      request.respond({status: 403, contentType: "application/json", body: '{"error":"Launch expired; reopen from Telegram."}'});
    } else if (request.url().startsWith(origin)) request.continue();
    else request.abort();
  });
  await nativePage.goto(origin + "/admin");
  await nativePage.waitForFunction(() => !document.getElementById("open-browser").hidden);
  assert.equal(await nativePage.$eval("#start-login", e => e.hidden), true);
  assert.equal(await nativePage.$eval("#console", e => e.hidden), true);
  assert.match(await nativePage.$eval("#message", e => e.textContent), /expired/);
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(expiredLaunchAttempts, 1);
  await nativePage.close();
  assert.ok(received.every(body => body.target === "owner" && body.action === "invite"));
  console.log("Admin browser and cookie-free Telegram-frame login, confirmation, XSS, logout, stale-response and safe fallback checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
