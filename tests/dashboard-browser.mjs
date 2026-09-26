import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

let denied = false;
const fixture = {
  profile: {name: "Synthetic learner", target_role: "Platform engineer", level: "intermediate", setup_complete: true},
  stats: {done: 4, pending: 2, total: 6, streak: 2, minutes_practiced: 65, answers_graded: 1},
  preferences: {paused: false, media: "video"},
  tasks: [
    {id: "test-task-1", title: "Explain health-based traffic routing", skill: "AWS EC2", estimated_minutes: 20,
      assigned_date: "2026-09-26", detail: "Sketch two availability zones.\nExplain how healthy capacity handles requests."},
    {id: "test-task-2", title: "Trace a Kubernetes readiness failure", skill: "Kubernetes networking",
      estimated_minutes: 15, assigned_date: "2026-09-26", detail: "Compare pod readiness and liveness."},
  ],
  plan: [{date: "2026-09-28", topic: "AWS EC2: instance health and replacement"},
         {date: "2026-09-29", topic: "Kubernetes: readiness and service routing"}],
  skills: [{skill: "AWS EC2", done: 3, total: 4}, {skill: "Kubernetes networking", done: 1, total: 2}],
  recent_interviews: [{question: "How would you diagnose an unhealthy web target?", score: 7,
                       feedback: "Separate instance status from application health."}],
  generated_at: new Date().toISOString(), auth_expires_at: Math.floor(Date.now() / 1000) + 300, private: true,
};
const server = createServer(async (request, response) => {
  if (request.url === "/app/data") {
    response.writeHead(denied ? 403 : 200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(denied ? {error: "Access was revoked. Reopen from Telegram."} : fixture));
    return;
  }
  const names = {"/app": ["dashboard.html", "text/html"], "/static/dashboard.css": ["dashboard.css", "text/css"],
                 "/static/dashboard.js": ["dashboard.js", "text/javascript"]};
  const selected = names[request.url];
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
    assert.equal(await page.$$eval("#tasks li", e => e.length), 2);
    assert.equal(await page.evaluate(() => document.body.classList.contains("telegram-light")), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `dashboard-${label}.png`), fullPage: true});
    }
    fixture.profile.name = "<img src=x onerror='window.pwned=true'>";
    await page.click("#refresh");
    await page.waitForFunction(() => document.getElementById("learner-name").textContent.startsWith("<img"));
    assert.equal(await page.$eval("#learner-name", e => e.children.length), 0);
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    denied = true;
    await page.click("#refresh");
    await page.waitForFunction(() => document.getElementById("content").hidden);
    assert.equal(await page.$$eval("#tasks li", e => e.length), 0);
    assert.match(await page.$eval("#notice", e => e.textContent), /revoked/);
    denied = false;
    fixture.profile.name = "Synthetic learner";
    await page.evaluate(() => { window.Telegram.WebApp.initData = ""; });
    await page.click("#refresh");
    assert.match(await page.$eval("#notice", e => e.textContent), /Open this private dashboard/);
    await page.close();
  }
  console.log("Private dashboard mobile/desktop, text escaping, revocation clearing and direct-open checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
