import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { createInterface } from "node:readline";
import puppeteer from "puppeteer";

// A lesson video in a real browser, end to end: the real Flask app on a disposable PostgreSQL schema,
// a video rendered by the real renderer and stored by the real pipeline (tests/web_media_server.py),
// real playback and seeking in Chromium, byte ranges, the Safari two-byte probe and access checks.
if (!process.env.TEST_DATABASE_URL) {
  if (process.env.CI) throw new Error("The lesson video browser check needs TEST_DATABASE_URL (provided in CI).");
  console.log("Lesson video browser check skipped: TEST_DATABASE_URL is not set.");
  process.exit(0);
}
const server = spawn(process.env.TEST_PYTHON || "python", [join("tests", "web_media_server.py")],
                     {stdio: ["pipe", "pipe", "inherit"]});
const info = JSON.parse(await new Promise((resolve, reject) => {
  createInterface({input: server.stdout}).once("line", resolve);
  server.once("exit", code => reject(new Error(`The test server stopped (${code}).`)));
}));
const {origin} = info;
const VIDEO = `/web/media/${info.video}`;
const browser = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  headless: true, args: process.platform === "linux" ? ["--no-sandbox"] : [],
});
const shots = process.env.WEB_SCREENSHOT_DIR;

async function open(token, viewport) {
  const context = await (browser.createBrowserContext || browser.createIncognitoBrowserContext).call(browser);
  const page = await context.newPage();
  page.on("pageerror", error => { throw error; });
  await page.setViewport(viewport);
  // The real session cookie: __Host- prefixed, so Secure and Path=/ (loopback counts as a secure origin).
  if (token) {
    await page.setCookie({name: info.cookie, value: token, url: origin, path: "/", secure: true, httpOnly: true,
                          sameSite: "Strict"});
  }
  return {context, page};
}
const statusOf = (page, path) => page.evaluate(async address => (await fetch(address, {cache: "no-store"})).status, path);

try {
  for (const [label, viewport] of [["mobile", {width: 390, height: 860}], ["desktop", {width: 1280, height: 900}]]) {
    const {context, page} = await open(info.learner, {...viewport, deviceScaleFactor: 1});
    const responses = [];
    page.on("response", response => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/web/media/")) {
        responses.push({path, status: response.status(), range: response.request().headers().range || null,
                        headers: response.headers()});
      }
    });
    await page.goto(origin + "/web");
    await page.waitForSelector("li.message.media video");
    // The lesson arrives in order: the video sits between the text before and after it.
    const order = (await page.$$eval("#feed > li", items => items.map(item => item.querySelector("video") ? "video" : item.textContent))).slice(-3);
    assert.equal(order.length, 3);
    assert.match(order[0], /Today's lesson/);
    assert.equal(order[1], "video");
    assert.match(order[2], /After the video/);
    const element = await page.$eval("li.message.media video", video => ({
      src: video.getAttribute("src"), poster: video.getAttribute("poster"), controls: video.controls,
      inline: video.playsInline, preload: video.preload, list: video.getAttribute("controlslist"),
    }));
    assert.deepEqual(element, {src: VIDEO, poster: `/web/media/${info.poster}`, controls: true, inline: true,
                               preload: "metadata", list: "nodownload"});
    const caption = await page.$eval("li.message.media figcaption", figure => figure.innerText);
    assert.match(caption, /How the load balancer routes requests/);
    assert.match(caption, /Reviewed authored explanation\. · Captioned walkthrough\./);
    assert.notEqual(await page.evaluate(() => document.createElement("video").canPlayType('video/mp4; codecs="avc1.64001F"')), "",
                    "this browser plays H.264 MP4");
    // Real playback, a seek near the end, and playback again from there.
    const played = await page.evaluate(async () => {
      const video = document.querySelector("li.message.media video");
      const until = (test, message) => new Promise((resolve, reject) => {
        const timer = setTimeout(() => { clearInterval(poll); reject(new Error(message)); }, 30000);
        const poll = setInterval(() => { if (test()) { clearTimeout(timer); clearInterval(poll); resolve(); } }, 50);
      });
      video.muted = true;
      await video.play();
      await until(() => video.currentTime > 1.2, "no playback progress");
      video.pause();
      const target = Math.max(0, video.duration - 4);
      const seeked = new Promise(resolve => video.addEventListener("seeked", resolve, {once: true}));
      video.currentTime = target;
      await seeked;
      const afterSeek = video.currentTime;
      await video.play();
      await until(() => video.ended || video.currentTime > target + 1, "no playback after seeking");
      return {duration: video.duration, target, afterSeek, width: video.videoWidth, height: video.videoHeight,
              error: video.error && video.error.code};
    });
    assert.equal(played.error, null);
    assert.ok(Math.abs(played.duration - info.duration) < 0.6, `duration ${played.duration} vs ${info.duration}`);
    assert.ok(Math.abs(played.afterSeek - played.target) < 0.6, "the seek landed where asked");
    assert.deepEqual([played.width, played.height], [1280, 720]);
    // The player itself fetched the video by byte ranges, and every response stayed private.
    assert.ok(responses.some(item => item.path === VIDEO && item.status === 206 && item.range), "ranged playback");
    for (const item of responses) {
      assert.equal(item.headers["cache-control"], "no-store, private");
      assert.equal(item.headers["cross-origin-resource-policy"], "same-origin");
    }
    // Safari's first request is a two-byte probe; then the whole file arrives intact.
    const checks = await page.evaluate(async path => {
      const probe = await fetch(path, {headers: {Range: "bytes=0-1"}, cache: "no-store"});
      const probeBytes = (await probe.arrayBuffer()).byteLength;
      const whole = await fetch(path, {cache: "no-store"});
      const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", await whole.arrayBuffer()));
      return {probe: [probe.status, probeBytes, probe.headers.get("content-range")],
              whole: [whole.status, whole.headers.get("content-type"), Array.from(digest, b => b.toString(16).padStart(2, "0")).join("")]};
    }, VIDEO);
    assert.deepEqual(checks.probe, [206, 2, `bytes 0-1/${info.bytes}`]);
    assert.deepEqual(checks.whole, [200, "video/mp4", info.sha256]);
    // The message fits the screen.
    const fit = await page.evaluate(() => {
      const box = document.querySelector("li.message.media video").getBoundingClientRect();
      return {scroll: document.scrollingElement.scrollWidth, width: innerWidth, right: box.right, ratio: box.width / box.height};
    });
    assert.ok(fit.scroll <= fit.width && fit.right <= fit.width, "no sideways scrolling");
    assert.ok(Math.abs(fit.ratio - 16 / 9) < 0.02, "the frame keeps its 16:9 shape");
    if (shots) {
      await page.evaluate(() => document.querySelector("li.message.media").scrollIntoView({block: "center"}));
      await page.screenshot({path: join(shots, `web-video-${label}.png`)});
    }
    if (label === "desktop") {
      // Signing out clears the conversation and ends access to the video.
      await page.click("#logout");
      await page.waitForFunction(() => !document.querySelector("video") && !document.getElementById("signin").hidden);
      assert.equal(await statusOf(page, VIDEO), 403);
    }
    await context.close();
  }
  // Another signed-in learner without this message, and a browser without a session, cannot fetch it.
  for (const [token, expected] of [[info.other, 404], [null, 403]]) {
    const {context, page} = await open(token, {width: 390, height: 860, deviceScaleFactor: 1});
    await page.goto(origin + "/web");
    assert.equal(await statusOf(page, VIDEO), expected);
    assert.equal(await statusOf(page, `/web/media/${"f".repeat(32)}`), token ? 404 : 403);
    await context.close();
  }
  console.log(`Real lesson video (${info.bytes} bytes, ${info.duration}s) played and seeked in Chromium on mobile and desktop; ` +
              "ranged requests, the two-byte probe, intact bytes, private headers, sign-out and other-learner refusal checked.");
} finally {
  await browser.close();
  server.stdin.end();
  await new Promise(resolve => (server.exitCode === null ? server.once("exit", resolve) : resolve()));
}
