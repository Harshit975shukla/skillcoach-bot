import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdtemp, writeFile, rm, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import puppeteer from "puppeteer";
import { LAB_TOKEN, LESSON_ID, courses, fixture, growth, lessonFixture, resources } from "./dashboard-fixture.mjs";

let denied = false;
let uploadPreviews = 0, uploadConfirms = 0, dataRequests = 0, labFailOnce = false, lessonRequests = 0, lessonDenied = false;
let courseRequests = 0, courseDenied = false;
const exerciseTaps = [];
const labSubmits = [];
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
  if (request.url === "/app/exercise") {
    assert.equal(request.method, "POST");
    assert.equal(request.headers["x-csrf-token"], "synthetic-csrf");
    assert.equal(request.headers["x-telegram-init-data"], "synthetic-signed-launch");
    assert.equal(request.headers.cookie, undefined);
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    assert.deepEqual(Object.keys(body).sort(), ["action", "request_id", "task_id"]);
    assert.match(body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    exerciseTaps.push(body);
    response.writeHead(200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify({queued: true, duplicate: false}));
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
  if (request.url === "/app/course") {
    assert.equal(request.method, "POST");
    assert.equal(request.headers.cookie, undefined);
    let raw = ""; for await (const chunk of request) raw += chunk;
    const body = JSON.parse(raw);
    assert.deepEqual(Object.keys(body).sort(), ["init_data", "topic"]);
    assert.equal(body.init_data, "synthetic-signed-launch");
    assert.equal(body.topic, courses.lesson.id);
    courseRequests++;
    response.writeHead(courseDenied ? 403 : 200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(courseDenied ? {error: "Access was revoked."}
      : {lesson: courses.lesson, auth_expires_at: fixture.auth_expires_at, private: true}));
    return;
  }
  const names = {"/app": ["dashboard.html", "text/html"], "/static/dashboard.css": ["dashboard.css", "text/css"],
                 "/static/dashboard.js": ["dashboard.js", "text/javascript"],
                 "/static/lesson-content.js": ["lesson-content.js", "text/javascript"]};
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
    await page.emulateMediaFeatures([{name: "prefers-reduced-motion", value: "reduce"}]);
    await page.setRequestInterception(true);
    page.on("request", request => {
      if (request.url().startsWith("https://telegram.org/")) {
        request.respond({status: 200, contentType: "text/javascript", body:
          "window.Telegram={WebApp:{initData:'synthetic-signed-launch',colorScheme:'light',ready(){},expand(){},onEvent(){},openTelegramLink(url){window.openedQuiz=url;}}};"});
      } else if (request.url().startsWith(origin)) request.continue();
      else request.abort();
    });
    await page.goto(origin + "/app");
    await page.waitForFunction(() => !document.getElementById("content").hidden);
    assert.equal(await page.$eval("#learner-name", e => e.textContent), "Synthetic learner");
    assert.equal(await page.$$eval("#tasks > li", e => e.length), 2);
    assert.equal(await page.$eval("#earlier-tasks", e => e.hidden), false);
    assert.equal(await page.$$eval("#earlier-list > li", e => e.length), 1);
    assert.match(await page.$eval("#earlier-summary", e => e.textContent), /Earlier practice \(1, optional\)/);
    // Today: one next action, lesson/quiz/exercise status and the week's study days.
    assert.equal(await page.$eval("#today-card", e => e.hidden), false);
    assert.equal(await page.$eval("#today-next", e => e.textContent), "Finish the quiz for “CI pipeline design” (2/5)");
    assert.match(await page.$eval("#today-status", e => e.textContent), /Quiz: 2\/5 answered/);
    assert.match(await page.$eval("#today-status", e => e.textContent), /Exercises: 1 of 2 done/);
    assert.match(await page.$eval("#today-status", e => e.textContent), /Study days this week: 2 of 4 · streak 3/);
    assert.equal(await page.$eval("#today-actions a", e => e.href), "https://t.me/SkillCoachTestBot?start=quiz_" + LESSON_ID);
    assert.equal(await page.$eval("#study-days", e => e.textContent), "2 of 4");
    assert.equal(await page.$eval("#accuracy", e => e.textContent), "60% · 10 answered");
    assert.equal(await page.$eval("#understood", e => e.textContent), "2 of 3");
    assert.equal(await page.$eval("#streak", e => e.textContent), "3 days");
    assert.equal(await page.$eval("#reviews", e => e.textContent), "75% · 4 answered");
    assert.equal(await page.$eval("#graded", e => e.textContent), "(1 graded)");
    assert.match(await page.$eval("#today-status", e => e.textContent), /Reviews due: 2/);
    assert.equal(await page.$eval("#roadmap", e => e.hidden), false);
    assert.equal(await page.$eval("#roadmap-summary", e => e.textContent),
                 "Roadmap: 3 of 199 topics started · 1 solid · 1 needs review");
    assert.match(await page.$eval("#roadmap-next", e => e.textContent), /^Review what slipped: /);
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.$eval("#today", e => e.scrollIntoView());
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `today-${label}.png`)});
      await page.$eval("#progress", e => e.scrollIntoView());
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `progress-${label}.png`)});
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    // One-tap exercise tracking posts a bound request and refreshes the view.
    const beforeTap = dataRequests;
    await page.click("#tasks > li:first-child .exercise-button");
    for (let wait = 0; dataRequests === beforeTap && wait < 100; wait++) await new Promise(r => setTimeout(r, 20));
    assert.ok(dataRequests > beforeTap, "an exercise tap refreshes the dashboard");
    assert.deepEqual(exerciseTaps.slice(-1).map(({task_id, action}) => ({task_id, action})),
                     [{task_id: "test-task-1", action: "done"}]);
    await page.waitForFunction(() => document.getElementById("task-status").textContent.includes("recorded as done"));
    assert.equal(await page.$eval("#quiz-count", e => e.textContent), "2 available");
    assert.equal(await page.$$eval("#quiz-list a", e => e.length), 2);
    assert.equal(await page.$$eval("#quiz-list img", e => e.length), 0);
    assert.equal(await page.evaluate(() => window.pwnedQuiz), undefined);
    assert.match(await page.$eval("#quiz-list", e => e.textContent), /2\/5 answered/);
    assert.match(await page.$eval("#quiz-list", e => e.textContent), /4\/5 correct/);
    assert.match(await page.$eval("#quiz-list", e => e.textContent), /Deadline passed/);
    await page.click("#quiz-list a");
    assert.equal(await page.evaluate(() => window.openedQuiz), "https://t.me/SkillCoachTestBot?start=quiz_" + LESSON_ID);
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.$eval("#quizzes", e => e.scrollIntoView());
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `quizzes-${label}.png`)});
    }
    assert.match(await page.$eval("#plan-status", e => e.textContent), /Awaiting your approval/);
    assert.equal(await page.$eval("#plan-bot-link", e => e.href), "https://t.me/SkillCoachTestBot?start=plan");
    assert.equal(await page.evaluate(() => document.body.classList.contains("telegram-light")), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.equal(await page.$$eval("#course-module option", e => e.length), 24);
    assert.equal(await page.$$eval("#course-list > li", e => e.length), 10);
    await page.click("#course-more");
    assert.equal(await page.$$eval("#course-list > li", e => e.length), 20);
    const coursesBeforeSearch = courseRequests;
    await page.type("#course-search", "no-matching-topic-here");
    assert.match(await page.$eval("#course-list", e => e.textContent), /No matching lessons/);
    await page.$eval("#course-search", e => { e.value = ""; e.dispatchEvent(new Event("input")); });
    await page.select("#course-module", "linux");
    assert.equal(await page.$eval("#course-list .state-badge.needs_review", e => e.textContent), "Needs review");
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.$eval("#lessons", e => e.scrollIntoView());
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `roadmap-${label}.png`)});
    }
    assert.equal(await page.$$eval("#course-list > li", e => e.length),
      courses.index.modules.find(module => module.id === "linux").topics.length);
    assert.equal(courseRequests, coursesBeforeSearch, "course filtering is local");
    await page.click("#course-list button");
    await page.waitForFunction(() => !document.getElementById("lesson-page").hidden);
    assert.equal(await page.$eval("#lesson-title", e => e.textContent), courses.lesson.title);
    assert.match(await page.$eval("#lesson-meta", e => e.textContent), /AI-generated offline/);
    assert.equal(await page.$eval("#lesson-body", e => e.textContent.includes("/complete ")), false);
    assert.equal(await page.$eval("#lesson-feedback", e => e.hidden), true);
    assert.ok(await page.$("#lesson-walkthrough svg"));
    assert.ok(await page.$$eval("#lesson-walkthrough svg rect", nodes => nodes.every((node, i) => !i ||
      Number(nodes[i - 1].getAttribute("x")) + Number(nodes[i - 1].getAttribute("width")) < Number(node.getAttribute("x")))));
    const firstStep = await page.$eval("#lesson-walkthrough > h3", e => e.textContent);
    await page.click(".course-controls button:last-child");
    assert.notEqual(await page.$eval("#lesson-walkthrough > h3", e => e.textContent), firstStep);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `course-${label}.png`), fullPage: true});
    }
    await page.click("#lesson-back");
    assert.equal(await page.$eval("#content", e => e.hidden), false);
    courseDenied = true;
    await page.click("#course-list button");
    await page.waitForFunction(() => document.getElementById("content").hidden && !document.getElementById("notice").hidden);
    assert.equal(await page.$eval("#lesson-body", e => e.textContent), "");
    assert.equal(await page.$$eval("#course-list > li", e => e.length), 0);
    assert.equal(await page.$$eval("#quiz-list > li", e => e.length), 0);
    courseDenied = false;
    await page.click("#refresh");
    await page.waitForFunction(() => !document.getElementById("lesson-page").hidden);
    await page.click("#lesson-back");
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
    // Labs: open lab, carry-forward note, escaping, safe references and catalog.
    assert.equal(await page.$$eval("#lab-items > li", e => e.length), 2);
    assert.equal(await page.$eval("#lab-count", e => e.textContent), "1 pending");
    assert.equal(await page.$eval("#lab-gate", e => e.hidden), false);
    assert.match(await page.$eval("#lab-gate", e => e.textContent), /1 required lab still open.*carry forward.*never wait/);
    assert.equal(await page.$eval("#lab-items .lab-token code", e => e.textContent), LAB_TOKEN);
    assert.equal(await page.$$eval("#lab-items .lab-token", e => e.length), 1);
    assert.equal(await page.$$eval("#lab-items .lab-state.blocking", e => e.length), 0);
    assert.match(await page.$eval("#lab-items .lab-state", e => e.textContent), /Needs a fix/);
    assert.equal(await page.$$eval("#lab-items > li:nth-child(2) .task-title *", e => e.length), 0);
    assert.deepEqual(await page.$$eval("#lab-items .lab-refs a", e => e.map(a => a.href)),
                     ["https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html"]);
    assert.deepEqual(await page.$$eval("#lab-catalog li code", e => e.map(c => c.textContent)), ["/lab vpc-subnet-routing"]);
    assert.match(await page.$eval("#lab-cost", e => e.textContent), /may cost money/);
    assert.equal(await page.$$eval(".lab-input", e => e.length), 1);
    assert.equal(await page.evaluate(() => window.pwnedLab), undefined);
    // A local route is self-checked practice: cleanup and a no-submit note, never a link input.
    const localRoute = await page.$$eval("#lab-items > li:first-child details", nodes => {
      const local = nodes.find(d => d.querySelector("summary").textContent.startsWith("Practice locally"));
      return local ? local.textContent : "";
    });
    assert.match(localRoute, /Cleanup when you finish/);
    assert.match(localRoute, /nothing is deployed, charged or submitted/);
    assert.doesNotMatch(localRoute, /Submit:/);
    // Certification: the chosen exam, per-domain practice evidence, deep links and the other exams.
    assert.equal(await page.$eval("#cert-selected", e => e.hidden), false);
    assert.match(await page.$eval("#cert-title", e => e.textContent), /Certified Kubernetes Administrator/);
    assert.match(await page.$eval("#cert-overall", e => e.textContent), /65% across 2 practised domains/);
    assert.equal(await page.$eval("#cert-guide", e => e.href), growth.certification.track.source);
    const certDomains = await page.$$eval("#cert-domains > li", items => items.map(li => ({
      text: li.textContent, link: li.querySelector("a") ? li.querySelector("a").href : null})));
    assert.equal(certDomains.length, growth.certification.track.domains.length);
    assert.match(certDomains[0].text, /Strong in practice/);
    assert.match(certDomains[1].text, /40% of 5 practice answers.*Needs work/);
    assert.equal(certDomains[1].link, "https://t.me/SkillCoachTestBot?start=cert_cka_1");
    const otherExams = await page.$$eval("#cert-tracks > li", items => items.map(li => li.textContent));
    assert.equal(otherExams.length, growth.certification.tracks.length - 1);
    assert.ok(otherExams.every(text => !text.includes("Certified Kubernetes Administrator")));
    assert.match(await page.$eval("#cert-disclaimer", e => e.textContent),
                 /does not predict your exam result.*checked 2026-09-30/);
    // Capstones: statuses, escaped titles and the opt-in portfolio link.
    const capstoneItems = await page.$$eval("#capstone-list > li", items => items.map(li => li.textContent));
    assert.equal(capstoneItems.length, growth.capstones.length);
    assert.match(capstoneItems[0], /Verified/);
    assert.match(capstoneItems[1], /<img src=x.*Needs a fix/);
    assert.equal(await page.$$eval("#capstone-list img", e => e.length), 0);
    assert.equal(await page.evaluate(() => window.pwnedCapstone), undefined);
    assert.equal(await page.$eval("#portfolio-status a", e => new URL(e.href).pathname), "/portfolio/Ab3dEfGh1jKlMn0p");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      for (const section of ["certification", "labs"]) {
        await (await page.$("#" + section)).screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `${section}-${label}.png`)});
      }
    }
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
    // Switching to the chat cancels the in-flight check: its late reply cannot land, reading content stays.
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: true});
      document.dispatchEvent(new Event("visibilitychange"));
      window.pendingLab({ok: true, json: async () => ({queued: true, duplicate: false})});
      delete window.pendingLab;
    });
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(await page.$$eval("#lab-items > li", e => e.length), 2);
    assert.equal(await page.$eval("#lab-status", e => e.textContent), "");
    assert.equal(await page.$eval(".lab-input", e => e.value), "");
    assert.equal(await page.$eval("#content", e => e.hidden), false);
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
    assert.equal(await page.$$eval("#cert-domains > li, #cert-tracks > li, #capstone-list > li", e => e.length), 0);
    assert.equal(await page.$eval("#cert-selected", e => e.hidden), true);
    assert.equal(await page.$eval("#portfolio-status", e => e.textContent), "");
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
  await stale.evaluate(fixture => window.delayedRefresh({ok: true, json: async () => (
    {...fixture, profile: {...fixture.profile, name: "Late response"}})}), fixture);
  await new Promise(resolve => setTimeout(resolve, 50));
  // A refresh answered after the page was hidden is ignored.
  assert.equal(await stale.$eval("#learner-name", e => e.textContent), "Synthetic learner");
  await stale.close();
  // A lesson link from Telegram opens straight into that lesson and stays open while the learner visits the chat.
  const direct = await browser.newPage();
  const directErrors = [];
  direct.on("pageerror", error => directErrors.push(error.message));
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
  const reopened = lessonRequests, before = dataRequests;
  await direct.evaluate(() => {
    window.scrollTo(0, 400);
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  assert.equal(await direct.$eval("#lesson-view", e => e.hidden), false);
  assert.equal(await direct.evaluate(() => document.body.textContent.includes("guarantee the tested artifact")), true);
  await direct.evaluate(() => {
    Object.defineProperty(document, "hidden", {configurable: true, value: false});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  for (let wait = 0; dataRequests === before && wait < 100; wait++) await new Promise(r => setTimeout(r, 20));
  assert.ok(dataRequests > before, "returning re-checks access");
  await direct.waitForFunction(() => !document.getElementById("refresh").disabled);
  // The open lesson is kept, not reloaded, so the reading position survives.
  assert.equal(await direct.$eval("#lesson-page", e => e.hidden), false);
  assert.equal(lessonRequests, reopened);
  await direct.evaluate(() => window.backClick());
  assert.equal(await direct.$eval("#content", e => e.hidden), false);
  assert.equal(await direct.evaluate(() => window.backShown), 0);
  assert.deepEqual(directErrors, []);
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
