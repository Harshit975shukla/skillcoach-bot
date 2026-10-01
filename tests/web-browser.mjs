import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

// Synthetic fixtures only: no real learner, email or credential is used.
const CSRF = "synthetic-web-csrf";
const LESSON_ID = "0123456789abcdef0123";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const library = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",
  ["-c", "import json; from skillcoach.course_library import page; from skillcoach.catalog import TOPICS; " +
   "topic=next(k for k in TOPICS if k.startswith('linux/')); print(json.dumps(page(topic)))"],
  {encoding: "utf8", maxBuffer: 2 * 1024 * 1024}));
const earlier = [1, 2, 3].map(id => ({id, kind: "text", text: `Earlier message ${id}`, buttons: [],
  at: "2026-09-28T03:30:00+00:00"}));
const initialFeed = () => [
  {id: 11, kind: "text", at: "2026-10-01T03:30:00+00:00",
    text: "Question 1 of 5: which policy wins?\nDocs: https://docs.aws.amazon.com/iam/. <img src=x onerror=window.pwnedWeb=1>",
    buttons: [[{kind: "callback", text: "A) Allow", data: "a:q1:A"}, {kind: "callback", text: "B) Explicit deny", data: "a:q1:B"}],
              [{kind: "lesson", text: "Open lesson page", lesson: LESSON_ID}],
              [{kind: "link", text: "Bad link", url: "javascript:window.pwnedWeb=3"}],
              [{kind: "command", text: "📊 My progress", command: "/progress"}]]},
  {id: 12, kind: "text", at: "2026-10-01T03:31:00+00:00",
    blocks: [{type: "p", spans: [{t: "b", v: "Lesson ready"}, {t: "text", v: " run "}, {t: "code", v: "aws iam list-roles"}]},
             {type: "ul", items: [[{t: "text", v: "Item one"}], [{t: "text", v: "<script>window.pwnedWeb=2</script>"}]]}],
    buttons: []},
];
let state;
function resetState(overrides = {}) {
  state = {web: true, authenticated: false, feed: initialFeed(), sends: [], logins: [], lessonBodies: [],
           failNextSend: false, nextId: 20, sessionChecks: 0, joins: [], urls: [], ...overrides};
}
resetState();
const INVITE = "Abcdefghijklmnopqrstuvwxyz012345";
const lessonFixture = {...library, library: false, title: "IAM policy evaluation", date: "2026-10-01",
  exercises: [{id: "task-1", title: "Trace an explicit deny", minutes: 10, status: "pending",
               blocks: [{type: "p", spans: [{t: "text", v: "Compare two policies."}]}]}]};

const server = createServer(async (request, response) => {
  let raw = "";
  for await (const chunk of request) raw += chunk;
  const json = (status, value) => {
    response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(value));
  };
  const path = request.url.split("?")[0];
  state.urls.push(request.url);
  if (path.startsWith("/web/")) {
    assert.equal(request.url.includes("?"), false, "no credentials or identity in URLs");
    if (!state.web) return json(404, {error: "The web app is not switched on.", enabled: false});
    const body = raw ? JSON.parse(raw) : {};
    if (path === "/web/join/start") {
      assert.equal(request.headers.origin, origin);
      assert.deepEqual(Object.keys(body).sort(), ["email", "invite", "name"]);
      assert.equal(body.invite, INVITE);
      state.joins.push(body);
      return json(200, {pending: true, expires_at: new Date(Date.now() + 600000).toISOString(),
                        resend_at: new Date(Date.now() + 60000).toISOString()});
    }
    if (path === "/web/join/verify") {
      assert.equal(request.headers.origin, origin);
      assert.deepEqual(Object.keys(body), ["code"]);
      if (body.code !== "654321") return json(400, {error: "Incorrect code. 4 attempts remaining."});
      return json(200, {requested: true});
    }
    if (path === "/web/session") {
      state.sessionChecks++;
      return state.authenticated ? json(200, {authenticated: true, csrf: CSRF, name: "Synthetic learner",
        expires_at: new Date(Date.now() + 86400000).toISOString()}) : json(403, {error: "Sign in with your email to continue."});
    }
    if (path === "/web/login/start") {
      assert.equal(request.headers.origin, origin);
      assert.deepEqual(Object.keys(body), ["email"]);
      state.logins.push(body.email);
      if (body.email === "limited@example.test") return json(429, {error: "Codes are limited to one a minute, five an hour and ten a day. Try again later."});
      return json(200, {pending: true, expires_at: new Date(Date.now() + 600000).toISOString(),
                        resend_at: new Date(Date.now() + 60000).toISOString()});
    }
    if (path === "/web/login/verify") {
      assert.equal(request.headers.origin, origin);
      assert.deepEqual(Object.keys(body), ["code"]);
      if (body.code !== "123456") return json(400, {error: "Incorrect code. 4 attempts remaining."});
      state.authenticated = true;
      return json(200, {authenticated: true, csrf: CSRF, name: "Synthetic learner",
                        expires_at: new Date(Date.now() + 86400000).toISOString()});
    }
    if (path === "/web/logout") {
      state.authenticated = false;
      return json(200, {logged_out: true});
    }
    if (!state.authenticated) return json(403, {error: "Your session ended. Sign in again with your email."});
    assert.equal(request.headers["x-csrf-token"], CSRF);
    if (path === "/web/feed") {
      if (body.before !== undefined) return json(200, {messages: earlier.filter(m => m.id < body.before), working: false, older: false});
      const after = body.after ?? -1;
      return json(200, {messages: state.feed.filter(m => m.id > after), working: false, older: body.after === undefined});
    }
    if (path === "/web/send") {
      const keys = Object.keys(body).sort();
      assert.ok(["callback,request_id", "request_id,text"].includes(keys.join(",")), keys.join(","));
      assert.match(body.request_id, UUID);
      state.sends.push(body);
      if (state.failNextSend) { state.failNextSend = false; return json(503, {error: "SkillCoach is temporarily unavailable. Try again shortly."}); }
      if (state.sends.filter(s => s.request_id === body.request_id).length === 1 || body.text === "/today") {
        const reply = body.callback ? "✅ Correct: an explicit deny always wins." : `Reply to ${body.text}`;
        state.feed.push({id: state.nextId++, kind: "text", text: reply, buttons: [], at: new Date().toISOString()});
      }
      return json(202, {status: "queued"});
    }
    if (path === "/web/lesson") {
      state.lessonBodies.push(body);
      if (body.lesson === LESSON_ID) return json(200, {lesson: lessonFixture, private: true});
      return json(404, {error: "This lesson is not in your learning history."});
    }
    return json(404, {error: "Unknown route"});
  }
  const names = {"/web": ["web.html", "text/html"], "/static/web.css": ["web.css", "text/css"],
                 "/static/web.js": ["web.js", "text/javascript"], "/static/dashboard.css": ["dashboard.css", "text/css"],
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
const noOverflow = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
const texts = page => page.$$eval("#feed > li", items => items.map(item => item.textContent));
try {
  for (const [label, width] of [["mobile", 390], ["desktop", 1100]]) {
    resetState();
    const page = await browser.newPage();
    page.on("pageerror", error => { throw error; });
    await page.setViewport({width, height: 860, deviceScaleFactor: 1});
    await page.emulateMediaFeatures([{name: "prefers-reduced-motion", value: "reduce"}]);
    await page.setRequestInterception(true);
    page.on("request", request => request.url().startsWith(origin) ? request.continue() : request.abort());
    await page.goto(origin + "/web");
    await page.waitForFunction(() => !document.getElementById("signin").hidden);
    assert.equal(await page.$eval("#chat", e => e.hidden), true);
    assert.equal(await page.$eval("#logout", e => e.hidden), true);
    assert.equal(await page.$eval("#notice", e => e.hidden), true);
    if (shots) await page.screenshot({path: join(shots, `web-signin-${label}.png`)});
    // Email step: client-side validation, a rate-limit message, then the code step.
    await page.type("#email", "nope");
    await page.click("#email-submit");
    assert.equal(await page.$eval("#signin-error", e => e.textContent), "Enter a valid email address.");
    assert.equal(state.logins.length, 0);
    await page.$eval("#email", e => { e.value = "limited@example.test"; });
    await page.click("#email-submit");
    await page.waitForFunction(() => /limited to one a minute/.test(document.getElementById("signin-error").textContent));
    await page.$eval("#email", e => { e.value = "learner@example.test"; });
    await page.click("#email-submit");
    await page.waitForFunction(() => !document.getElementById("code-form").hidden);
    assert.match(await page.$eval("#code-sent", e => e.textContent), /learner@example\.test/);
    assert.equal(await page.$eval("#code-resend", e => e.disabled), true);
    assert.match(await page.$eval("#code-resend", e => e.textContent), /Send a new code \(\d+s\)/);
    await page.type("#code", "000000");
    await page.click("#code-submit");
    await page.waitForFunction(() => /Incorrect code/.test(document.getElementById("signin-error").textContent));
    assert.equal(await page.$eval("#code", e => e.value), "");
    await page.type("#code", "123456");
    await page.click("#code-submit");
    await page.waitForFunction(() => document.querySelectorAll("#feed .message").length === 2);
    assert.equal(await page.$eval("#signin", e => e.hidden), true);
    assert.equal(await page.$eval("#logout", e => e.hidden), false);
    // Untrusted text stays text; only safe HTTPS links become links.
    assert.equal(await page.$$eval("#feed img, #feed script", e => e.length), 0);
    assert.equal(await page.evaluate(() => window.pwnedWeb), undefined);
    assert.deepEqual(await page.$$eval("#feed a", links => links.map(a => a.href)), ["https://docs.aws.amazon.com/iam/"]);
    assert.match((await texts(page))[0], /<img src=x onerror=window\.pwnedWeb=1>/);
    assert.equal(await page.$eval("#feed .message:nth-child(2) code", e => e.textContent), "aws iam list-roles");
    assert.equal(await page.$eval("#feed .message:nth-child(2) strong", e => e.textContent), "Lesson ready");
    assert.equal(await page.$$eval("#feed .message:first-child .actions", e => e.length), 3);
    assert.equal(await page.$eval("#older", e => e.hidden), false);
    assert.ok(await noOverflow(page));
    if (shots) await page.screenshot({path: join(shots, `web-chat-${label}.png`)});
    // A quiz button sends that exact callback once, with CSRF, and the reply appears.
    await page.$$eval("#feed .message:first-child .actions button", buttons => buttons.find(b => b.textContent.startsWith("B)")).click());
    await page.waitForFunction(() => document.getElementById("feed").textContent.includes("explicit deny always wins"));
    assert.deepEqual(state.sends.map(({callback}) => callback), ["a:q1:B"]);
    assert.match((await texts(page)).at(-2), /B\) Explicit deny\s*Sent/);
    // A failed send keeps its request ID, so "Try again" cannot create a second message.
    state.failNextSend = true;
    await page.type("#message", "/today");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("#feed .message.mine.failed .retry"));
    assert.equal(await page.$eval("#message", e => e.value), "");
    // The retry must be visible, not hidden behind the docked composer and its shortcuts.
    assert.equal(await page.evaluate(() => {
      const retry = document.querySelector("#feed .message.mine.failed .retry"), box = retry.getBoundingClientRect();
      return document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2) === retry;
    }), true, "Try again is covered");
    const sendsBeforeRetry = state.sends.length;
    await page.click("#feed .message.mine.failed .retry");
    await page.waitForFunction(() => document.getElementById("feed").textContent.includes("Reply to /today"));
    assert.equal(state.sends.length, sendsBeforeRetry + 1);
    const [failed, retried] = state.sends.slice(-2);
    assert.equal(failed.request_id, retried.request_id);
    assert.deepEqual(retried, {request_id: failed.request_id, text: "/today"});
    await page.click('.quick button[data-command="/progress"]');
    await page.waitForFunction(() => document.getElementById("feed").textContent.includes("Reply to /progress"));
    // Shift+Enter keeps writing a multi-line answer instead of sending.
    const sendsBefore = state.sends.length;
    await page.type("#message", "line one");
    await page.keyboard.down("Shift"); await page.keyboard.press("Enter"); await page.keyboard.up("Shift");
    await page.type("#message", "line two");
    assert.equal(await page.$eval("#message", e => e.value), "line one\nline two");
    assert.equal(state.sends.length, sendsBefore);
    await page.$eval("#message", e => { e.value = ""; });
    // Earlier messages load above without losing the conversation.
    await page.click("#older");
    await page.waitForFunction(() => document.getElementById("feed").textContent.includes("Earlier message 1"));
    assert.match((await texts(page))[0], /Earlier message 1/);
    assert.equal(await page.$eval("#older", e => e.hidden), true);
    // The lesson reader opens the private lesson and returns to the conversation.
    await page.$$eval("#feed .actions button", buttons => buttons.find(b => b.textContent === "Open lesson page").click());
    await page.waitForFunction(() => document.getElementById("lesson-title").textContent === "IAM policy evaluation");
    assert.deepEqual(state.lessonBodies.at(-1), {lesson: LESSON_ID});
    assert.equal(await page.$eval("#chat", e => e.hidden), true);
    assert.match(await page.$eval("#lesson-body", e => e.textContent), /\/complete task-1/);
    assert.ok(await noOverflow(page));
    if (shots) await page.screenshot({path: join(shots, `web-lesson-${label}.png`)});
    await page.click("#reader-back");
    assert.equal(await page.$eval("#chat", e => e.hidden), false);
    assert.equal(await page.$eval("#lesson-body", e => e.children.length), 0);
    // An ended session clears the conversation and returns to sign-in.
    state.authenticated = false;
    await page.click('.quick button[data-command="/help"]');
    await page.waitForFunction(() => !document.getElementById("signin").hidden);
    assert.match(await page.$eval("#notice", e => e.textContent), /session ended/);
    assert.equal(await page.$$eval("#feed > li", e => e.length), 0);
    // Signing out clears private content.
    state.authenticated = true;
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll("#feed .message").length > 0);
    await page.click("#logout");
    await page.waitForFunction(() => !document.getElementById("signin").hidden);
    assert.equal(state.authenticated, false);
    assert.equal(await page.$$eval("#feed > li", e => e.length), 0);
    assert.equal(await page.$eval("#notice", e => e.textContent), "Signed out.");
    await page.close();
    console.log(`Web ${label} sign-in, conversation, retry, lesson reader and sign-out checks passed.`);
  }
  // When web mode is off, the page says so and shows no sign-in form.
  resetState({web: false});
  const page = await browser.newPage();
  await page.goto(origin + "/web");
  await page.waitForFunction(() => /not switched on/.test(document.getElementById("notice").textContent));
  assert.equal(await page.$eval("#signin", e => e.hidden), true);
  assert.equal(await page.$eval("#chat", e => e.hidden), true);
  await page.close();
  // Joining by invitation: the token leaves the address bar at once and travels only in a request body.
  for (const [label, width] of [["mobile", 390], ["desktop", 1100]]) {
    resetState();
    const joinPage = await browser.newPage();
    joinPage.on("pageerror", error => { throw error; });
    await joinPage.setViewport({width, height: 860, deviceScaleFactor: 1});
    await joinPage.setRequestInterception(true);
    joinPage.on("request", request => request.url().startsWith(origin) ? request.continue() : request.abort());
    await joinPage.goto(origin + "/web#invite=" + INVITE);
    await joinPage.waitForFunction(() => !document.getElementById("join").hidden);
    assert.equal(await joinPage.evaluate(() => location.href), origin + "/web");
    assert.equal(state.sessionChecks, 0, "an invitation does not touch any existing session");
    await joinPage.type("#join-name", "Synthetic Joiner");
    await joinPage.type("#join-email", "joiner@example.test");
    await joinPage.click("#join-submit");
    await joinPage.waitForFunction(() => !document.getElementById("join-code-form").hidden);
    assert.deepEqual(state.joins, [{invite: INVITE, name: "Synthetic Joiner", email: "joiner@example.test"}]);
    assert.match(await joinPage.$eval("#join-code-sent", e => e.textContent), /joiner@example\.test/);
    await joinPage.type("#join-code", "111111");
    await joinPage.click("#join-code-submit");
    await joinPage.waitForFunction(() => /4 attempts remaining/.test(document.getElementById("join-error").textContent));
    await joinPage.type("#join-code", "654321");
    await joinPage.click("#join-code-submit");
    await joinPage.waitForFunction(() => !document.getElementById("join-done").hidden);
    assert.match(await joinPage.$eval("#join-done-text", e => e.textContent), /joiner@example\.test/);
    assert.equal(await noOverflow(joinPage), true);
    if (shots) await joinPage.screenshot({path: join(shots, `web-join-${label}.png`), fullPage: true});
    await joinPage.click("#join-signin");
    await joinPage.waitForFunction(() => !document.getElementById("signin").hidden);
    assert.equal(await joinPage.$eval("#email", e => e.value), "joiner@example.test");
    assert.ok(state.urls.every(url => !url.includes(INVITE)), "the invitation token never appears in a request URL");
    // A damaged link explains itself and cannot be submitted.
    await joinPage.goto(origin + "/web#invite=short");
    await joinPage.waitForFunction(() => /incomplete/.test(document.getElementById("join-error").textContent));
    assert.equal(await joinPage.$eval("#join-submit", e => e.disabled), true);
    await joinPage.close();
    console.log(`Web ${label} join by invitation checks passed.`);
  }
  console.log("Web app browser checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
