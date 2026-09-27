import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

let available = true, invalidLink = false;
const requests = [];
const server = createServer(async (request, response) => {
  requests.push({method: request.method, url: request.url});
  if (request.url === "/join/config") {
    response.writeHead(200, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify({available, telegram_url: invalidLink ? "javascript:alert(1)" : "https://t.me/SkillCoachTestBot?start=request"}));
    return;
  }
  const file = request.url === "/join" ? "join.html" : request.url.replace("/static/", "");
  if (!["join.html", "join.js", "dashboard.css", "admin.css"].includes(file)) {
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
  for (const [name, width] of [["mobile", 390], ["desktop", 1100]]) {
    const page = await browser.newPage();
    await page.setViewport({width, height: 900});
    await page.setRequestInterception(true);
    page.on("request", request => request.url().startsWith(origin) ? request.continue() : request.abort());
    await page.goto(origin + "/join");
    await page.waitForFunction(() => !document.getElementById("request-access").hidden);
    assert.equal(await page.$eval("#request-access", a => a.href), "https://t.me/SkillCoachTestBot?start=request");
    assert.equal(await page.$$eval("input", nodes => nodes.length), 0);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path: join(process.env.DASHBOARD_SCREENSHOT_DIR, `join-${name}.png`), fullPage: true});
    }
    available = false;
    await page.reload();
    await page.waitForFunction(() => document.getElementById("join-status").textContent.includes("closed"));
    assert.equal(await page.$eval("#request-access", e => e.hidden), true);
    available = true; invalidLink = true;
    await page.reload();
    await page.waitForFunction(() => document.getElementById("join-status").classList.contains("error"));
    assert.equal(await page.$eval("#request-access", e => e.hidden), true);
    invalidLink = false;
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
    await page.close();
  }
  assert.ok(requests.every(request => request.method === "GET"));
  console.log("Public join mobile/desktop, closed state, invalid-link rejection and GET-only privacy checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
