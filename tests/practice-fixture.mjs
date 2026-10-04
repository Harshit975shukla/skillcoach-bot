// Practice page fixture: the real practice.html/css/js served with a fake /web API whose lesson data
// comes from the real Python builder (skillcoach.practice). Synthetic only: no learner, email or
// credential is involved. Responses carry the production Content-Security-Policy, so an inline style
// or script in the page would be blocked here exactly as in production.
//
// Used by tests/practice-browser.mjs. Run directly for a local preview of the page:
//   node tests/practice-fixture.mjs [port]      (then open http://127.0.0.1:<port>/web/practice)
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const CSRF = "synthetic-practice-csrf";
export const PROGRESS_KEY = "0123456789abcdef0123456789abcdef";
export const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; " +
  "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";

export function practiceData() {
  const script = `
import json
from skillcoach import practice
from skillcoach.catalog import TOPICS
featured = practice.FEATURED
derived = next(k for k in TOPICS if k.startswith("linux/"))
lessons, steps = {}, {}
for topic in (featured, derived):
    for item in practice._lessons(topic):
        view = practice.lesson(topic, item.id)
        lessons[topic + "|" + item.id] = view
        for found in practice.review([step["item"] for step in view["lesson"]["steps"]]):
            steps[found["item"]] = found
print(json.dumps({"catalog": practice.catalog(), "lessons": lessons, "steps": steps, "derived": derived}))
`;
  return JSON.parse(execFileSync(process.env.TEST_PYTHON || "python", ["-c", script],
    {encoding: "utf8", maxBuffer: 16 * 1024 * 1024}));
}

const STATIC = {
  "/web/practice": ["practice.html", "text/html; charset=utf-8"],
  "/static/practice.css": ["practice.css", "text/css"],
  "/static/practice.js": ["practice.js", "text/javascript"],
  "/static/dashboard.css": ["dashboard.css", "text/css"],
  "/static/lesson-content.js": ["lesson-content.js", "text/javascript"],
  "/static/icon-192.png": ["icon-192.png", "image/png"],
  "/static/apple-touch-icon.png": ["apple-touch-icon.png", "image/png"],
};

export async function startPracticeServer({data = practiceData(), port = 0} = {}) {
  const state = {authenticated: true, requests: [], lessonBodies: [], reviewBodies: [], hostile: false, failLesson: false};
  let origin = "";
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    const path = request.url.split("?")[0];
    state.requests.push(request.url);
    const json = (status, value) => {
      response.writeHead(status, {"Content-Type": "application/json", "Cache-Control": "no-store", "Content-Security-Policy": CSP});
      response.end(JSON.stringify(value));
    };
    if (path.startsWith("/web/") && path !== "/web/practice") {
      assert.equal(request.url.includes("?"), false, "no credentials or identity in URLs");
      if (path === "/web/session") {
        assert.equal(request.method, "GET");
        return state.authenticated ? json(200, {authenticated: true, csrf: CSRF, name: "Synthetic learner"})
          : json(403, {error: "Sign in with your email to continue."});
      }
      if (path === "/web/manifest.webmanifest") return json(200, {name: "SkillCoach", start_url: "/web", display: "standalone"});
      if (path === "/web/sw.js") { response.writeHead(404).end(); return; }
      assert.equal(request.method, "POST");
      assert.equal(request.headers["x-csrf-token"], CSRF, "practice data needs the session's CSRF token");
      if (origin) assert.equal(request.headers.origin, origin);
      if (!state.authenticated) return json(403, {error: "Sign in with your email to continue."});
      const body = raw ? JSON.parse(raw) : {};
      if (path === "/web/practice/catalog") {
        assert.deepEqual(body, {});
        const catalog = structuredClone(data.catalog);
        if (state.hostile) {
          const topic = catalog.modules.flatMap(m => m.topics).find(t => t.id === data.derived);
          topic.title = "<img src=x onerror=window.pwnedPractice=1> Hostile title";
        }
        return json(200, {...catalog, progress_key: PROGRESS_KEY});
      }
      if (path === "/web/practice/lesson") {
        assert.deepEqual(Object.keys(body).sort(), ["lesson", "topic"]);
        state.lessonBodies.push(body);
        if (state.failLesson) return json(503, {error: "SkillCoach is temporarily unavailable. Try again shortly."});
        const found = data.lessons[`${body.topic}|${body.lesson}`];
        if (!found) return json(404, {error: "Choose a lesson from the practice path."});
        const view = structuredClone(found);
        if (state.hostile) {
          view.topic.title = "<img src=x onerror=window.pwnedPractice=2> Hostile";
          const teach = view.lesson.steps.find(step => step.type === "teach");
          teach.title = "<script>window.pwnedPractice=3</script>";
          teach.body.unshift({type: "p", spans: [{t: "text", v: "<img src=x onerror=window.pwnedPractice=4>"}]});
        }
        return json(200, view);
      }
      if (path === "/web/practice/review") {
        assert.deepEqual(Object.keys(body), ["items"]);
        assert.ok(Array.isArray(body.items) && body.items.length >= 1 && body.items.length <= 20);
        state.reviewBodies.push(body);
        return json(200, {steps: body.items.map(item => data.steps[item]).filter(Boolean)});
      }
      return json(404, {error: "Unknown route"});
    }
    const selected = STATIC[path];
    if (!selected) { response.writeHead(404).end(); return; }
    response.writeHead(200, {"Content-Type": selected[1], "Content-Security-Policy": CSP, "Cache-Control": "no-store"});
    response.end(await readFile(join("skillcoach", "static", selected[0])));
  });
  await new Promise(resolve => server.listen(port, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  return {server, state, origin, data, close: () => new Promise(resolve => server.close(resolve))};
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.argv[2] || 8765);
  const {origin} = await startPracticeServer({port});
  console.log(`Practice preview (synthetic data): ${origin}/web/practice`);
}
