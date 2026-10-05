// Practice page (/web/practice) in a real browser against tests/practice-fixture.mjs: synthetic data
// built by the real Python practice builder, the production CSP, no network beyond the fixture.
import assert from "node:assert/strict";
import { join } from "node:path";
import puppeteer from "puppeteer";
import { PROGRESS_KEY, startPracticeServer } from "./practice-fixture.mjs";

const fixture = await startPracticeServer();
const {origin, state, data} = fixture;
const STORE_KEY = "skillcoach.practice.v1." + PROGRESS_KEY;
const FEATURED = data.catalog.featured;
const shots = process.env.PRACTICE_SCREENSHOT_DIR;
const plain = spans => (spans || []).map(span => String(span.v)).join("");
const allSteps = Object.values(data.lessons).flatMap(view => view.lesson.steps);
const stepOf = item => allSteps.find(step => step.item === item) || data.steps[item];

const browser = await puppeteer.launch({
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  headless: true, args: process.platform === "linux" ? ["--no-sandbox"] : [],
});

async function open(width, height, scheme = "light") {
  const page = await browser.newPage(), problems = [];
  page.on("pageerror", error => problems.push("pageerror: " + error.message));
  page.on("console", message => {
    // Expected 403/503 answers are logged by the browser as failed loads; scripts must log nothing.
    // Chrome logs "Manifest: ... Syntax error." when a reload cuts off the manifest fetch.
    if (message.type() === "error"
        && !message.text().startsWith("Failed to load resource")
        && !message.text().startsWith("Manifest:")) problems.push("console: " + message.text());
  });
  // PRACTICE_CPU_THROTTLE=4 (for example) slows the page like a busy CI runner, to shake out timing bugs.
  if (process.env.PRACTICE_CPU_THROTTLE) await page.emulateCPUThrottling(Number(process.env.PRACTICE_CPU_THROTTLE));
  await page.setViewport({width, height, deviceScaleFactor: 1});
  await page.emulateMediaFeatures([{name: "prefers-reduced-motion", value: "reduce"},
                                   {name: "prefers-color-scheme", value: scheme}]);
  await page.setRequestInterception(true);
  page.on("request", request => request.url().startsWith(origin) ? request.continue() : request.abort());
  await page.evaluateOnNewDocument(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", event => window.__csp.push(event.violatedDirective));
  });
  return {page, problems};
}
const snap = async (page, name) => { if (shots) await page.screenshot({path: join(shots, name + ".png")}); };
const noOverflow = async (page, label) => assert.ok(
  await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${label}: no sideways scrolling`);
const shown = (page, selector) => page.$eval(selector, element => !element.closest("[hidden]")).catch(() => false);
const text = (page, selector) => page.$eval(selector, element => element.textContent.replace(/\s+/g, " ").trim());
const item = page => page.$eval("#stage .step", element => element.dataset.item);
async function clickText(page, selector, wanted) {
  const handles = await page.$$(selector);
  for (const handle of handles) {
    const value = await handle.evaluate(element => element.hidden || element.disabled ? null
      : (element.querySelector(".option-text") || element).textContent.replace(/\s+/g, " ").trim());
    if (value === wanted.replace(/\s+/g, " ").trim()) { await handle.click(); return; }
  }
  throw new Error(`No ${selector} reads "${wanted}"`);
}
async function stepChanged(page, before) {
  await page.waitForFunction(previous => {
    const step = document.querySelector("#stage .step");
    return !document.getElementById("summary").hidden || (step && step.dataset.item !== previous)
      || (step && step.dataset.repeat !== undefined);
  }, {}, before);
}

// Answers the current step (correctly unless told otherwise) and returns what it was.
async function answer(page, {wrong = false, guess = false, keyboard = false, label = ""} = {}) {
  const id = await item(page), step = stepOf(id);
  assert.ok(step, "unknown step " + id);
  if (guess) await page.click("#guess");
  if (step.type === "teach") {
    assert.equal(await text(page, "#check"), "Continue");
    await page.click("#check");
    return step;
  }
  if (step.type === "choice") {
    const target = step.options.find(option => option.correct !== wrong);
    if (keyboard) {
      const index = await page.$$eval("#stage .option .option-text", (nodes, wanted) =>
        nodes.findIndex(node => node.textContent.replace(/\s+/g, " ").trim() === wanted), plain(target.text));
      await page.focus("#stage .step-heading");
      await page.keyboard.press(String(index + 1));
      await page.keyboard.press("Enter");
    } else await clickText(page, "#stage .option", plain(target.text));
  } else if (step.type === "truefalse") {
    await clickText(page, "#stage .option", (step.answer !== wrong) ? "True" : "False");
  } else if (step.type === "match") {
    if (wrong) {
      await clickText(page, ".match-col .tile", plain(step.pairs[0][0]));
      await clickText(page, ".match-col .tile", plain(step.pairs[1][1]));
      assert.equal(await page.$eval(".match-live", element => element.textContent), "Not a pair. Try again.");
    }
    for (const [left, right] of step.pairs) {
      await clickText(page, ".match-col .tile", plain(left));
      await clickText(page, ".match-col .tile", plain(right));
    }
  } else if (step.type === "order") {
    const order = wrong ? [...step.steps].reverse() : step.steps;
    for (const spans of order) await clickText(page, ".order-bank .tile", plain(spans));
  } else if (step.type === "fill") {
    const tokens = wrong ? step.tokens.filter(token => !step.answer.includes(token)).slice(0, step.answer.length) : step.answer;
    for (const token of tokens) await clickText(page, ".fill-bank .token", token);
  } else if (step.type === "spot") {
    const index = wrong ? step.lines.findIndex((line, n) => line.trim() && !step.answers.includes(n)) : step.answers[0];
    await (await page.$$(".spot-line"))[index].click();
  } else if (step.type === "type") {
    await page.type("#type-answer", wrong ? "not the answer" : step.answer);
  } else if (step.type === "scenario") {
    for (const [n, stage] of step.stages.entries()) {
      const right = stage.options.find(option => option.correct), miss = stage.options.find(option => !option.correct);
      if (wrong && n === 0) await clickText(page, ".scenario-stage:last-of-type .option", plain(miss.text));
      await clickText(page, ".scenario-stage:last-of-type .option", plain(right.text));
    }
  } else if (step.type === "explain") {
    await page.type("#explain-text", "A synthetic answer typed only for the test.");
    assert.equal(await text(page, "#check"), "Compare with key points");
    await page.click("#check");
    await page.waitForSelector(".key-points");
    const boxes = await page.$$(".points input");
    for (const box of boxes.slice(0, wrong ? 0 : Math.ceil(boxes.length / 2))) await box.click();
    if (label) await snap(page, `practice-explain-${label}`);
    await page.click("#check");
    return step;
  }
  if (!keyboard) {
    assert.equal(await page.$eval("#check", element => element.disabled), false, `${step.type}: Check is enabled`);
    await page.click("#check");
  }
  await page.waitForSelector("#feedback:not([hidden])");
  return step;
}
async function next(page, keyboard = false) {
  if (keyboard) await page.keyboard.press("Enter");
  else await page.click("#next");
}

try {
  // 1. Signed out: a clear way back to sign-in, and no practice data is requested.
  {
    state.authenticated = false;
    const {page, problems} = await open(390, 844);
    await page.goto(origin + "/web/practice");
    await page.waitForSelector("#signed-out:not([hidden])");
    assert.equal(await page.$eval("#signed-out a", element => element.getAttribute("href")), "/web");
    assert.equal(state.requests.some(url => url.startsWith("/web/practice/")), false);
    assert.deepEqual(problems, []);
    await page.close();
    state.authenticated = true;
  }

  // 2. Desktop, light: the path, a whole lesson with a mistake, its repair, a guess, the keyboard and
  //    the self-check; then the summary, saved progress and the next lesson unlocked.
  {
    const {page, problems} = await open(1280, 900, "light");
    await page.goto(origin + "/web/practice");
    await page.waitForSelector("#home:not([hidden])");
    await noOverflow(page, "desktop home");
    assert.equal(await text(page, "#course-title"), "Kubernetes");
    assert.equal(await page.$$eval("#module option", options => options.length), data.catalog.modules.length);
    const active = await page.$eval(".unit.active h3", element => element.textContent);
    assert.equal(active, "Kubernetes Pods, ReplicaSets and Deployments");
    assert.equal(await page.$eval(".unit.active .callout", element => element.textContent), "Start");
    assert.match(await text(page, "#continue"), /^Start lesson.*Pods: the disposable unit$/);
    assert.equal(await page.$eval("#continue", element => element.getAttribute("aria-label")),
                 "Start lesson: Pods: the disposable unit, in Kubernetes Pods, ReplicaSets and Deployments");
    // Nothing is due yet: the Review button stays in place, disabled.
    assert.equal(await page.$eval("#review", element => element.disabled), true);
    assert.equal(await page.$eval("#review", element => element.getAttribute("aria-label")), "No cards due for review");
    assert.equal(await text(page, "#streak-count"), "0");
    // The topic before the active one folds into one row; the active unit draws its route and glyphs.
    assert.match(await text(page, ".earlier-toggle"), /^1 earlier topic0 of 2 lessons done$/);
    assert.equal(await page.$eval(".earlier-toggle", element => element.getAttribute("aria-expanded")), "false");
    await page.waitForSelector(".unit.active .route path.route-base");
    assert.equal(await page.$$eval(".unit.active .node svg", icons => icons.length), 4);
    await page.click(".earlier-toggle");
    assert.equal(await shown(page, "#earlier-units"), true);
    assert.match(await text(page, "#earlier-units .unit-title"), /control plane/i);
    await page.click(".earlier-toggle");
    assert.equal(await shown(page, "#earlier-units"), false);
    // A later unit opens from its banner.
    const later = (await page.$$("#path > .unit:not(.active) .unit-toggle"))[0];
    await later.click();
    assert.equal(await later.evaluate(element => element.getAttribute("aria-expanded")), "true");
    await later.click();
    await page.evaluate(() => scrollTo(0, 0));
    await snap(page, "practice-home-desktop-light");
    // A locked lesson explains itself instead of opening.
    const nodes = await page.$$(".unit.active .node");
    await nodes[1].click();
    assert.match(await text(page, "#path-note"), /Finish “Pods: the disposable unit” first/);
    assert.equal(state.lessonBodies.length, 0);

    await page.click("#continue");
    await page.waitForSelector("#player:not([hidden]) .step");
    assert.deepEqual(state.lessonBodies.at(-1), {topic: FEATURED, lesson: "pods"});
    assert.equal(await page.$eval("#progress", element => element.getAttribute("aria-valuemax")), "10");
    assert.equal(await page.$eval("#shell", element => element.hidden), true);
    const seen = [];
    let mistake = null, guessed = false, keyboard = false;
    while (!(await shown(page, "#summary"))) {
      const id = await item(page), step = stepOf(id);
      await noOverflow(page, "desktop " + step.type);
      if (step.pretest) {
        assert.match(await text(page, ".step-flag"), /Take a guess/);
        assert.equal(await shown(page, "#guess"), false);
        await answer(page, {wrong: true});
        assert.equal(await text(page, "#feedback-title"), "Now you know");
        assert.equal(await page.$eval("#feedback", element => element.className), "feedback neutral");
        await next(page);
      } else if (step.type === "choice" && !mistake && !seen.includes(id)) {
        mistake = id;
        await answer(page, {wrong: true});
        assert.equal(await text(page, "#feedback-title"), "Not quite");
        assert.equal(await page.$eval("#feedback", element => element.className), "feedback bad");
        assert.match(await text(page, "#feedback-body"), /Answer:/);
        assert.match(await text(page, "#feedback-body"), /You'll see this one again at the end of the lesson/);
        assert.equal(await text(page, "#repair-count"), "1 to fix");
        await snap(page, "practice-wrong-desktop-light");
        await next(page);
      } else if (step.type === "truefalse" && !guessed) {
        guessed = true;
        assert.equal(await shown(page, "#guess"), true);
        await answer(page, {guess: true});
        assert.equal(await text(page, "#feedback-title"), "Correct, but you guessed");
        assert.match(await text(page, "#feedback-body"), /come back tomorrow/);
        await next(page);
      } else if (step.type === "choice" && !keyboard && mistake && id !== mistake) {
        keyboard = true;
        await answer(page, {keyboard: true});
        assert.equal(await page.$eval("#feedback", element => element.className), "feedback good");
        await next(page, true);
      } else if (seen.includes(id)) {
        assert.equal(id, mistake, "only the missed question comes back");
        assert.equal(await text(page, ".step-flag"), "Let's fix this one");
        await answer(page);
        assert.equal(await page.$eval("#feedback", element => element.className), "feedback good");
        await next(page);
      } else {
        await answer(page, {label: "desktop-light"});
        if (step.type !== "teach" && step.type !== "explain") await next(page);
      }
      seen.push(id);
      if (!(await shown(page, "#summary"))) await page.waitForFunction(count =>
        !document.getElementById("summary").hidden || document.querySelector("#stage .step"), {}, seen.length);
    }
    assert.ok(mistake && guessed && keyboard, "the lesson exercised a mistake, a guess and the keyboard");
    assert.equal(seen.filter(id => id === mistake).length, 2);
    // XP: 5 first-try right (2 each, the guess included) + 1 repaired + 2 for the self-check + 5 bonus.
    assert.equal(await text(page, "#summary-title"), "Lesson complete");
    assert.equal(await text(page, "#sum-xp"), "+18");
    assert.equal(await text(page, "#sum-accuracy"), "83%");
    assert.equal(await text(page, "#sum-streak"), "1 day");
    assert.equal(await page.$$eval("#sum-takeaways li", items => items.length), 3);
    assert.match(await text(page, "#sum-review"), /^7 cards from this lesson come back tomorrow .*including the one you missed/);
    assert.match(await text(page, "#sum-next"), /Next: ReplicaSets: counting by labels/);
    assert.match(await page.$eval("#sum-provenance", element => element.textContent), /checked against the official Kubernetes documentation/);
    assert.equal(await page.$$eval("#sum-references a", links => links.every(link => link.href.startsWith("https://kubernetes.io/"))), true);
    await noOverflow(page, "desktop summary");
    await snap(page, "practice-summary-desktop-light");
    const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), STORE_KEY);
    assert.ok(saved.lessons[`${FEATURED}|pods`]);
    assert.equal(saved.xp.today, 18);
    assert.equal(saved.streak.count, 1);
    const cards = Object.entries(saved.items);
    assert.equal(cards.length, 7, "graded questions and the self-check become review cards; the pretest does not");
    assert.ok(cards.every(([id, record]) => record.b === 1 && record.n === 1 && id.startsWith(FEATURED + "|pods|")));
    assert.equal(saved.items[mistake].w, 1);
    assert.equal(Object.keys(saved.items).some(id => id.endsWith("|guess-node-fails")), false);
    // Nothing the learner typed was stored or sent.
    assert.equal(JSON.stringify(saved).includes("synthetic answer"), false);
    assert.equal(state.requests.every(url => !url.includes("synthetic")), true);

    await page.click("#sum-home");
    await page.waitForSelector("#home:not([hidden])");
    assert.equal(await page.$eval(".unit.active .node", element => element.classList.contains("done")), true);
    // Back on the path, the finished node and the newly unlocked one are marked for their moment,
    // and the route turns green up to the finished lesson.
    assert.equal(await page.$$eval(".unit.active .node.just-done", nodes => nodes.length), 1);
    assert.equal(await page.$$eval(".unit.active .node.just-open", nodes => nodes.length), 1);
    await page.waitForSelector(".unit.active .route path.route-done");
    assert.equal(await page.$eval(".unit.active .callout", element => element.textContent), "Next");
    assert.match(await text(page, "#continue"), /^Continue.*ReplicaSets: counting by labels$/);
    assert.equal(await text(page, "#streak-count"), "1");
    assert.equal(await text(page, "#goal-xp"), "18");
    assert.match(await text(page, "#review-note"), /Next review: tomorrow, 7 cards/);

    // 3. A review: three cards made due yesterday come back, mixed, and move further out when right.
    const due = cards.slice(0, 3).map(([id]) => id);
    await page.evaluate((key, ids) => {
      const store = JSON.parse(localStorage.getItem(key)), d = new Date(Date.now() - 86400000);
      const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      for (const id of ids) store.items[id].due = day;
      localStorage.setItem(key, JSON.stringify(store));
    }, STORE_KEY, due);
    await page.reload();
    await page.waitForSelector("#home:not([hidden])");
    assert.equal(await page.$eval("#review", element => element.getAttribute("aria-label")), "Review 3 cards");
    assert.equal(await page.$eval("#review", element => element.disabled), false);
    await page.click("#review");
    await page.waitForSelector("#player:not([hidden]) .step");
    assert.deepEqual([...state.reviewBodies.at(-1).items].sort(), [...due].sort());
    while (!(await shown(page, "#summary"))) {
      const step = await answer(page);
      if (step.type !== "explain") await next(page);
      await page.waitForFunction(() => !document.getElementById("summary").hidden || document.querySelector("#stage .step"));
    }
    assert.equal(await text(page, "#summary-title"), "Review complete");
    assert.equal(await shown(page, "#sum-next"), false);
    assert.match(await text(page, "#sum-review"), /^3 cards moved further out\.$/);
    const reviewed = await page.evaluate((key, ids) => ids.map(id => JSON.parse(localStorage.getItem(key)).items[id].b), STORE_KEY, due);
    assert.deepEqual(reviewed, [2, 2, 2]);

    // 4. Leaving a lesson: Escape and the browser's back button ask first; leaving saves nothing.
    await page.click("#sum-home");
    await page.waitForSelector("#home:not([hidden])");
    await page.click("#continue");
    await page.waitForSelector("#player:not([hidden]) .step");
    await page.keyboard.press("Escape");
    await page.waitForSelector("#quit-sheet:not([hidden])");
    assert.equal(await page.evaluate(() => document.activeElement.id), "quit-stay");
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.id), "quit-leave");
    await page.keyboard.press("Escape");
    assert.equal(await shown(page, "#quit-sheet"), false);
    await page.evaluate(() => history.back());
    await page.waitForSelector("#quit-sheet:not([hidden])");
    await page.click("#quit-stay");
    assert.equal(await shown(page, "#player"), true);
    await page.click("#quit");
    await page.click("#quit-leave");
    await page.waitForSelector("#home:not([hidden])");
    const after = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), STORE_KEY);
    assert.equal(after.lessons[`${FEATURED}|replicasets`], undefined);
    assert.equal(await page.evaluate(() => location.hash), "");
    assert.deepEqual(await page.evaluate(() => window.__csp), []);
    assert.deepEqual(problems, []);
    await page.close();
  }

  // 5. Phone, dark: every exercise type renders without sideways scrolling, and the auto-built lesson
  //    for a library topic works end to end.
  {
    const {page, problems} = await open(390, 844, "dark");
    await page.goto(origin + "/web/practice");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector("#home:not([hidden])");
    await noOverflow(page, "phone home");
    // The first screen on a phone shows the current lesson and the one after it, without scrolling.
    const firstScreen = await page.evaluate(() => [...document.querySelectorAll(".unit.active .node")].slice(0, 2)
      .map(node => node.getBoundingClientRect().bottom <= innerHeight));
    assert.deepEqual(firstScreen, [true, true], "current lesson and the next node are visible at once");
    assert.equal(await shown(page, "#review"), true);
    await snap(page, "practice-home-mobile-dark");
    const types = new Set();
    for (let lesson = 0; lesson < 4; lesson++) {
      const node = await page.$$(".unit.active .node");
      const states = await Promise.all(node.map(n => n.evaluate(element => element.className)));
      const index = states.findIndex(name => name.includes("current"));
      assert.equal(index, lesson, "the path walks the hand-crafted lessons in order");
      await node[index].click();
      await page.waitForSelector("#player:not([hidden]) .step");
      while (!(await shown(page, "#summary"))) {
        const id = await item(page), step = stepOf(id);
        await noOverflow(page, "phone " + step.type);
        if (!types.has(step.type)) {
          types.add(step.type);
          await snap(page, `practice-${step.type}-mobile-dark`);
        }
        await answer(page, {label: "mobile-dark"});
        if (step.type !== "teach" && step.type !== "explain") {
          if (!types.has("feedback")) { types.add("feedback"); await snap(page, "practice-feedback-mobile-dark"); }
          await next(page);
        }
        await page.waitForFunction(() => !document.getElementById("summary").hidden || document.querySelector("#stage .step"));
      }
      await noOverflow(page, "phone summary");
      if (lesson === 0) await snap(page, "practice-summary-mobile-dark");
      await page.click("#sum-home");
      await page.waitForSelector("#home:not([hidden])");
    }
    for (const type of ["teach", "choice", "truefalse", "match", "order", "fill", "spot", "explain", "type", "scenario"]) {
      assert.ok(types.has(type), "the hand-crafted unit covers " + type);
    }
    const unit = await page.$eval(".unit.active", element => element.querySelector("h3").textContent);
    assert.notEqual(unit, "Kubernetes Pods, ReplicaSets and Deployments", "a finished unit hands over to the next topic");
    // An auto-built lesson from another course.
    const linux = data.catalog.modules.find(module => module.topics.some(topic => topic.id === data.derived));
    await page.select("#module", linux.id);
    await page.waitForFunction(title => document.getElementById("course-title").textContent === title, {}, linux.title);
    const derived = data.derived;
    const title = data.lessons[`${derived}|core`].topic.title;
    assert.equal(await page.$eval(".unit.active h3", element => element.textContent), title);
    assert.match(await page.$eval(".unit.active .unit-meta", element => element.textContent), /Built from the course notes/);
    await page.click("#continue");
    await page.waitForSelector("#player:not([hidden]) .step");
    assert.deepEqual(state.lessonBodies.at(-1), {topic: derived, lesson: "core"});
    const derivedShots = new Set();
    while (!(await shown(page, "#summary"))) {
      const id = await item(page), step = stepOf(id);
      const kind = step.pretest ? "guess" : step.type;
      if (!derivedShots.has(kind)) { derivedShots.add(kind); await snap(page, `practice-derived-${kind}-mobile-dark`); }
      await answer(page);
      if (step.type !== "explain" && step.type !== "teach") await next(page);
      await page.waitForFunction(() => !document.getElementById("summary").hidden || document.querySelector("#stage .step"));
    }
    assert.ok(["guess", "teach", "choice", "truefalse", "match"].every(kind => derivedShots.has(kind)), [...derivedShots].join());
    assert.equal(await text(page, "#summary-title"), "Lesson complete");
    assert.match(await page.$eval("#sum-provenance", element => element.textContent), /Built automatically from this topic's course notes/);
    assert.deepEqual(await page.evaluate(() => window.__csp), []);
    assert.deepEqual(problems, []);
    await page.close();
  }

  // 6. Hostile course text is shown as text, never run; a failed lesson request explains itself.
  {
    state.hostile = true;
    const {page, problems} = await open(1024, 800);
    await page.goto(origin + "/web/practice");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector("#home:not([hidden])");
    await page.select("#module", data.catalog.modules.find(module => module.topics.some(topic => topic.id === data.derived)).id);
    await page.waitForFunction(() => document.querySelector(".unit.active h3").textContent.includes("Hostile title"));
    assert.match(await page.$eval(".unit.active h3", element => element.textContent), /^<img src=x onerror=/);
    await page.click("#continue");
    await page.waitForSelector("#player:not([hidden]) .step");
    while (true) {
      const heading = await text(page, "#stage .step-heading");
      if (heading.includes("<script>")) break;
      await answer(page);
      if (!(await shown(page, "#feedback"))) continue;
      await next(page);
    }
    assert.match(await text(page, "#stage .teach-body"), /<img src=x onerror=window.pwnedPractice=4>/);
    assert.equal(await page.evaluate(() => window.pwnedPractice), undefined);
    await page.click("#quit");
    await page.click("#quit-leave");
    state.failLesson = true;
    await page.click("#continue");
    await page.waitForFunction(() => document.getElementById("path-note").textContent.includes("temporarily unavailable"));
    assert.equal(await shown(page, "#player"), false);
    state.failLesson = false;
    state.hostile = false;
    assert.deepEqual(await page.evaluate(() => window.__csp), []);
    assert.deepEqual(problems, []);
    await page.close();
  }

  // 7. Hints, the simulated terminal and a troubleshooting scenario, in the Rollback lesson.
  {
    const {page, problems} = await open(1024, 800, "dark");
    await page.goto(origin + "/web/practice");
    await page.waitForSelector("#home:not([hidden])");
    await page.evaluate((key, topic) => {
      const lessons = {};
      for (const id of ["pods", "replicasets", "rolling-updates"]) lessons[`${topic}|${id}`] = {at: "2026-10-01", accuracy: 100};
      localStorage.setItem(key, JSON.stringify({v: 1, xp: {total: 0, day: "", today: 0}, streak: {count: 0, last: ""},
                                                lessons, items: {}, module: ""}));
    }, STORE_KEY, FEATURED);
    await page.reload();
    await page.waitForSelector("#home:not([hidden])");
    await page.click("#continue");
    await page.waitForSelector("#player:not([hidden]) .step");
    assert.deepEqual(state.lessonBodies.at(-1), {topic: FEATURED, lesson: "rollback"});
    let hintedChoice = null, typedWrong = false, typedRight = false, scenarioWrong = false, scenarioRight = false;
    while (!(await shown(page, "#summary"))) {
      const id = await item(page), step = stepOf(id);
      if (step.pretest) {
        assert.equal(await shown(page, "#hint"), false, "no hint on a guess before teaching");
        await answer(page);
        await next(page);
      } else if (step.type === "choice" && !hintedChoice && step.options.length >= 3) {
        hintedChoice = id;
        await page.click("#hint");
        assert.equal(await page.$eval("#hint", element => element.disabled), true, "one hint per question");
        assert.equal(await page.$$eval("#stage .option.is-out", nodes => nodes.length), 1);
        assert.equal(await text(page, ".hint-box"), "Hint: One wrong answer is crossed out.");
        assert.equal(await page.$eval("#stage .option.is-out", element => element.disabled), true);
        await answer(page);
        assert.equal(await text(page, "#feedback-title"), "Correct, with a hint");
        assert.match(await text(page, "#feedback-body"), /come back tomorrow/);
        await next(page);
      } else if (step.type === "type" && !typedWrong) {
        typedWrong = true;
        assert.equal(await text(page, "#check"), "Run");
        await page.click("#hint");
        assert.match(await text(page, ".hint-box"), /kubectl rollout subcommand/);
        await page.type("#type-answer", "kubectl get pods");
        await page.keyboard.press("Enter");
        await page.waitForSelector("#feedback:not([hidden])");
        assert.equal(await text(page, "#feedback-title"), "Not quite");
        assert.match(await text(page, "#feedback-body"), /Answer: kubectl rollout history deployment\/web/);
        assert.equal(await page.$$eval(".terminal-live .term-line", lines => lines.length), 0, "no output for a wrong command");
        await snap(page, "practice-terminal-wrong-desktop-dark");
        await next(page);
      } else if (step.type === "type") {
        typedRight = true;
        assert.equal(await text(page, ".step-flag"), "Let's fix this one");
        // Spaces and a pasted "$ " prompt don't matter; the command's words do.
        await page.type("#type-answer", "$ kubectl   rollout history deploy/web ");
        await page.keyboard.press("Enter");
        await page.waitForSelector("#feedback:not([hidden])");
        assert.equal(await page.$eval("#feedback", element => element.className), "feedback good");
        assert.deepEqual(await page.$$eval(".terminal-live .term-line", lines => lines.map(line => line.textContent)), step.output);
        await snap(page, "practice-terminal-desktop-dark");
        await next(page);
      } else if (step.type === "scenario" && !scenarioWrong) {
        scenarioWrong = true;
        assert.equal(await shown(page, "#hint"), false);
        assert.equal(await page.$$eval(".scenario-stage", nodes => nodes.length), 1, "later steps stay hidden");
        await answer(page, {wrong: true});
        assert.equal(await page.$$eval(".scenario-stage", nodes => nodes.length), step.stages.length);
        assert.equal(await page.$$eval(".scenario-stage .terminal", nodes => nodes.length), step.stages.length);
        assert.equal(await text(page, "#feedback-title"), "Not quite");
        assert.match(await text(page, "#feedback-body"), /Solved, with 1 wrong turn on the way/);
        await snap(page, "practice-scenario-desktop-dark");
        await next(page);
      } else if (step.type === "scenario") {
        scenarioRight = true;
        await answer(page);
        assert.match(await text(page, "#feedback-body"), /Solved with no wrong turns/);
        await next(page);
      } else {
        await answer(page);
        if (step.type !== "teach" && step.type !== "explain") await next(page);
      }
      await noOverflow(page, "desktop dark " + step.type);
      await page.waitForFunction(() => !document.getElementById("summary").hidden || document.querySelector("#stage .step"));
    }
    assert.ok(hintedChoice && typedWrong && typedRight && scenarioWrong && scenarioRight);
    const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), STORE_KEY);
    // A hinted answer is right but not yet known: no mistake, and it returns tomorrow (box 1).
    assert.deepEqual([saved.items[hintedChoice].b, saved.items[hintedChoice].w], [1, 0]);
    assert.equal(saved.items[`${FEATURED}|rollback|history-command`].w, 1);
    assert.equal(saved.items[`${FEATURED}|rollback|bad-tag`].w, 1);
    assert.equal(JSON.stringify(saved).includes("kubectl get pods"), false, "typed answers are not stored");
    assert.deepEqual(await page.evaluate(() => window.__csp), []);
    assert.deepEqual(problems, []);
    await page.close();
  }
  console.log(JSON.stringify({practice: "ok", lessons: state.lessonBodies.length, reviews: state.reviewBodies.length}));
} finally {
  await browser.close();
  await fixture.close();
}
