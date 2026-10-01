import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";
import { LESSON_ID, courses, fixture, lessonFixture } from "./dashboard-fixture.mjs";

// The private dashboard for web learners. The page is rendered by the server's own filter, identity is
// the signed-in /web session (cookie plus CSRF token), and every action leads back to the web
// conversation. Synthetic fixtures only.
const CSRF = "0123456789abcdef".repeat(4);
const COOKIE = "web-session=synthetic-session";
const page = execFileSync(process.env.TEST_PYTHON || "python", ["-c",
  "import pathlib, sys; from skillcoach.web_routes import TELEGRAM_SCRIPT; sys.stdout.buffer.write(" +
  "TELEGRAM_SCRIPT.sub('', pathlib.Path('skillcoach/static/dashboard.html').read_text(encoding='utf-8')).encode())"],
  {encoding: "utf8"});
assert.ok(!page.includes("telegram.org"), "the web dashboard page never loads Telegram's script");

let state;
const resetState = () => {
  state = {authenticated: true, denied: false, sessionChecks: 0, data: 0, lessons: [], courses: [], exercises: [],
           expiresIn: 14 * 86400};
};
resetState();
const server = createServer(async (request, response) => {
  let raw = "";
  for await (const chunk of request) raw += chunk;
  const path = request.url.split("?")[0];
  const json = (status, value) => {
    response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(value));
  };
  if (path === "/web/dashboard") {
    // The real cookie is __Host- prefixed and Secure; this plain-HTTP test server uses a plain one.
    response.writeHead(200, {"Content-Type": "text/html; charset=utf-8",
                             "Set-Cookie": `${COOKIE}; Path=/; HttpOnly; SameSite=Strict`});
    response.end(page);
    return;
  }
  if (path === "/web/session") {
    assert.equal(request.method, "GET");
    state.sessionChecks++;
    return state.authenticated
      ? json(200, {authenticated: true, csrf: CSRF, name: "Synthetic learner", expires_at: new Date(Date.now() + 86400000).toISOString()})
      : json(403, {error: "Sign in with your email to continue."});
  }
  if (path.startsWith("/app/")) {
    // Identity is the session cookie and its CSRF token: never Telegram data, a URL or a learner ID.
    assert.equal(request.method, "POST");
    assert.equal(request.url.includes("?"), false);
    assert.equal(request.headers["x-telegram-init-data"], undefined);
    assert.equal(request.headers.cookie, COOKIE);
    assert.equal(request.headers["x-csrf-token"], CSRF);
    const body = JSON.parse(raw);
    assert.equal("init_data" in body, false);
    if (!state.authenticated || state.denied) return json(403, {error: "Your session ended. Sign in again with your email."});
    if (path === "/app/data") {
      assert.deepEqual(body, {});
      state.data++;
      return json(200, {...fixture, bot_url: null, web: true, document_csrf: CSRF,
                        auth_expires_at: Math.floor(Date.now() / 1000) + state.expiresIn});
    }
    if (path === "/app/lesson") {
      assert.deepEqual(Object.keys(body), ["lesson"]);
      state.lessons.push(body.lesson);
      return body.lesson === LESSON_ID ? json(200, {lesson: lessonFixture, auth_expires_at: fixture.auth_expires_at, private: true})
        : json(404, {error: "This lesson is not in your learning history."});
    }
    if (path === "/app/course") {
      assert.deepEqual(Object.keys(body), ["topic"]);
      state.courses.push(body.topic);
      return json(200, {lesson: courses.lesson, auth_expires_at: fixture.auth_expires_at, private: true});
    }
    if (path === "/app/exercise") {
      assert.deepEqual(Object.keys(body).sort(), ["action", "request_id", "task_id"]);
      state.exercises.push(body);
      return json(200, {queued: true, duplicate: false});
    }
    return json(404, {error: "Unknown route"});
  }
  const names = {"/static/dashboard.css": ["dashboard.css", "text/css"], "/static/dashboard.js": ["dashboard.js", "text/javascript"],
                 "/static/lesson-content.js": ["lesson-content.js", "text/javascript"]};
  const selected = names[path];
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
const shots = process.env.WEB_SCREENSHOT_DIR;
const noOverflow = tab => tab.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
const settle = () => new Promise(resolve => setTimeout(resolve, 150));
try {
  for (const [label, width] of [["mobile", 390], ["desktop", 1100]]) {
    resetState();
    const tab = await browser.newPage();
    const external = [], errors = [];
    tab.on("pageerror", error => errors.push(error.message));
    await tab.setViewport({width, height: 900, deviceScaleFactor: 1});
    await tab.emulateMediaFeatures([{name: "prefers-reduced-motion", value: "reduce"}]);
    await tab.setRequestInterception(true);
    tab.on("request", request => {
      if (request.url().startsWith(origin)) request.continue();
      else { external.push(request.url()); request.abort(); }
    });
    await tab.goto(origin + "/web/dashboard");
    await tab.waitForFunction(() => !document.getElementById("content").hidden);
    assert.equal(await tab.evaluate(() => window.Telegram), undefined);
    assert.equal(await tab.$eval("#learner-name", e => e.textContent), "Synthetic learner");
    // A tab brought to the front may refresh once more; each refresh still proves the same session.
    assert.ok(state.sessionChecks >= 1 && state.data >= 1);
    assert.equal(await tab.$eval("#chat-link", e => e.hidden), false);
    assert.equal(await tab.$eval("#chat-link", e => e.href), origin + "/web");
    // Every action opens the web conversation with a start payload, never Telegram.
    assert.equal(await tab.$eval("#today-actions a", e => e.href), `${origin}/web#start=quiz_${LESSON_ID}`);
    assert.equal(await tab.$eval("#today-actions a", e => e.textContent), "Take the quiz in your conversation");
    const quizLinks = await tab.$$eval("#quiz-list a", links => links.map(a => [a.textContent, a.getAttribute("href")]));
    assert.deepEqual(quizLinks, [["Resume in your conversation", `/web#start=quiz_${LESSON_ID}`],
                                 ["Start in your conversation", "/web#start=quiz_2026-09-28"]]);
    assert.equal(await tab.$eval("#plan-bot-link", e => e.hidden), false);
    assert.equal(await tab.$eval("#plan-bot-link", e => e.getAttribute("href")), "/web#start=plan");
    assert.equal(await tab.$eval("#plan-bot-link", e => e.textContent), "Review, change or approve in your conversation");
    const starts = await tab.$$eval("#content a[href^='/web#start=']", links => links.map(a => a.getAttribute("href")));
    assert.ok(starts.some(href => /^\/web#start=cert_[a-z-]+_\d+$/.test(href)), "certification practice links");
    assert.ok(starts.some(href => /^\/web#start=capstone_[a-z0-9-]+$/.test(href)), "capstone links");
    assert.ok(starts.every(href => /^\/web#start=[A-Za-z0-9_-]{1,64}$/.test(href)));
    assert.equal(await tab.$$eval("a[href*='t.me'], a[href*='telegram']", links => links.length), 0);
    const visible = await tab.$eval("#content", e => e.innerText);
    assert.doesNotMatch(visible, /Telegram|in the bot|inside the bot/);
    assert.match(visible, /Start or resume in your conversation/);
    assert.ok(await noOverflow(tab));
    if (shots) await tab.screenshot({path: join(shots, `web-dashboard-${label}.png`)});
    // Lessons and courses open with only their own identifier in the body.
    await tab.click("#today-actions button");
    await tab.waitForFunction(() => !document.getElementById("lesson-page").hidden);
    assert.deepEqual(state.lessons, [LESSON_ID]);
    await tab.click("#lesson-back");
    assert.equal(await tab.$eval("#content", e => e.hidden), false);
    // A recorded exercise uses the same session and its CSRF token, then refreshes.
    await tab.waitForFunction(() => !document.getElementById("refresh").disabled);
    let loads = state.data;
    await tab.click("#tasks > li:first-child .exercise-button");
    await tab.waitForFunction(() => /recorded as done/.test(document.getElementById("task-status").textContent));
    assert.deepEqual(state.exercises.map(({task_id, action}) => [task_id, action]), [["test-task-1", "done"]]);
    for (let wait = 0; state.data === loads && wait < 100; wait++) await settle();
    assert.ok(state.data > loads);
    // Hiding the page keeps what is open; returning re-checks access with the same session token.
    await tab.waitForFunction(() => !document.getElementById("refresh").disabled);
    const checks = state.sessionChecks;
    loads = state.data;
    await tab.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: true});
      document.dispatchEvent(new Event("visibilitychange"));
      Object.defineProperty(document, "hidden", {configurable: true, value: false});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    for (let wait = 0; state.data === loads && wait < 100; wait++) await settle();
    assert.ok(state.data > loads);
    assert.equal(state.sessionChecks, checks);
    // A refused request clears private data and forgets the token; the next refresh asks again.
    state.denied = true;
    await tab.waitForFunction(() => !document.getElementById("refresh").disabled);
    await tab.click("#refresh");
    await tab.waitForFunction(() => document.getElementById("content").hidden);
    assert.match(await tab.$eval("#notice", e => e.textContent), /session ended/);
    assert.equal(await tab.$$eval("#tasks > li, #quiz-list > li, #lab-items > li", e => e.length), 0);
    assert.equal(await tab.$eval("#learner-name", e => e.textContent), "");
    assert.equal(await tab.$eval("#chat-link", e => e.hidden), false);
    state.denied = false;
    await tab.click("#refresh");
    await tab.waitForFunction(() => !document.getElementById("content").hidden);
    assert.equal(state.sessionChecks, checks + 1);
    // Signed out on the web: the page asks the learner to sign in there.
    state.authenticated = false;
    await tab.click("#refresh");
    await tab.waitForFunction(() => document.getElementById("content").hidden);
    await tab.waitForFunction(() => !document.getElementById("refresh").disabled);
    await tab.click("#refresh");
    await tab.waitForFunction(() => /Sign in to SkillCoach on the web/.test(document.getElementById("notice").textContent));
    assert.equal(state.sessionChecks, checks + 2);
    // A long web session stays open: timers are clamped instead of firing at once.
    state.authenticated = true;
    state.expiresIn = 40 * 86400;
    await tab.click("#refresh");
    await tab.waitForFunction(() => !document.getElementById("content").hidden);
    await settle();
    assert.equal(await tab.$eval("#content", e => e.hidden), false);
    assert.equal(await tab.$eval("#notice", e => e.hidden), true);
    // The narrowest phones keep the header inside the screen.
    await tab.setViewport({width: 320, height: 800, deviceScaleFactor: 1});
    assert.ok(await tab.evaluate(() => [...document.querySelectorAll(".header > *")]
      .every(element => element.getBoundingClientRect().right <= innerWidth)));
    assert.deepEqual(external, [], "no third-party request");
    assert.deepEqual(errors, []);
    await tab.close();
    console.log(`Web dashboard ${label} identity, links, lesson, exercise, refusal and sign-out checks passed.`);
  }
  // Opening the dashboard without being signed in shows nothing private.
  resetState();
  state.authenticated = false;
  const signedOut = await browser.newPage();
  await signedOut.goto(origin + "/web/dashboard");
  await signedOut.waitForFunction(() => /Sign in to SkillCoach on the web/.test(document.getElementById("notice").textContent));
  assert.equal(await signedOut.$eval("#content", e => e.hidden), true);
  assert.equal(state.data, 0);
  await signedOut.close();
  console.log("Web dashboard browser checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
