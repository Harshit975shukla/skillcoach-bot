import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

// The real service worker source, run in a sandbox with recorded caches, clients and notifications.
const source = await readFile("skillcoach/static/web-sw.js", "utf8");
const ORIGIN = "https://coach.example.test";
const SHELL = ["/web/offline", "/static/dashboard.css", "/static/web.css", "/static/icon-192.png"];

function worker({network = "up", windows = [], addAllFails = false, existing = []} = {}) {
  const listeners = {}, store = new Map();
  const calls = {added: [], deleted: [], put: 0, notifications: [], opened: [], skipped: 0, claimed: 0, fetched: []};
  for (const name of existing) store.set(name, new Map([[ORIGIN + "/old", "old"]]));
  const open = async name => {
    if (!store.has(name)) store.set(name, new Map());
    const cache = store.get(name);
    return {
      async addAll(urls) {
        calls.added.push([name, [...urls]]);
        if (addAllFails) throw new TypeError("network");
        for (const url of urls) cache.set(new URL(url, ORIGIN).href, {cached: url});
      },
      async put() { calls.put++; },
    };
  };
  const caches = {
    open,
    async keys() { return [...store.keys()]; },
    async delete(name) { calls.deleted.push(name); return store.delete(name); },
    async match(url) {
      const href = new URL(url, ORIGIN).href;
      for (const cache of store.values()) if (cache.has(href)) return cache.get(href);
      return undefined;
    },
  };
  const self = {
    location: new URL(ORIGIN + "/web/sw.js"),
    addEventListener(type, listener) { listeners[type] = listener; },
    skipWaiting() { calls.skipped++; return Promise.resolve(); },
    clients: {
      async claim() { calls.claimed++; },
      async matchAll(options) {
        assert.deepEqual(JSON.parse(JSON.stringify(options)), {type: "window", includeUncontrolled: true});
        return windows;
      },
      async openWindow(url) { calls.opened.push(url); return {url}; },
    },
    // Values made inside the sandbox belong to another realm; record plain copies.
    registration: { async showNotification(title, options) { calls.notifications.push([title, JSON.parse(JSON.stringify(options))]); } },
  };
  const fetch = async request => {
    calls.fetched.push(request.url);
    if (network === "down") throw new TypeError("Failed to fetch");
    return {network: request.url};
  };
  vm.runInContext(source, vm.createContext({self, caches, fetch, URL, Response: {error: () => ({error: true})}}));
  return {listeners, store, calls};
}

async function dispatch(listeners, type, init = {}) {
  const waits = [];
  let answer = null;
  listeners[type]({...init, waitUntil: promise => waits.push(promise), respondWith: promise => { answer = promise; }});
  await Promise.all(waits);
  return answer === null ? null : await answer;
}

const get = (path, mode = "cors", url = ORIGIN + path) => ({request: {url, method: "GET", mode}});

// Install stores exactly the public offline shell; a failure there still installs (notifications work).
{
  const {listeners, calls} = worker();
  await dispatch(listeners, "install");
  assert.deepEqual(calls.added, [["skillcoach-web-v1", SHELL]]);
  assert.equal(calls.skipped, 1);
  const broken = worker({addAllFails: true});
  await dispatch(broken.listeners, "install");
  assert.equal(broken.calls.skipped, 1);
}
// Activate removes only this app's older caches, never another app's.
{
  const {listeners, calls, store} = worker({existing: ["skillcoach-web-v0", "other-app", "skillcoach-web-v1", "skillcoach-admin"]});
  await dispatch(listeners, "activate");
  assert.deepEqual(calls.deleted, ["skillcoach-web-v0"]);
  assert.deepEqual([...store.keys()].sort(), ["other-app", "skillcoach-admin", "skillcoach-web-v1"]);
  assert.equal(calls.claimed, 1);
}
// Fetch: pages and APIs always come from the network; only failures of a page or the offline
// page's own public assets use the cache, and nothing is ever written to it.
{
  const online = worker();
  await dispatch(online.listeners, "install");
  assert.deepEqual(await dispatch(online.listeners, "fetch", get("/web", "navigate")), {network: ORIGIN + "/web"});
  const offline = worker({network: "down"});
  await dispatch(offline.listeners, "install");
  assert.deepEqual(await dispatch(offline.listeners, "fetch", get("/web", "navigate")), {cached: "/web/offline"});
  assert.deepEqual(await dispatch(offline.listeners, "fetch", get("/web/dashboard", "navigate")), {cached: "/web/offline"});
  assert.deepEqual(await dispatch(offline.listeners, "fetch", get("/static/web.css")), {cached: "/static/web.css"});
  assert.deepEqual(await dispatch(offline.listeners, "fetch", get("/static/icon-192.png")), {cached: "/static/icon-192.png"});
  for (const event of [
    get("/web/session"),
    get("/web/media/0123456789abcdef0123456789abcdef"),
    get("/static/web.js"),
    get("/static/web.css?v=2"),
    get("/web/offline"),
    get("/static/web.css", "cors", "https://evil.example/static/web.css"),
    {request: {url: ORIGIN + "/web/feed", method: "POST", mode: "cors"}},
    {request: {url: ORIGIN + "/web", method: "POST", mode: "navigate"}},
  ]) {
    assert.equal(await dispatch(offline.listeners, "fetch", event), null, event.request.url);
  }
  assert.equal(online.calls.put + offline.calls.put, 0, "nothing is cached at run time");
  assert.deepEqual([...offline.store.get("skillcoach-web-v1").keys()].map(url => new URL(url).pathname).sort(), [...SHELL].sort());
}
// Push: only the reminder kind is read; the text is fixed whatever else the message carries.
{
  const {listeners, calls} = worker();
  const data = value => ({data: {json: () => { if (value instanceof Error) throw value; return value; }}});
  await dispatch(listeners, "push", data({push: "quiz"}));
  await dispatch(listeners, "push", data({push: "lesson", title: "Your score: 2/5", body: "IAM topic", url: "https://evil.example", tag: "x"}));
  await dispatch(listeners, "push", data(new SyntaxError("not json")));
  await dispatch(listeners, "push", data({push: "__proto__"}));
  await dispatch(listeners, "push", data({push: "constructor"}));
  await dispatch(listeners, "push", {data: null});
  const icons = {icon: "/static/icon-192.png", badge: "/static/badge-72.png"};
  assert.deepEqual(calls.notifications, [
    ["SkillCoach", {body: "Your quiz is ready.", tag: "skillcoach-quiz", ...icons}],
    ["SkillCoach", {body: "Today's lesson is ready.", tag: "skillcoach-lesson", ...icons}],
    ...Array(4).fill(["SkillCoach", {body: "Open SkillCoach to continue.", tag: "skillcoach-update", ...icons}]),
  ]);
}
// A tap always goes to the conversation at /web on this origin, never to a URL from the message.
{
  const client = (url, {navigable = true, fails = false} = {}) => {
    const record = {url, focused: 0, navigated: []};
    record.focus = async () => { record.focused++; return record; };
    if (navigable) {
      record.navigate = async target => {
        record.navigated.push(target);
        if (fails) throw new TypeError("not controlled");
        return {url: target, focus: async () => { record.focused++; return record; }};
      };
    }
    return record;
  };
  const tap = async windows => {
    const run = worker({windows});
    await dispatch(run.listeners, "notificationclick", {
      notification: {close() {}, data: {url: "https://evil.example/phish"}},
    });
    return run.calls;
  };
  const conversation = client(ORIGIN + "/web"), dashboard = client(ORIGIN + "/web/dashboard");
  let calls = await tap([dashboard, conversation, client("https://evil.example/web")]);
  assert.equal(conversation.focused, 1);
  assert.deepEqual(dashboard.navigated, []);
  assert.deepEqual(calls.opened, []);
  const elsewhere = client(ORIGIN + "/web/dashboard");
  calls = await tap([client(ORIGIN + "/admin"), elsewhere]);
  assert.deepEqual(elsewhere.navigated, [ORIGIN + "/web"]);
  assert.equal(elsewhere.focused, 1);
  assert.deepEqual(calls.opened, []);
  const uncontrolled = client(ORIGIN + "/web/dashboard", {fails: true});
  calls = await tap([uncontrolled]);
  assert.deepEqual(calls.opened, [ORIGIN + "/web"]);
  calls = await tap([client("https://evil.example/web")]);
  assert.deepEqual(calls.opened, [ORIGIN + "/web"]);
  calls = await tap([]);
  assert.deepEqual(calls.opened, [ORIGIN + "/web"]);
}
console.log("Service worker install, cache, offline, fixed-text push and fixed-destination click checks passed.");
