import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

let authenticated = false, approved = false, executions = 0, authRequests = 0;
let telegramFrameEnabled = false, rejectTelegramFrame = false;
const memoryRequests = [];
const received = [];
const previewId = "b286e036-b0a5-4844-b0c2-8044a20c2389";
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
};
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
    if (request.url === "/admin/login/start") return output(200, {code: "AB12CD",
      telegram_url: "https://t.me/SkillCoachTestBot?start=admin_login_test", expires_at: new Date(Date.now() + 300000).toISOString()});
    if (request.url === "/admin/login/status") {
      if (approved) authenticated = true;
      return output(200, authenticated ? session() : {pending: true, authenticated: false});
    }
    if (!authenticated) return output(403, {error: "Owner session expired"});
    if (request.headers["x-csrf-token"] !== "synthetic-csrf") return output(403, {error: "CSRF missing"});
    if (request.url === "/admin/data") return output(200, fixture);
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
  if (!["admin.html", "admin.css", "admin.js", "dashboard.css"].includes(file)) {
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
    authenticated = false; approved = false; executions = 0;
    const page = await browser.newPage();
    page.on("pageerror", error => console.error("Admin browser page error:", error.message));
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
    await page.waitForFunction(() => document.getElementById("login-code").textContent === "AB12CD");
    assert.match(await page.$eval("#telegram-login-link", e => e.href), /^https:\/\/t\.me\//);
    approved = true;
    await page.waitForFunction(() => !document.getElementById("console").hidden);
    assert.equal(await page.$$eval("#members tr", e => e.length), 3);
    assert.equal(await page.$$eval("#members img", e => e.length), 0);
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
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
    assert.equal(await page.$eval("#invite-url", e => e.value), "");
    await page.evaluate(() => window.__lateData());
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await page.$eval("#console", e => e.hidden), true);
    assert.equal(await page.$$eval("#members tr", e => e.length), 0);
    await page.close();
    console.log(`Admin ${name} interaction checks passed.`);
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
      if (!["admin.html", "admin.css", "admin.js", "dashboard.css"].includes(file)) {
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
