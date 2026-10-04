import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

// The installable web app in a real browser: the real service worker, offline page, manifest and
// icons, and the notification controls. Headless Chrome has no push service, so the browser's
// PushManager and permission prompt are simulated; everything else is real. Synthetic data only.
const {manifest, key} = JSON.parse(execFileSync(process.env.TEST_PYTHON || "python", ["-c",
  "import json; from skillcoach.web_routes import MANIFEST; from skillcoach.web_push import generate_keys; " +
  "print(json.dumps({'manifest': MANIFEST, 'key': generate_keys()[0]}))"], {encoding: "utf8"}));
const CSRF = "synthetic-web-csrf";
const PRIVATE = "PRIVATE-LESSON-TEXT-4711";
const SHELL = ["/web/offline", "/static/dashboard.css", "/static/web.css", "/static/icon-192.png"];
let state;
const reset = (overrides = {}) => {
  state = {signedIn: true, down: false, log: [], subscribes: [], syncs: [], unsubscribes: [], syncAnswer: true,
           failUnsubscribe: false, ...overrides};
};
reset();
const files = {
  "/web": ["web.html", "text/html"], "/web/offline": ["web-offline.html", "text/html"],
  "/web/sw.js": ["web-sw.js", "text/javascript"], "/static/web.js": ["web.js", "text/javascript"],
  "/static/web.css": ["web.css", "text/css"], "/static/dashboard.css": ["dashboard.css", "text/css"],
  "/static/lesson-content.js": ["lesson-content.js", "text/javascript"],
};
for (const name of ["icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "badge-72.png"]) {
  files["/static/" + name] = [name, "image/png"];
}
const session = () => ({authenticated: true, csrf: CSRF, name: "Synthetic learner", push_key: key,
                        expires_at: new Date(Date.now() + 86400000).toISOString()});
const server = createServer(async (request, response) => {
  const path = request.url.split("?")[0];
  state.log.push(`${request.method} ${path}`);
  if (state.down) { request.socket.destroy(); return; }
  let raw = "";
  for await (const chunk of request) raw += chunk;
  const json = (status, value) => {
    response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store"});
    response.end(JSON.stringify(value));
  };
  if (path === "/web/manifest.webmanifest") {
    response.writeHead(200, {"Content-Type": "application/manifest+json"});
    response.end(JSON.stringify(manifest));
    return;
  }
  if (path === "/web/session") return state.signedIn ? json(200, session()) : json(403, {error: "Sign in with your email to continue."});
  if (path === "/web/login/start") {
    return json(200, {pending: true, expires_at: new Date(Date.now() + 600000).toISOString(),
                      resend_at: new Date(Date.now() + 60000).toISOString()});
  }
  if (path === "/web/login/verify") { state.signedIn = true; return json(200, session()); }
  if (path === "/web/logout") { state.signedIn = false; return json(200, {logged_out: true}); }
  if (path === "/web/feed") {
    assert.equal(request.headers["x-csrf-token"], CSRF);
    return json(200, {messages: [{id: 1, kind: "text", text: PRIVATE, buttons: [], at: new Date().toISOString()}],
                      working: false, older: false});
  }
  if (path.startsWith("/web/push/")) {
    assert.equal(request.method, "POST");
    assert.equal(request.headers["x-csrf-token"], CSRF);
    assert.equal(request.headers.origin, origin);
    assert.equal(request.url.includes("?"), false);
    const body = JSON.parse(raw);
    if (path === "/web/push/subscribe") {
      assert.deepEqual(Object.keys(body).sort(), ["auth", "endpoint", "p256dh"]);
      state.subscribes.push(body);
      return json(200, {subscribed: true});
    }
    if (path === "/web/push/sync") {
      assert.deepEqual(Object.keys(body).sort(), ["auth", "endpoint", "p256dh"]);
      state.syncs.push(body);
      return json(200, {subscribed: state.syncAnswer});
    }
    if (path === "/web/push/unsubscribe") {
      assert.deepEqual(Object.keys(body), ["endpoint"]);
      if (state.failUnsubscribe) { request.socket.destroy(); return; }
      state.unsubscribes.push(body.endpoint);
      return json(200, {subscribed: false});
    }
  }
  const selected = files[path];
  if (!selected) { response.writeHead(404).end(); return; }
  const headers = {"Content-Type": selected[1]};
  if (path === "/web/sw.js") headers["Service-Worker-Allowed"] = "/web";
  response.writeHead(200, headers);
  response.end(await readFile(join("skillcoach", "static", selected[0])));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  headless: true, args: process.platform === "linux" ? ["--no-sandbox"] : [],
});
const shots = process.env.WEB_SCREENSHOT_DIR;

// Simulates the browser's push service and permission prompt, keeping the rest of the page real.
function simulatePush(config) {
  const decode = text => {
    const base = text.replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(base + "=".repeat((4 - base.length % 4) % 4)), c => c.charCodeAt(0));
  };
  const memory = window.__push = {permission: config.permission, requests: 0, subscribed: 0, unsubscribed: 0,
                                  unsubscribeResult: true, subscription: null, key: null};
  Object.defineProperty(Notification, "permission", {configurable: true, get: () => memory.permission});
  Notification.requestPermission = async () => {
    memory.requests++;
    if (memory.permission === "default") memory.permission = "granted";
    return memory.permission;
  };
  const make = endpoint => ({
    endpoint,
    options: {get applicationServerKey() { return memory.key; }},
    toJSON: () => ({endpoint, expirationTime: null, keys: {p256dh: "BPsyntheticP256dh", auth: "syntheticAuth"}}),
    async unsubscribe() {
      memory.unsubscribed++;
      if (memory.unsubscribeResult === true) memory.subscription = null;
      return memory.unsubscribeResult;
    },
  });
  if (config.existing) {
    memory.subscription = make(config.existing);
    memory.key = config.keyMatches ? decode(config.key) : new Uint8Array(65).fill(4);
  }
  PushManager.prototype.getSubscription = async () => memory.subscription;
  PushManager.prototype.subscribe = async options => {
    memory.subscribed++;
    memory.key = new Uint8Array(options.applicationServerKey);
    memory.subscription = make(`https://fcm.googleapis.com/fcm/send/synthetic-${memory.subscribed}`);
    return memory.subscription;
  };
}

async function open(config, {userAgent, noPush = false} = {}) {
  const context = await (browser.createBrowserContext || browser.createIncognitoBrowserContext).call(browser);
  const page = await context.newPage();
  page.on("pageerror", error => { throw error; });
  await page.setViewport({width: 390, height: 860, deviceScaleFactor: 1});
  if (userAgent) await page.setUserAgent(userAgent);
  if (noPush) await page.evaluateOnNewDocument(() => { delete window.PushManager; });
  else if (config) await page.evaluateOnNewDocument(simulatePush, config);
  return {context, page};
}
const pressed = page => page.$eval("#notify", e => e.getAttribute("aria-pressed"));
const noticeText = page => page.$eval("#notice", e => e.textContent);

// Brand, bell, Dashboard and Sign out stay inside the screen, never overlap and keep 44px targets.
// They share the brand's line whenever their natural widths fit; otherwise the actions sit on a
// right-aligned row below the brand. Returns whether everything fitted on one line.
async function checkHeader(page, label) {
  const layout = await page.evaluate(() => {
    const box = element => element.getBoundingClientRect().toJSON();
    const header = document.querySelector(".header");
    const brand = document.querySelector(".brand");
    const actions = document.querySelector(".header-actions");
    const items = [...actions.children].filter(element => !element.hidden);
    const widths = items.map(element => box(element).width).reduce((sum, width) => sum + width, 0);
    const need = box(brand).width + parseFloat(getComputedStyle(header).columnGap) + widths
      + parseFloat(getComputedStyle(actions).columnGap) * (items.length - 1);
    return {
      width: innerWidth, scroll: document.scrollingElement.scrollWidth, fits: need <= box(header).width,
      header: box(header), brand: box(brand), items: items.map(element => ({id: element.id, ...box(element)})),
    };
  });
  assert.ok(layout.scroll <= layout.width, `${label}: no sideways scrolling`);
  assert.deepEqual(layout.items.map(item => item.id), ["notify", "practice-link", "dashboard-link", "logout"], label);
  const middle = item => (item.top + item.bottom) / 2;
  layout.items.forEach((item, index) => {
    assert.ok(item.left >= 0 && item.right <= layout.width, `${label}: ${item.id} inside the screen`);
    assert.ok(item.height >= 44 && item.width >= 44, `${label}: ${item.id} keeps a 44px target`);
    for (const other of layout.items.slice(index + 1)) {
      const apart = item.right <= other.left || other.right <= item.left
        || item.bottom <= other.top || other.bottom <= item.top;
      assert.ok(apart, `${label}: ${item.id} and ${other.id} do not overlap`);
    }
    if (layout.fits) assert.ok(Math.abs(middle(item) - middle(layout.brand)) < 2, `${label}: ${item.id} beside the brand`);
    else assert.ok(item.top >= layout.brand.bottom, `${label}: ${item.id} below the brand`);
  });
  if (!layout.fits) {
    const last = layout.items[layout.items.length - 1];
    assert.ok(Math.abs(last.right - layout.header.right) < 1, `${label}: actions aligned right`);
  }
  return layout.fits;
}

try {
  // 1. The real service worker caches only the public offline shell, and offline shows a generic,
  //    styled page: never the previous conversation.
  {
    reset();
    const {context, page} = await open(null);
    await page.goto(origin + "/web");
    await page.waitForFunction(text => document.getElementById("feed").textContent.includes(text), {}, PRIVATE);
    const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
    assert.equal(scope, origin + "/web");
    await page.reload();
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    await page.waitForFunction(text => document.getElementById("feed").textContent.includes(text), {}, PRIVATE);
    const cached = await page.evaluate(async () => {
      const result = {};
      for (const name of await caches.keys()) {
        result[name] = (await (await caches.open(name)).keys()).map(r => new URL(r.url).pathname + new URL(r.url).search);
      }
      return result;
    });
    assert.deepEqual(Object.keys(cached), ["skillcoach-web-v1"]);
    assert.deepEqual(cached["skillcoach-web-v1"].sort(), [...SHELL].sort());
    // The manifest and every icon are real and the right size.
    const installed = await page.evaluate(async () => {
      const link = document.querySelector('link[rel="manifest"]');
      const data = await (await fetch(link.href)).json();
      const icons = [];
      for (const icon of data.icons) {
        const image = new Image();
        image.src = icon.src;
        await image.decode();
        icons.push([icon.sizes, `${image.naturalWidth}x${image.naturalHeight}`, icon.purpose]);
      }
      return {data, icons, touch: document.querySelector('link[rel="apple-touch-icon"]').getAttribute("href")};
    });
    assert.deepEqual(installed.data, manifest);
    assert.ok(installed.icons.every(([sizes, actual]) => sizes === actual));
    assert.equal(installed.touch, "/static/apple-touch-icon.png");
    state.down = true;
    for (const path of ["/web", "/web/dashboard"]) {
      await page.goto(origin + path);
      await page.waitForFunction(() => document.querySelector("h1") && /offline/.test(document.querySelector("h1").textContent));
      assert.equal((await page.content()).includes(PRIVATE), false, "the offline page shows nobody's messages");
      // Both stylesheets came from the cache: the brand and the button use their own styles.
      assert.equal(await page.$eval(".brand", e => getComputedStyle(e).fontWeight), "750");
      assert.equal(await page.$eval(".button-link", e => getComputedStyle(e).minHeight), "44px");
    }
    if (shots) await page.screenshot({path: join(shots, "web-offline-mobile.png")});
    state.down = false;
    await context.close();
    console.log("Real service worker: public-shell-only cache, manifest and icons, styled generic offline page.");
  }
  // 2. Permission is asked only after a tap; turning off is reported truthfully; sign-out removes
  //    the device before the session ends.
  {
    reset();
    const {context, page} = await open({permission: "default"});
    await page.goto(origin + "/web");
    await page.waitForFunction(() => !document.getElementById("offer").hidden);
    assert.equal(await page.evaluate(() => window.__push.requests), 0, "no permission prompt on load");
    assert.match(await page.$eval("#offer-text", e => e.textContent), /notification on this device/);
    assert.equal(await pressed(page), "false");
    // The header never overflows at phone widths, whatever the platform fonts; larger text makes
    // the actions take their own row (forced here so every platform checks that fallback).
    for (const width of [390, 360, 320]) {
      await page.setViewport({width, height: 860, deviceScaleFactor: 1});
      await checkHeader(page, width);
    }
    await page.setViewport({width: 390, height: 860, deviceScaleFactor: 1});
    await page.evaluate(() => { document.documentElement.style.fontSize = "135%"; });
    assert.equal(await checkHeader(page, "larger text"), false, "larger text wraps the actions");
    if (shots) await page.screenshot({path: join(shots, "web-header-larger-text-mobile.png"), clip: {x: 0, y: 0, width: 390, height: 260}});
    await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
    if (shots) await page.screenshot({path: join(shots, "web-push-offer-mobile.png")});
    await page.click("#offer-go");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "true");
    assert.deepEqual(await page.evaluate(() => [window.__push.requests, window.__push.subscribed]), [1, 1]);
    assert.equal(state.subscribes.length, 1);
    assert.equal(state.subscribes[0].endpoint, "https://fcm.googleapis.com/fcm/send/synthetic-1");
    assert.equal(await page.$eval("#offer", e => e.hidden), true);
    if (shots) await page.screenshot({path: join(shots, "web-push-on-mobile.png")});
    // Neither the browser nor the server confirms: the page says so and keeps the bell on.
    await page.evaluate(() => { window.__push.unsubscribeResult = false; });
    state.failUnsubscribe = true;
    await page.click("#notify");
    await page.waitForFunction(() => /could not be turned off/.test(document.getElementById("notice").textContent));
    assert.equal(await pressed(page), "true");
    // Trying again once the connection works turns it off.
    await page.evaluate(() => { window.__push.unsubscribeResult = true; });
    state.failUnsubscribe = false;
    await page.click("#notify");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "false");
    assert.match(await noticeText(page), /off for this device/);
    assert.deepEqual(state.unsubscribes, ["https://fcm.googleapis.com/fcm/send/synthetic-1"]);
    // Either confirmation is enough: a browser unsubscribe with the server unreachable.
    await page.click("#notify");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "true");
    state.failUnsubscribe = true;
    await page.click("#notify");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "false");
    state.failUnsubscribe = false;
    // A browser that blocks notifications never subscribes.
    await page.evaluate(() => { window.__push.permission = "denied"; });
    const before = await page.evaluate(() => window.__push.subscribed);
    await page.click("#notify");
    await page.waitForFunction(() => /blocked/.test(document.getElementById("notice").textContent));
    assert.equal(await page.evaluate(() => window.__push.subscribed), before);
    // Sign-out removes this browser's device first, then ends the session.
    await page.evaluate(() => { window.__push.permission = "granted"; });
    await page.click("#notify");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "true");
    state.log = [];
    await page.click("#logout");
    await page.waitForFunction(() => !document.getElementById("signin").hidden);
    const order = state.log.filter(entry => entry.startsWith("POST /web/push/unsubscribe") || entry === "POST /web/logout");
    assert.deepEqual(order, ["POST /web/push/unsubscribe", "POST /web/logout"]);
    assert.equal(await page.evaluate(() => window.__push.subscription), null);
    assert.equal(await page.$eval("#notify", e => e.hidden), true);
    await context.close();
    console.log("Notifications: tap-only permission, truthful opt-out, blocked permission and sign-out order.");
  }
  // 3. A shared browser: a subscription left by another account is dropped, never kept or claimed;
  //    this account's own device resumes without asking again; an old key is replaced.
  {
    const previous = "https://fcm.googleapis.com/fcm/send/previous-account";
    reset({syncAnswer: false});
    let {context, page} = await open({permission: "granted", existing: previous, keyMatches: true, key});
    await page.goto(origin + "/web");
    await page.waitForFunction(() => window.__push.unsubscribed === 1);
    assert.deepEqual(state.syncs.map(body => body.endpoint), [previous]);
    assert.equal(await pressed(page), "false");
    assert.equal(await page.evaluate(() => window.__push.requests), 0);
    await context.close();
    reset({syncAnswer: true});
    ({context, page} = await open({permission: "granted", existing: previous, keyMatches: true, key}));
    await page.goto(origin + "/web");
    await page.waitForFunction(() => document.getElementById("notify").getAttribute("aria-pressed") === "true");
    assert.deepEqual(await page.evaluate(() => [window.__push.requests, window.__push.unsubscribed]), [0, 0]);
    await context.close();
    reset();
    ({context, page} = await open({permission: "granted", existing: previous, keyMatches: false, key}));
    await page.goto(origin + "/web");
    await page.waitForFunction(() => window.__push.unsubscribed === 1);
    assert.deepEqual(state.syncs, []);
    assert.deepEqual(state.unsubscribes, [previous]);
    assert.equal(await pressed(page), "false");
    await context.close();
    console.log("Shared browser: another account's subscription dropped, own device resumed, old key replaced.");
  }
  // 4. iPhone or iPad Safari without Home Screen install has no push: honest guidance, no bell.
  {
    reset();
    const {context, page} = await open(null, {
      noPush: true,
      userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    });
    await page.goto(origin + "/web");
    await page.waitForFunction(() => !document.getElementById("offer").hidden);
    assert.match(await page.$eval("#offer-text", e => e.textContent), /iOS 16\.4 or later.*Add to Home Screen/);
    assert.equal(await page.$eval("#notify", e => e.hidden), true);
    if (shots) await page.screenshot({path: join(shots, "web-ios-offer-mobile.png")});
    await page.click("#offer-go");
    assert.equal(await page.$eval("#offer", e => e.hidden), true);
    await context.close();
    console.log("iPhone without Home Screen install: honest guidance and no notification control.");
  }
  console.log("Installable web app browser checks passed.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
