/* SkillCoach Practice: short, answer-first lessons on a path (design contract in practice.html).
   Content comes from /web/practice/* with the signed-in /web session and its CSRF token. Answers are
   checked in this page. Progress (lessons done, XP, streak and the spaced-review schedule) stays in this
   browser's localStorage under an opaque per-learner key. Written explanations never leave the page and
   are never stored: only how many key points the learner ticked is used, to schedule the next review. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const kit = window.SkillCoachLesson;
  const motionOK = () => matchMedia("(prefers-reduced-motion: no-preference)").matches;
  const GOAL = 20, STRONG = 3, REVIEW_SIZE = 12, MAX_REPEATS = 2;
  // Days until a card returns, by box: a first correct answer returns tomorrow, then 3, 7, 16, 35 days.
  const INTERVALS = [0, 1, 3, 7, 16, 35];
  const STORE = "skillcoach.practice.v1.";
  const GUESSABLE = new Set(["choice", "truefalse", "order", "fill", "spot"]);
  const WAVE = [0, 0.75, 1, 0.75, 0, -0.75, -1, -0.75];
  const PRAISE = ["Correct", "Nice work", "Exactly", "That's it"];

  // DOM helpers ---------------------------------------------------------------------------------------
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function inline(parent, list) {
    for (const span of list || []) {
      if (span.t === "code") parent.append(el("code", "", span.v));
      else if (span.t === "b") parent.append(el("strong", "", span.v));
      else parent.append(document.createTextNode(String(span.v)));
    }
    return parent;
  }
  function blocks(parent, list) {
    if (list && list.length) kit.renderBlocks(parent, list);
    return parent;
  }
  function button(cls, text) {
    const node = el("button", cls, text);
    node.type = "button";
    return node;
  }
  function shuffle(list) {
    const copy = [...list];
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }
  const SVG = "http://www.w3.org/2000/svg";
  const ICONS = {
    check: [["M5 12.5l4.6 4.6L19.2 7.4", "stroke"]],
    lock: [["M7.5 11V8.2a4.5 4.5 0 0 1 9 0V11", "stroke"], ["M5.5 10.6h13v10h-13z", "fill"]],
    star: [["M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9z", "fill"]],
    flame: [["M12.7 2.4c.5 3.6 5 5.6 5 10.7a5.7 5.7 0 0 1-11.4 0c0-2.5 1.1-4.4 2.7-5.6.1 1.9 1 3.1 2.4 3.7-.6-3.2-.1-6.1 1.3-8.8z", "fill"]],
    bolt: [["M13.6 2 4.6 13.6h6.3L9.9 22l9.6-12.3h-6.6z", "fill"]],
    close: [["M6 6l12 12M18 6 6 18", "stroke"]],
    review: [["M19.5 10.5A7.7 7.7 0 0 0 5.4 7.6M4.5 13.5a7.7 7.7 0 0 0 14.1 2.9", "stroke"], ["M5 3.8v4h4M19 20.2v-4h-4", "stroke"]],
    chevron: [["M6 9.5l6 6 6-6", "stroke"]],
    // Lesson glyphs on the path: a Pod with two containers, a ReplicaSet's three Pods, a rollout
    // moving to a new version, a rollback, an idea and a target.
    pod: [["M4.5 6.8a2.3 2.3 0 0 1 2.3-2.3h10.4a2.3 2.3 0 0 1 2.3 2.3v10.4a2.3 2.3 0 0 1-2.3 2.3H6.8a2.3 2.3 0 0 1-2.3-2.3z", "stroke"],
          ["M8 9h3.2v6H8zM12.8 9H16v6h-3.2z", "fill"]],
    replicaset: [["M3 8.5h5.2v7H3zM9.4 8.5h5.2v7H9.4zM15.8 8.5H21v7h-5.2z", "stroke"]],
    rollout: [["M3.5 12h11.5M11 7.5l4.5 4.5-4.5 4.5", "stroke"], ["M19.5 5.5v13", "stroke"]],
    rollback: [["M8.5 6.5 4 11l4.5 4.5", "stroke"], ["M4.5 11h9.2a5.3 5.3 0 0 1 0 10.6H11", "stroke"]],
    idea: [["M9.3 17.6h5.4M10.3 20.6h3.4", "stroke"],
           ["M12 3.4a5.9 5.9 0 0 0-3.5 10.6c.7.6 1 1.3 1 2.1h5c0-.8.4-1.5 1-2.1A5.9 5.9 0 0 0 12 3.4z", "stroke"]],
    target: [["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z", "stroke"],
             ["M12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z", "fill"]],
  };
  function icon(name, size = 22) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    for (const [d, mode] of ICONS[name]) {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", d);
      if (mode === "stroke") {
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "currentColor");
        path.setAttribute("stroke-width", "2.6");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-linejoin", "round");
      } else path.setAttribute("fill", "currentColor");
      svg.append(path);
    }
    return svg;
  }
  for (const holder of document.querySelectorAll("[data-icon]")) holder.append(icon(holder.dataset.icon));

  // Server ----------------------------------------------------------------------------------------------
  let csrf = "";
  async function call(path, body, method = "POST") {
    const headers = {"Content-Type": "application/json"};
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(path, {
      method, headers, credentials: "same-origin", cache: "no-store",
      body: method === "GET" ? undefined : JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    return {status: response.status, ok: response.ok, data};
  }

  // Device-local dates and progress --------------------------------------------------------------------
  const pad = n => String(n).padStart(2, "0");
  const dayKey = (date = new Date()) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  function addDays(key, days) {
    const [y, m, d] = key.split("-").map(Number);
    return dayKey(new Date(y, m - 1, d + days));
  }
  let storeKey = "", store = null, storable = true;
  const freshStore = () => ({v: 1, xp: {total: 0, day: "", today: 0}, streak: {count: 0, last: ""},
                             lessons: {}, items: {}, module: ""});
  function loadStore(key) {
    try {
      const data = JSON.parse(localStorage.getItem(key) || "null");
      if (data && data.v === 1 && data.items && typeof data.items === "object" && data.lessons
          && typeof data.lessons === "object") return {...freshStore(), ...data};
    } catch { /* unreadable progress starts again */ }
    return freshStore();
  }
  function save() {
    try {
      localStorage.setItem(storeKey, JSON.stringify(store));
      storable = true;
    } catch {
      storable = false;
    }
    return storable;
  }
  const xpToday = () => (store.xp.day === dayKey() ? store.xp.today : 0);
  function streakNow() {
    const today = dayKey();
    return store.streak.last === today || store.streak.last === addDays(today, -1) ? store.streak.count : 0;
  }
  function addXp(amount) {
    const today = dayKey();
    if (store.xp.day !== today) { store.xp.day = today; store.xp.today = 0; }
    store.xp.today += amount;
    store.xp.total += amount;
  }
  function extendStreak() {
    const today = dayKey();
    if (store.streak.last === today) return false;
    store.streak.count = store.streak.last === addDays(today, -1) ? store.streak.count + 1 : 1;
    store.streak.last = today;
    return true;
  }
  // Leitner boxes: a right first answer moves a card up one box (longer wait); a wrong, guessed or weak
  // answer puts it back in box 1, so it returns tomorrow. Box 3 or higher counts as "strong".
  function schedule(item, outcome) {
    const record = store.items[item] || {b: 0, n: 0, w: 0, due: ""};
    record.n += 1;
    if (outcome === "correct") record.b = Math.min(record.b + 1, INTERVALS.length - 1);
    else {
      record.b = 1;
      if (outcome === "wrong") record.w += 1;
    }
    record.due = addDays(dayKey(), INTERVALS[record.b]);
    store.items[item] = record;
  }
  function dueItems() {
    const today = dayKey();
    return Object.entries(store.items)
      .filter(([, record]) => record.due && record.due <= today)
      .sort((a, b) => a[1].due.localeCompare(b[1].due) || a[1].b - b[1].b)
      .map(([item]) => item);
  }
  function nextReview() {
    const today = dayKey(), later = Object.values(store.items).map(r => r.due).filter(d => d && d > today).sort();
    return later.length ? {day: later[0], count: later.filter(d => d === later[0]).length} : null;
  }
  function when(day) {
    const today = dayKey();
    if (day === addDays(today, 1)) return "tomorrow";
    const [y, m, d] = day.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, {weekday: "long", day: "numeric", month: "short"});
  }
  const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

  // Catalog and path ----------------------------------------------------------------------------------
  let catalog = null, moduleId = "";
  const moduleById = id => catalog.modules.find(module => module.id === id);
  const lessonKey = (topic, lesson) => `${topic}|${lesson}`;
  const isDone = (topic, lesson) => Object.prototype.hasOwnProperty.call(store.lessons, lessonKey(topic, lesson));
  function lessonState(topic, index) {
    if (isDone(topic.id, topic.lessons[index].id)) return "done";
    return index === 0 || isDone(topic.id, topic.lessons[index - 1].id) ? "open" : "locked";
  }
  const openIndex = topic => topic.lessons.findIndex((_, i) => lessonState(topic, i) === "open");
  function recommended(module) {
    const started = module.topics.find(t => openIndex(t) > 0);
    const featured = module.topics.find(t => t.id === catalog.featured && openIndex(t) >= 0);
    const any = module.topics.find(t => openIndex(t) >= 0);
    const topic = started || featured || any;
    return topic ? {topic, index: openIndex(topic)} : null;
  }
  function cardsOf(topicId) {
    let total = 0, strong = 0;
    for (const [item, record] of Object.entries(store.items)) {
      if (!item.startsWith(topicId + "|")) continue;
      total += 1;
      if (record.b >= STRONG) strong += 1;
    }
    return {total, strong};
  }
  function following(topicId, lessonId) {
    for (const module of catalog.modules) {
      const t = module.topics.findIndex(topic => topic.id === topicId);
      if (t < 0) continue;
      const topic = module.topics[t], i = topic.lessons.findIndex(lesson => lesson.id === lessonId);
      if (topic.lessons[i + 1]) return {topic, index: i + 1};
      for (const later of module.topics.slice(t + 1)) {
        const open = openIndex(later);
        if (open >= 0) return {topic: later, index: open};
      }
    }
    return null;
  }

  // Views -----------------------------------------------------------------------------------------------
  let retryAction = null;
  function notice(text, error = false, retry = null) {
    $("notice").textContent = text;
    $("notice").hidden = !text;
    $("notice").classList.toggle("error", error);
    retryAction = retry;
    $("retry-wrap").hidden = !retry;
  }
  function show(name) {
    $("shell").hidden = name === "player" || name === "summary";
    $("home").hidden = name !== "home";
    $("signed-out").hidden = name !== "signed-out";
    $("player").hidden = name !== "player";
    $("summary").hidden = name !== "summary";
    $("stats").hidden = name !== "home";
    document.body.classList.toggle("in-lesson", name === "player");
    if (name !== "player") document.documentElement.style.removeProperty("scroll-padding-bottom");
  }
  // The sticky answer bar covers the bottom of the screen; scrolling must keep answers above it.
  function padForBar() {
    const bar = $("player").querySelector(".player-bar");
    document.documentElement.style.setProperty("scroll-padding-bottom", `${bar.offsetHeight + 12}px`);
  }
  function pathNote(text) { $("path-note").textContent = text; }
  function signedOut(text) {
    notice("");
    if (text) $("signed-out-text").textContent = text;
    show("signed-out");
  }

  function showHome() {
    notice(storable ? "" : "This browser isn't saving practice progress (storage is off or full).", !storable);
    show("home");
    renderStats();
    renderModules();
    renderPath();
    renderToday();
  }
  function renderStats() {
    const streak = streakNow(), xp = xpToday();
    $("streak-count").textContent = streak;
    $("streak-label").textContent = streak === 1 ? "day streak" : "days in a row";
    $("streak").classList.toggle("lit", store.streak.last === dayKey());
    $("goal-xp").textContent = xp;
    $("goal-target").textContent = GOAL;
    $("goal").classList.toggle("met", xp >= GOAL);
  }
  function renderToday() {
    const module = moduleById(moduleId), next = recommended(module), due = dueItems(), xp = xpToday();
    const started = Object.keys(store.lessons).length > 0;
    $("today-title").textContent = started ? "Keep going" : "Start here";
    $("today-text").textContent = xp >= GOAL
      ? `Today's goal is done: ${xp} XP. Anything more is a bonus.`
      : started
        ? `${GOAL - xp} XP to today's goal. A lesson takes about 5 minutes.`
        : "Short lessons, mostly questions. Every mistake comes back until it sticks.";
    const go = $("continue");
    go.replaceChildren();
    if (next) {
      const lesson = next.topic.lessons[next.index], action = next.index === 0 && !started ? "Start lesson" : "Continue";
      const detail = el("span", "button-detail");
      detail.append(el("span", "detail-topic", `${next.topic.title} · `), el("span", "", lesson.title));
      go.append(el("span", "button-title", action), detail);
      go.setAttribute("aria-label", `${action}: ${lesson.title}, in ${next.topic.title}`);
      go.disabled = false;
      go.onclick = () => startLesson(next.topic.id, lesson.id);
    } else {
      go.append(el("span", "button-title", "Course complete"),
                el("span", "button-detail", "Choose another course below"));
      go.setAttribute("aria-label", "Course complete. Choose another course below.");
      go.disabled = true;
    }
    const review = $("review"), count = Math.min(due.length, REVIEW_SIZE);
    review.replaceChildren(icon("review", 20),
      el("span", "button-title long", due.length ? `Review ${plural(count, "card")}` : "No cards due"),
      el("span", "button-title short", due.length ? String(count) : "0"));
    review.setAttribute("aria-label", due.length ? `Review ${plural(count, "card")}` : "No cards due for review");
    review.disabled = !due.length;
    const upcoming = nextReview();
    $("review-note").textContent = due.length
      ? due.length > REVIEW_SIZE ? `${due.length} cards are due; each review takes ${REVIEW_SIZE}.` : "Reviews bring back what you're about to forget."
      : upcoming ? `Next review: ${when(upcoming.day)}, ${plural(upcoming.count, "card")}.` : "Cards you practise come back here for review.";
  }
  function renderModules() {
    const select = $("module");
    if (!select.options.length) for (const module of catalog.modules) select.append(new Option(module.title, module.id));
    select.value = moduleId;
  }
  // Units before the one you're on fold into one "earlier topics" row and units after it show as
  // banners, so the lesson you're on is near the top of the path; any of them opens on a tap.
  const expanded = new Set();
  let lastFinished = null;
  function renderPath() {
    const module = moduleById(moduleId), next = recommended(module), list = $("path");
    const total = module.topics.reduce((sum, t) => sum + t.lessons.length, 0);
    const finished = module.topics.reduce((sum, t) => sum + t.lessons.filter((_, i) => lessonState(t, i) === "done").length, 0);
    $("course-title").textContent = module.title;
    $("course-meta").textContent = `${finished} of ${total} lessons done · ${plural(module.topics.length, "topic")}`;
    list.replaceChildren();
    const activeIndex = next ? module.topics.findIndex(topic => topic.id === next.topic.id) : -1;
    const earlier = module.topics.slice(0, Math.max(activeIndex, 0));
    if (earlier.length) {
      const group = el("li", "p-earlier"), inner = el("ol", "earlier-units"), key = moduleId + ":earlier";
      const toggle = button("earlier-toggle");
      const doneEarlier = earlier.reduce((sum, t) => sum + t.lessons.filter((_, i) => lessonState(t, i) === "done").length, 0);
      toggle.append(el("span", "earlier-title", plural(earlier.length, "earlier topic")),
                    el("span", "earlier-meta", `${doneEarlier} of ${earlier.reduce((s, t) => s + t.lessons.length, 0)} lessons done`),
                    icon("chevron", 20));
      inner.id = "earlier-units";
      inner.hidden = !expanded.has(key);
      toggle.setAttribute("aria-expanded", String(!inner.hidden));
      toggle.setAttribute("aria-controls", inner.id);
      toggle.addEventListener("click", () => {
        inner.hidden = !inner.hidden;
        toggle.setAttribute("aria-expanded", String(!inner.hidden));
        if (inner.hidden) expanded.delete(key); else expanded.add(key);
        drawRoutes();
      });
      for (const topic of earlier) inner.append(unitItem(topic, next));
      group.append(toggle, inner);
      list.append(group);
    }
    for (const topic of module.topics.slice(Math.max(activeIndex, 0))) list.append(unitItem(topic, next));
    requestAnimationFrame(() => {
      drawRoutes();
      const moved = list.querySelector(".node.just-open") || list.querySelector(".node.just-done");
      if (moved) moved.scrollIntoView({block: "center", behavior: motionOK() ? "smooth" : "auto"});
      lastFinished = null;
    });
  }
  function unitItem(topic, next) {
    const active = Boolean(next && next.topic.id === topic.id);
    const unit = el("li", "unit" + (active ? " active" : "") + (topic.crafted ? " crafted" : ""));
    const head = el("div", "unit-head"), cards = cardsOf(topic.id), heading = el("h3");
    const doneCount = topic.lessons.filter((_, i) => lessonState(topic, i) === "done").length;
    const strongTopic = cards.total > 0 && cards.strong === cards.total && doneCount === topic.lessons.length;
    const meta = [topic.crafted ? "Hand-crafted lessons" : "Built from the course notes",
                  `${doneCount} of ${topic.lessons.length} done`];
    if (cards.total) meta.push(`${cards.strong} of ${plural(cards.total, "card")} strong`);
    const toggle = button("unit-toggle"), wrap = el("div", "nodes-wrap"), id = "unit-" + topic.id.replace(/[^a-z0-9]+/g, "-");
    wrap.id = id;
    wrap.hidden = !(active || expanded.has(topic.id));
    toggle.append(el("span", "unit-title", topic.title), icon("chevron", 20));
    toggle.setAttribute("aria-expanded", String(!wrap.hidden));
    toggle.setAttribute("aria-controls", id);
    toggle.addEventListener("click", () => {
      wrap.hidden = !wrap.hidden;
      toggle.setAttribute("aria-expanded", String(!wrap.hidden));
      if (wrap.hidden) expanded.delete(topic.id); else expanded.add(topic.id);
      drawRoutes();
    });
    heading.append(toggle);
    head.append(heading, el("p", "unit-meta", meta.join(" · ")));
    const nodes = el("ol", "nodes");
    topic.lessons.forEach((lesson, index) => {
      const state = lessonState(topic, index), current = active && next.index === index;
      const finishedNow = lastFinished && lastFinished.topic === topic.id && lastFinished.lesson === lesson.id;
      const unlockedNow = lastFinished && lastFinished.topic === topic.id && index > 0
        && topic.lessons[index - 1].id === lastFinished.lesson && state === "open";
      const row = el("li", "node-row");
      row.style.setProperty("--wave", WAVE[index % WAVE.length]);
      const node = button(`node ${state}${current ? " current" : ""}${strongTopic ? " strong" : ""}`
        + `${finishedNow ? " just-done" : ""}${unlockedNow ? " just-open" : ""}`);
      node.append(state === "done" ? icon(strongTopic ? "star" : "check", 30)
        : state === "locked" ? icon("lock", 24) : icon(ICONS[lesson.icon] ? lesson.icon : "idea", 32));
      node.setAttribute("aria-label", `${lesson.title}. Lesson ${index + 1} of ${topic.lessons.length}, ` +
        `${state === "done" ? "done" : state === "locked" ? "locked" : "ready"}, about ${lesson.minutes} minutes.`);
      if (current) node.setAttribute("aria-current", "step");
      if (state === "locked") node.setAttribute("aria-disabled", "true");
      node.addEventListener("click", () => state === "locked"
        ? pathNote(`Finish “${topic.lessons[index - 1].title}” first to unlock this lesson.`)
        : startLesson(topic.id, lesson.id, node));
      if (current) {
        const callout = el("span", "callout", doneCount ? "Next" : "Start");
        callout.setAttribute("aria-hidden", "true");
        row.append(callout);
      }
      row.append(node, el("span", "node-title", lesson.title));
      nodes.append(row);
    });
    wrap.append(nodes);
    unit.append(head, wrap);
    return unit;
  }
  // The route: a drawn path through each open unit's nodes, green as far as the lessons are done.
  function drawRoutes() {
    for (const wrap of document.querySelectorAll("#path .nodes-wrap")) {
      const old = wrap.querySelector(".route");
      if (old) old.remove();
      if (wrap.closest("[hidden]")) continue;
      const nodes = [...wrap.querySelectorAll(".node")];
      if (nodes.length < 2) continue;
      const box = wrap.getBoundingClientRect();
      const points = nodes.map(node => {
        const r = node.getBoundingClientRect();
        return [r.left + r.width / 2 - box.left, r.top + r.height / 2 - box.top, node.classList.contains("done")];
      });
      const curve = (a, b) => {
        const middle = (a[1] + b[1]) / 2;
        return `M ${a[0]} ${a[1]} C ${a[0]} ${middle} ${b[0]} ${middle} ${b[0]} ${b[1]}`;
      };
      const svg = document.createElementNS(SVG, "svg");
      svg.setAttribute("class", "route");
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      svg.setAttribute("width", String(Math.round(box.width)));
      svg.setAttribute("height", String(Math.round(box.height)));
      const line = (d, cls) => {
        const path = document.createElementNS(SVG, "path");
        path.setAttribute("d", d);
        path.setAttribute("class", cls);
        svg.append(path);
      };
      line(points.slice(1).map((point, i) => curve(points[i], point)).join(" "), "route-base");
      const done = points.slice(1).map((point, i) => (points[i][2] ? curve(points[i], point) : "")).filter(Boolean).join(" ");
      if (done) line(done, "route-done");
      wrap.prepend(svg);
    }
  }
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (!$("home").hidden) drawRoutes(); }, 120);
  });
  $("module").addEventListener("change", () => {
    moduleId = $("module").value;
    store.module = moduleId;
    save();
    pathNote("");
    renderPath();
    renderToday();
  });

  // Lesson player -------------------------------------------------------------------------------------
  let session = null, current = null, guessing = false, hinted = false, feedbackOpen = false, opening = false;

  async function startLesson(topicId, lessonId, trigger) {
    if (opening) return;
    opening = true;
    pathNote("Opening the lesson…");
    if (trigger) trigger.disabled = true;
    try {
      const result = await call("/web/practice/lesson", {topic: topicId, lesson: lessonId});
      if (result.status === 403) return signedOut("Your sign-in ended. Sign in again, then come back to Practice.");
      if (!result.ok) return pathNote(result.data.error || "That lesson couldn't be opened. Try again.");
      pathNote("");
      begin({kind: "lesson", info: result.data, topic: result.data.topic, lesson: result.data.lesson,
             steps: result.data.lesson.steps});
    } catch {
      pathNote("SkillCoach couldn't be reached. Check your connection and try again.");
    } finally {
      opening = false;
      if (trigger) trigger.disabled = false;
    }
  }
  async function startReview() {
    const ids = dueItems().slice(0, REVIEW_SIZE);
    if (!ids.length || opening) return;
    opening = true;
    pathNote("Opening your review…");
    try {
      const result = await call("/web/practice/review", {items: ids});
      if (result.status === 403) return signedOut("Your sign-in ended. Sign in again, then come back to Practice.");
      if (!result.ok) return pathNote(result.data.error || "The review couldn't be opened. Try again.");
      const steps = result.data.steps || [], known = new Set(steps.map(step => step.item));
      // Retired content leaves the queue instead of blocking it.
      for (const id of ids) if (!known.has(id)) delete store.items[id];
      save();
      pathNote("");
      if (!steps.length) { renderToday(); return pathNote("Those cards were retired from the course. Your queue is up to date."); }
      begin({kind: "review", steps: interleave(steps)});
    } catch {
      pathNote("SkillCoach couldn't be reached. Check your connection and try again.");
    } finally {
      opening = false;
    }
  }
  $("review").addEventListener("click", startReview);
  // Mixing topics (interleaving) makes reviews harder in the useful way: no two neighbours share a topic
  // when that can be avoided.
  function interleave(steps) {
    const pool = shuffle(steps), out = [];
    while (pool.length) {
      const last = out.length ? out[out.length - 1].topic : null;
      const index = pool.findIndex(step => step.topic !== last);
      out.push(pool.splice(index < 0 ? 0 : index, 1)[0]);
    }
    return out;
  }
  function begin(spec) {
    lastFinished = null;
    session = {...spec, queue: spec.steps.map(step => ({step, repeats: 0})), index: 0, total: spec.steps.length,
               resolved: new Set(), first: new Map(), explained: new Map(), xp: 0};
    history.pushState({practice: "lesson"}, "", "#lesson");
    show("player");
    renderStep();
  }
  function heading(wrap, content) {
    const title = el("h1", "step-heading");
    title.tabIndex = -1;
    if (typeof content === "string") title.textContent = content;
    else if (Array.isArray(content) && content.length && content[0].type) {
      // Prompt blocks: the first paragraph is the heading, anything after it follows as text.
      const [first, ...rest] = content;
      if (first.type === "p") inline(title, first.spans);
      else blocks(title, [first]);
      wrap.append(title);
      if (rest.length) wrap.append(blocks(el("div", "prompt-rest prose"), rest));
      return title;
    } else inline(title, content);
    wrap.append(title);
    return title;
  }
  function renderStep() {
    const entry = session.queue[session.index], step = entry.step;
    feedbackOpen = false;
    guessing = false;
    hinted = false;
    $("feedback").hidden = true;
    $("guess").setAttribute("aria-pressed", "false");
    const wrap = el("article", "step step-" + step.type);
    wrap.dataset.item = step.item;
    if (entry.repeats) wrap.append(el("p", "step-flag repair", "Let's fix this one"));
    else if (step.pretest) wrap.append(el("p", "step-flag guess-flag", "Take a guess: you'll learn this next"));
    else if (session.kind === "review" && step.topic) wrap.append(el("p", "step-flag", step.topic));
    current = RENDER[step.type](wrap, step);
    $("stage").replaceChildren(wrap);
    $("guess").hidden = !(GUESSABLE.has(step.type) && !step.pretest);
    $("hint").hidden = !(current.hint && !step.pretest);
    $("hint").disabled = false;
    padForBar();
    $("check").textContent = current.label || "Check";
    $("check").disabled = current.mode === "check" ? !current.ready() : false;
    $("check").className = "chunky primary";
    progress();
    window.scrollTo(0, 0);
    const title = wrap.querySelector(".step-heading");
    if (title) title.focus({preventScroll: true});
  }
  function changed() {
    if (!feedbackOpen && current && current.mode === "check") $("check").disabled = !current.ready();
  }
  function progress() {
    const done = session.resolved.size, total = session.total;
    $("progress-fill").style.setProperty("--progress", String(Math.min(1, done / total)));
    $("progress").setAttribute("aria-valuemax", String(total));
    $("progress").setAttribute("aria-valuenow", String(done));
    $("progress").setAttribute("aria-valuetext", `${done} of ${total} done`);
    const fixes = session.queue.slice(session.index + 1).filter(entry => entry.repeats).length;
    $("repair-count").hidden = !fixes;
    $("repair-count").textContent = `${fixes} to fix`;
  }
  function primary() {
    if (!session) return;
    if (feedbackOpen) return proceed();
    const entry = session.queue[session.index];
    if (current.mode === "continue") {
      if (current.finish) current.finish();
      session.resolved.add(entry.step.item);
      return proceed();
    }
    if (current.mode === "reveal") {
      current.reveal();
      current.mode = "continue";
      $("check").textContent = "Continue";
      $("check").disabled = false;
      return;
    }
    if (!current.ready()) return;
    const result = current.evaluate();
    result.hinted = hinted && result.correct;
    result.guessed = guessing && result.correct;
    $("hint").disabled = true;
    record(entry, result);
    feedback(entry, result);
  }
  function record(entry, result) {
    const step = entry.step;
    if (step.pretest) { session.resolved.add(step.item); return; }
    if (!session.first.has(step.item)) {
      // An answer found by guessing or with a hint is not yet known, so it comes back tomorrow.
      session.first.set(step.item, result.correct ? (result.guessed || result.hinted ? "guessed" : "correct") : "wrong");
      if (result.correct) session.xp += result.hinted ? 1 : 2;
    } else if (result.correct) session.xp += 1;
    if (result.correct || entry.repeats >= MAX_REPEATS) session.resolved.add(step.item);
    else session.queue.push({step, repeats: entry.repeats + 1});
  }
  function feedback(entry, result) {
    feedbackOpen = true;
    const pretest = entry.step.pretest, box = $("feedback");
    box.className = "feedback " + (pretest ? "neutral" : result.correct ? "good" : "bad");
    $("feedback-title").textContent = pretest
      ? (result.correct ? "Good guess" : "Now you know")
      : result.correct ? (result.guessed ? "Correct, but you guessed" : result.hinted ? "Correct, with a hint"
        : PRAISE[Math.floor(Math.random() * PRAISE.length)])
        : "Not quite";
    const body = $("feedback-body");
    body.replaceChildren(...result.body);
    if (result.guessed) body.append(el("p", "feedback-note", "Guessed answers come back tomorrow, so you can lock them in."));
    else if (result.hinted) body.append(el("p", "feedback-note", "Answers found with a hint come back tomorrow, so you can recall them on your own."));
    if (!result.correct && !pretest) {
      body.append(el("p", "feedback-note", entry.repeats < MAX_REPEATS
        ? "You'll see this one again at the end of the lesson." : "It comes back in tomorrow's review."));
    }
    if (result.explain && result.explain.length) body.append(blocks(el("div", "feedback-explain prose"), result.explain));
    $("next").className = "chunky " + (pretest ? "primary" : result.correct ? "good" : "bad");
    $("check").disabled = true;
    box.hidden = false;
    progress();
    if (!result.correct && !pretest && entry.repeats < MAX_REPEATS) {
      // The missed card visibly joins the end-of-lesson repair queue.
      const chip = $("repair-count");
      chip.classList.remove("bump");
      void chip.offsetWidth;
      chip.classList.add("bump");
    }
    $("feedback-title").focus({preventScroll: true});
  }
  function proceed() {
    if (!session) return;
    session.index += 1;
    if (session.index >= session.queue.length) return finish();
    renderStep();
  }
  $("check").addEventListener("click", primary);
  $("next").addEventListener("click", proceed);
  $("guess").addEventListener("click", () => {
    guessing = !guessing;
    $("guess").setAttribute("aria-pressed", String(guessing));
  });
  $("hint").addEventListener("click", () => {
    if (!session || feedbackOpen || hinted || !current || !current.hint) return;
    hinted = true;
    $("hint").disabled = true;
    const wrap = $("stage").querySelector(".step"), box = el("p", "hint-box");
    box.setAttribute("role", "status");
    box.append(el("strong", "", "Hint: "));
    const step = session.queue[session.index].step;
    if (step.hint) inline(box, step.hint);
    else current.hint(box);
    wrap.querySelector(".step-heading").after(box);
  });
  const hintText = (box, text) => box.append(document.createTextNode(text));
  function answerLine(label, spans) {
    const line = el("p", "answer-line");
    line.append(el("strong", "", label + " "));
    inline(line, spans);
    return line;
  }

  // Exercise types: each returns {mode, label?, ready(), evaluate()} or a continue/reveal controller.
  const RENDER = {
    teach(wrap, step) {
      heading(wrap, step.title);
      wrap.append(blocks(el("div", "prose teach-body"), step.body));
      if (step.visual) wrap.append(visual(step.visual));
      if (step.example && step.example.length) wrap.append(blocks(el("div", "prose teach-example"), step.example));
      return {mode: "continue", label: "Continue"};
    },
    choice(wrap, step) {
      heading(wrap, step.prompt);
      if (step.context && step.context.length) wrap.append(blocks(el("div", "context prose"), step.context));
      const options = shuffle(step.options), group = el("div", "options");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", "Answers");
      let chosen = null;
      const buttons = options.map((option, n) => {
        const choice = button("option");
        choice.setAttribute("aria-pressed", "false");
        const key = el("span", "key", n + 1);
        key.setAttribute("aria-hidden", "true");
        choice.append(key, inline(el("span", "option-text"), option.text));
        choice.addEventListener("click", () => {
          chosen = option;
          for (const other of buttons) other.setAttribute("aria-pressed", String(other === choice));
          changed();
        });
        group.append(choice);
        return choice;
      });
      wrap.append(group);
      // The automatic hint crosses out one wrong answer (when at least two wrong ones are offered).
      const crossOut = box => {
        const wrong = buttons.filter((choice, n) => !options[n].correct);
        const out = wrong[Math.floor(Math.random() * wrong.length)], index = buttons.indexOf(out);
        out.disabled = true;
        out.classList.add("is-out");
        out.setAttribute("aria-pressed", "false");
        out.setAttribute("aria-label", out.textContent + ", ruled out");
        if (chosen === options[index]) { chosen = null; changed(); }
        hintText(box, "One wrong answer is crossed out.");
      };
      const hint = step.hint ? true : options.length >= 3 ? crossOut : null;
      return {mode: "check", keys: buttons, hint, ready: () => chosen !== null, evaluate() {
        const right = options.find(option => option.correct);
        buttons.forEach((choice, n) => {
          choice.disabled = true;
          if (options[n].correct) choice.classList.add("is-correct");
          else if (options[n] === chosen) choice.classList.add("is-wrong");
        });
        const body = [inline(el("p", "why"), chosen.why)];
        if (!chosen.correct) body.push(answerLine("Answer:", right.text), inline(el("p", "why"), right.why));
        return {correct: chosen.correct, body, explain: step.explain};
      }};
    },
    truefalse(wrap, step) {
      heading(wrap, "True or false?");
      wrap.append(blocks(el("blockquote", "statement prose"), step.statement));
      const group = el("div", "truefalse");
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", "Answers");
      let chosen = null;
      const buttons = [true, false].map((value, n) => {
        const choice = button("option tf-option");
        choice.setAttribute("aria-pressed", "false");
        const key = el("span", "key", n + 1);
        key.setAttribute("aria-hidden", "true");
        choice.append(key, el("span", "option-text", value ? "True" : "False"));
        choice.addEventListener("click", () => {
          chosen = value;
          for (const other of buttons) other.setAttribute("aria-pressed", String(other === choice));
          changed();
        });
        group.append(choice);
        return choice;
      });
      wrap.append(group);
      return {mode: "check", keys: buttons, hint: Boolean(step.hint), ready: () => chosen !== null, evaluate() {
        const correct = chosen === step.answer;
        buttons.forEach((choice, n) => {
          choice.disabled = true;
          const value = n === 0;
          if (value === step.answer) choice.classList.add("is-correct");
          else if (value === chosen) choice.classList.add("is-wrong");
        });
        return {correct, body: [el("p", "why", `The statement is ${step.answer ? "true" : "false"}.`)], explain: step.explain};
      }};
    },
    match(wrap, step) {
      heading(wrap, step.prompt);
      const board = el("div", "match"), left = el("div", "match-col"), right = el("div", "match-col");
      left.setAttribute("role", "group");
      left.setAttribute("aria-label", "Terms");
      right.setAttribute("role", "group");
      right.setAttribute("aria-label", "Meanings");
      const live = el("p", "match-live visually-hidden");
      live.setAttribute("aria-live", "polite");
      let picked = null, mistakes = 0, matched = 0;
      const tile = (spans, pair, side) => {
        const node = button("tile");
        node.setAttribute("aria-pressed", "false");
        inline(node, spans);
        node.dataset.pair = String(pair);
        node.dataset.side = side;
        node.addEventListener("click", () => {
          if (picked && picked.dataset.side === side) picked.setAttribute("aria-pressed", "false");
          if (!picked || picked.dataset.side === side) {
            picked = node;
            node.setAttribute("aria-pressed", "true");
            return;
          }
          const other = picked;
          picked = null;
          other.setAttribute("aria-pressed", "false");
          if (other.dataset.pair === node.dataset.pair) {
            for (const done of [other, node]) {
              done.classList.add("matched");
              done.disabled = true;
              done.setAttribute("aria-label", done.textContent + ", matched");
            }
            matched += 1;
            live.textContent = matched === step.pairs.length ? "All pairs matched." : "Matched.";
            changed();
          } else {
            mistakes += 1;
            live.textContent = "Not a pair. Try again.";
            for (const miss of [other, node]) {
              miss.classList.remove("miss");
              void miss.offsetWidth;
              miss.classList.add("miss");
            }
          }
        });
        return node;
      };
      shuffle(step.pairs.map((pair, i) => [pair[0], i])).forEach(([spans, i]) => left.append(tile(spans, i, "left")));
      shuffle(step.pairs.map((pair, i) => [pair[1], i])).forEach(([spans, i]) => right.append(tile(spans, i, "right")));
      board.append(left, right);
      wrap.append(board, live);
      return {mode: "check", ready: () => matched === step.pairs.length, evaluate() {
        const correct = mistakes === 0;
        return {correct, body: [el("p", "why", correct ? "Every pair on the first try."
          : `All matched, with ${plural(mistakes, "wrong pair")} on the way.`)], explain: step.explain};
      }};
    },
    order(wrap, step) {
      heading(wrap, step.prompt);
      const answer = el("ol", "order-answer"), bank = el("div", "order-bank");
      answer.setAttribute("aria-label", "Your order");
      bank.setAttribute("role", "group");
      bank.setAttribute("aria-label", "Steps to place");
      const hint = el("p", "order-hint", "Tap the steps below in the order they happen.");
      let items = shuffle(step.steps.map((spans, i) => ({spans, i})));
      if (items.every((item, n) => item.i === n)) items = [...items.slice(1), items[0]];
      const placed = [];
      const draw = () => {
        answer.replaceChildren();
        placed.forEach((item, n) => {
          const li = el("li"), back = button("tile placed");
          inline(back, item.spans);
          back.setAttribute("aria-label", `Step ${n + 1}: ${back.textContent}. Remove`);
          back.addEventListener("click", () => {
            placed.splice(placed.indexOf(item), 1);
            item.node.hidden = false;
            draw();
            changed();
          });
          li.append(back);
          item.slot = li;
          answer.append(li);
        });
        hint.hidden = placed.length > 0;
      };
      for (const item of items) {
        const node = button("tile");
        inline(node, item.spans);
        node.addEventListener("click", () => {
          placed.push(item);
          node.hidden = true;
          draw();
          changed();
          const next = bank.querySelector("button:not([hidden])");
          (next || answer.querySelector("button:last-of-type") || node).focus();
        });
        item.node = node;
        bank.append(node);
      }
      wrap.append(answer, hint, bank);
      const clue = box => { hintText(box, "The first step is: "); inline(box, step.steps[0]); };
      return {mode: "check", hint: clue, ready: () => placed.length === step.steps.length, evaluate() {
        const correct = placed.every((item, n) => item.i === n);
        placed.forEach((item, n) => {
          item.slot.classList.add(item.i === n ? "is-correct" : "is-wrong");
          item.slot.querySelector("button").disabled = true;
        });
        const body = [];
        if (!correct) {
          body.push(el("p", "answer-line", "The order is:"));
          const list = el("ol", "answer-list");
          for (const spans of step.steps) list.append(inline(el("li"), spans));
          body.push(list);
        }
        return {correct, body, explain: step.explain};
      }};
    },
    fill(wrap, step) {
      heading(wrap, step.prompt);
      const line = el(step.code ? "pre" : "p", "fill-line" + (step.code ? " code" : ""));
      const blanks = [], bank = el("div", "fill-bank");
      bank.setAttribute("role", "group");
      bank.setAttribute("aria-label", "Word bank");
      step.parts.forEach((part, n) => {
        if (part) line.append(el("span", "", part));
        if (n < step.parts.length - 1) {
          const blank = button("blank");
          blank.setAttribute("aria-label", `Blank ${n + 1}, empty`);
          blank.addEventListener("click", () => {
            if (!blank.token) return;
            blank.token.hidden = false;
            blank.token = null;
            blank.textContent = "";
            blank.setAttribute("aria-label", `Blank ${n + 1}, empty`);
            changed();
          });
          blanks.push(blank);
          line.append(blank);
        }
      });
      for (const token of shuffle(step.tokens)) {
        const chip = button("tile token", token);
        chip.addEventListener("click", () => {
          const blank = blanks.find(b => !b.token);
          if (!blank) return;
          blank.token = chip;
          blank.textContent = token;
          blank.setAttribute("aria-label", `Blank ${blanks.indexOf(blank) + 1}: ${token}. Remove`);
          chip.hidden = true;
          changed();
        });
        bank.append(chip);
      }
      wrap.append(line, bank);
      const hint = box => hintText(box, `The ${blanks.length > 1 ? "first blank" : "answer"} starts with “${step.answer[0][0]}”.`);
      return {mode: "check", hint, ready: () => blanks.every(b => b.token), evaluate() {
        const correct = blanks.every((b, n) => b.textContent === step.answer[n]);
        blanks.forEach((b, n) => {
          b.disabled = true;
          b.classList.add(b.textContent === step.answer[n] ? "is-correct" : "is-wrong");
        });
        const body = [];
        if (!correct) {
          const filled = step.parts.map((part, n) => part + (n < step.answer.length ? step.answer[n] : "")).join("");
          const answer = el("p", "answer-line");
          answer.append(el("strong", "", "Answer: "), el(step.code ? "code" : "span", "", filled));
          body.push(answer);
        }
        return {correct, body, explain: step.explain};
      }};
    },
    spot(wrap, step) {
      heading(wrap, step.prompt);
      const listing = el("ol", "spot");
      listing.setAttribute("aria-label", `${step.lang.toUpperCase()} listing, one button per line`);
      let chosen = null;
      const lines = step.lines.map((text, n) => {
        const li = el("li"), line = button("spot-line");
        line.setAttribute("aria-pressed", "false");
        line.append(el("span", "spot-number", n + 1), el("code", "spot-code", text || " "));
        line.setAttribute("aria-label", `Line ${n + 1}: ${text.trim() || "blank"}`);
        line.addEventListener("click", () => {
          chosen = n;
          for (const other of lines) other.setAttribute("aria-pressed", String(other === line));
          changed();
        });
        li.append(line);
        listing.append(li);
        return line;
      });
      wrap.append(listing);
      return {mode: "check", hint: Boolean(step.hint), ready: () => chosen !== null, evaluate() {
        const correct = step.answers.includes(chosen);
        lines.forEach((line, n) => {
          line.disabled = true;
          if (step.answers.includes(n)) line.classList.add("is-correct");
          else if (n === chosen) line.classList.add("is-wrong");
        });
        const where = step.answers.map(n => n + 1).join(" and ");
        return {correct, body: [el("p", "why", correct ? `Yes, line ${chosen + 1}.`
          : `Look at line${step.answers.length > 1 ? "s" : ""} ${where}.`)], explain: step.explain};
      }};
    },
    explain(wrap, step) {
      heading(wrap, step.prompt);
      const label = el("label", "explain-label", "Your answer, in your own words");
      const box = el("textarea", "explain-text");
      box.id = "explain-text";
      box.rows = 4;
      box.maxLength = 2000;
      label.htmlFor = box.id;
      const privacy = el("p", "explain-note", "Only you see this. It isn't sent or saved.");
      wrap.append(label, box, privacy);
      const controller = {mode: "reveal", label: "Compare with key points", reveal() {
        box.readOnly = true;
        const section = el("section", "key-points");
        const title = el("h2", "", "Key points");
        title.tabIndex = -1;
        section.append(title, el("p", "explain-note", "Tick each point your answer covered."));
        const list = el("ul", "points");
        controller.boxes = step.points.map((spans, n) => {
          const li = el("li"), check = el("input"), text = el("label");
          check.type = "checkbox";
          check.id = `point-${n}`;
          text.htmlFor = check.id;
          inline(text, spans);
          li.append(check, text);
          list.append(li);
          return check;
        });
        section.append(list);
        if (step.model && step.model.length) {
          const model = el("details", "model");
          model.append(el("summary", "", "See a model answer"), blocks(el("div", "prose"), step.model));
          section.append(model);
        }
        wrap.append(section);
        title.focus();
      }, finish() {
        const ticked = controller.boxes.filter(check => check.checked).length;
        const ratio = ticked / controller.boxes.length;
        if (!session.explained.has(step.item)) {
          session.explained.set(step.item, ratio);
          session.xp += ratio >= 0.5 ? 2 : 1;
        }
      }};
      return controller;
    },
    type(wrap, step) {
      heading(wrap, step.prompt);
      if (step.context && step.context.length) wrap.append(blocks(el("div", "context prose"), step.context));
      const input = el("input", "type-input");
      input.type = "text";
      input.id = "type-answer";
      input.maxLength = 200;
      input.autocomplete = "off";
      input.spellcheck = false;
      input.setAttribute("autocapitalize", "off");
      input.setAttribute("autocorrect", "off");
      let screen = null;
      if (step.terminal) {
        screen = terminal([]);
        screen.classList.add("terminal-live");
        const row = el("label", "term-input-row");
        row.htmlFor = input.id;
        row.append(el("span", "term-prompt", "$"));
        input.setAttribute("aria-label", "Command");
        input.classList.add("term-input");
        screen.append(row);
        row.append(input);
        wrap.append(screen);
      } else {
        const label = el("label", "explain-label", "Your answer");
        label.htmlFor = input.id;
        wrap.append(label, input);
      }
      input.addEventListener("input", changed);
      input.addEventListener("keydown", event => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (feedbackOpen) proceed();
        else if (!$("check").disabled) primary();
      });
      setTimeout(() => { if (input.isConnected) input.focus({preventScroll: true}); }, 0);
      const hint = box => {
        if (step.terminal) {
          const words = step.answer.split(/\s+/);
          hintText(box, "It starts with ");
          box.append(el("code", "", words.slice(0, Math.min(2, words.length - 1) || 1).join(" ")), document.createTextNode("."));
        } else {
          const letters = step.answer.replace(/\s+/g, "").length;
          hintText(box, `It starts with “${step.answer[0]}” and has ${plural(letters, "character")}.`);
        }
      };
      return {mode: "check", label: step.terminal ? "Run" : "Check", hint, ready: () => input.value.trim() !== "", evaluate() {
        const correct = step.accept.includes(typedKey(input.value, step.terminal));
        input.readOnly = true;
        input.classList.add(correct ? "is-correct" : "is-wrong");
        if (screen && correct) {
          for (const line of step.output) screen.append(el("div", "term-line", line));
        }
        const body = [];
        if (!correct) {
          const answer = el("p", "answer-line");
          answer.append(el("strong", "", "Answer: "), el(step.terminal ? "code" : "span", "", step.answer));
          body.push(answer);
        }
        return {correct, body, explain: step.explain};
      }};
    },
    scenario(wrap, step) {
      heading(wrap, step.title);
      wrap.append(blocks(el("div", "prose scenario-situation"), step.situation));
      if (step.log.length) wrap.append(terminal(step.log));
      const controller = {mode: "check", label: "Finish", keys: [], done: 0, mistakes: 0,
        ready: () => controller.done === step.stages.length,
        evaluate() {
          const correct = controller.mistakes === 0;
          return {correct, body: [el("p", "why", correct ? "Solved with no wrong turns."
            : `Solved, with ${plural(controller.mistakes, "wrong turn")} on the way.`)], explain: step.explain};
        }};
      const stage = index => {
        const data = step.stages[index], box = el("section", "scenario-stage");
        const title = el("h2", "stage-title", `Step ${index + 1} of ${step.stages.length}`);
        title.tabIndex = -1;
        box.append(title, blocks(el("div", "prose stage-prompt"), data.prompt));
        const group = el("div", "options"), note = el("p", "why stage-why");
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", "Choices");
        note.setAttribute("aria-live", "polite");
        const options = shuffle(data.options);
        const buttons = options.map((option, n) => {
          const choice = button("option");
          const key = el("span", "key", n + 1);
          key.setAttribute("aria-hidden", "true");
          choice.append(key, inline(el("span", "option-text"), option.text));
          choice.addEventListener("click", () => {
            note.replaceChildren();
            inline(note, option.why);
            choice.disabled = true;
            if (!option.correct) {
              controller.mistakes += 1;
              choice.classList.add("is-wrong");
              return;
            }
            choice.classList.add("is-correct");
            for (const other of buttons) other.disabled = true;
            if (data.output.length) box.append(terminal(data.output));
            controller.done += 1;
            changed();
            if (index + 1 < step.stages.length) stage(index + 1);
            else { controller.keys = []; $("check").focus(); }
          });
          group.append(choice);
          return choice;
        });
        box.append(group, note);
        controller.keys = buttons;
        wrap.append(box);
        if (index) {
          title.focus({preventScroll: true});
          group.scrollIntoView({block: "nearest", behavior: motionOK() ? "smooth" : "auto"});
        }
      };
      stage(0);
      return controller;
    },
  };
  function typedKey(text, command) {
    if (command) return text.trim().replace(/^\$\s*/, "").split(/\s+/).filter(Boolean).join(" ");
    return text.toLowerCase().replace(/[^0-9a-z]/g, "");
  }
  // A read-only console: lines starting with "$ " are commands, the rest is output.
  function terminal(lines) {
    const screen = el("div", "terminal");
    screen.setAttribute("role", "group");
    screen.setAttribute("aria-label", "Terminal");
    for (const line of lines) screen.append(el("div", "term-line" + (line.startsWith("$ ") ? " term-cmd" : ""), line));
    return screen;
  }

  // Diagrams drawn from lesson data; the caption is the text alternative.
  function visual(data) {
    const figure = el("figure", "visual visual-" + data.kind), art = el("div", "visual-art");
    art.setAttribute("aria-hidden", "true");
    if (data.kind === "tree") {
      const box = item => {
        const node = el("div", "vbox tone-" + item.tone);
        node.append(el("span", "vbox-label", item.label));
        if (item.note) node.append(el("span", "vbox-note", item.note));
        if (item.children && item.children.length) {
          const kids = el("div", "vbox-kids");
          for (const child of item.children) kids.append(box(child));
          node.append(kids);
        }
        return node;
      };
      for (const item of data.boxes) art.append(box(item));
    } else {
      const names = {old: "Old version, serving", new: "New version, serving", starting: "New Pod starting", stopping: "Old Pod stopping"};
      const used = new Set();
      for (const row of data.rows) {
        const line = el("div", "slot-row");
        line.append(el("span", "slot-label", row.label));
        const cells = el("span", "slot-cells");
        for (const slot of row.slots) { cells.append(el("span", "slot slot-" + slot)); used.add(slot); }
        line.append(cells);
        art.append(line);
      }
      const legend = el("div", "slot-legend");
      for (const slot of used) {
        const item = el("span", "legend-item");
        item.append(el("span", "slot slot-" + slot), document.createTextNode(names[slot]));
        legend.append(item);
      }
      art.append(legend);
    }
    figure.append(art, el("figcaption", "", data.caption));
    return figure;
  }

  // Finishing ---------------------------------------------------------------------------------------
  function finish() {
    const s = session;
    session = null;
    current = null;
    const graded = [...s.first.values()];
    const firstRight = graded.filter(outcome => outcome !== "wrong").length;
    const accuracy = graded.length ? Math.round((100 * firstRight) / graded.length) : null;
    for (const [item, outcome] of s.first) schedule(item, outcome);
    for (const [item, ratio] of s.explained) schedule(item, ratio >= 0.5 ? "correct" : "weak");
    s.xp += s.kind === "lesson" ? 5 : 3;
    addXp(s.xp);
    const extended = extendStreak();
    if (s.kind === "lesson") {
      store.lessons[lessonKey(s.topic.id, s.lesson.id)] = {at: dayKey(), accuracy};
      lastFinished = {topic: s.topic.id, lesson: s.lesson.id};
    }
    const saved = save();
    history.replaceState(null, "", location.pathname + location.search);
    summary(s, {accuracy, extended, saved});
  }
  function summary(s, {accuracy, extended, saved}) {
    show("summary");
    const lesson = s.kind === "lesson";
    $("summary-title").textContent = lesson ? "Lesson complete" : "Review complete";
    $("summary-sub").textContent = lesson ? `${s.topic.title} · ${s.lesson.title}` : `${plural(s.total, "card")} from your review queue`;
    $("sum-accuracy").textContent = accuracy === null ? "–" : `${accuracy}%`;
    const streak = streakNow();
    $("sum-streak").textContent = `${plural(streak, "day")}${extended && streak > 1 ? ", extended" : ""}`;
    const xp = $("sum-xp");
    xp.textContent = `+${s.xp}`;
    const takeaways = $("sum-takeaways");
    takeaways.replaceChildren();
    for (const spans of lesson ? s.lesson.takeaways : []) takeaways.append(inline(el("li"), spans));
    takeaways.parentElement.hidden = !lesson;
    const tomorrow = addDays(dayKey(), 1);
    const cards = [...s.first.keys(), ...s.explained.keys()];
    const back = cards.filter(item => store.items[item] && store.items[item].due === tomorrow).length;
    const missed = [...s.first.values()].filter(outcome => outcome === "wrong").length;
    let review;
    if (lesson) {
      review = `${plural(back, "card")} from this lesson come${back === 1 ? "s" : ""} back tomorrow for a quick review`
        + (missed ? `, including the ${missed === 1 ? "one" : missed} you missed. ` : ". ")
        + "Each right answer after that sends a card further out: 3, 7, 16, then 35 days.";
    } else {
      const later = cards.length - back;
      review = `${plural(later, "card")} moved further out` + (back ? `; ${plural(back, "card")} come${back === 1 ? "s" : ""} back tomorrow.` : ".");
    }
    $("sum-review").textContent = review + (saved ? "" : " This browser couldn't save your progress.");
    const next = lesson ? following(s.topic.id, s.lesson.id) : null;
    const go = $("sum-next");
    go.hidden = !next;
    if (next) {
      go.textContent = `Next: ${next.topic.lessons[next.index].title}`;
      go.onclick = () => startLesson(next.topic.id, next.topic.lessons[next.index].id);
    }
    const about = $("summary").querySelector(".provenance");
    about.hidden = !lesson;
    if (lesson) {
      $("sum-provenance").textContent = s.info.provenance;
      const refs = $("sum-references");
      refs.replaceChildren();
      for (const url of s.info.references || []) {
        const link = el("a", "", url.replace(/^https:\/\//, ""));
        link.href = url;
        link.rel = "noopener noreferrer";
        link.target = "_blank";
        const li = el("li");
        li.append(link);
        refs.append(li);
      }
    }
    celebrate();
    $("summary-title").focus({preventScroll: true});
    window.scrollTo(0, 0);
  }
  // The one authored moment: a burst of the practice colours around the check mark.
  function celebrate() {
    const burst = $("burst");
    for (const old of burst.querySelectorAll(".spark")) old.remove();
    if (!motionOK()) return;
    for (let n = 0; n < 14; n++) {
      const spark = el("span", "spark spark-" + (n % 4));
      spark.style.setProperty("--angle", `${(360 / 14) * n + (n % 2 ? 9 : 0)}deg`);
      spark.style.setProperty("--reach", `${54 + (n % 3) * 14}px`);
      burst.append(spark);
    }
  }
  $("sum-home").addEventListener("click", () => showHome());

  // Leaving a lesson --------------------------------------------------------------------------------
  function openQuit() {
    $("quit-sheet").hidden = false;
    $("quit-stay").focus();
  }
  function closeQuit() {
    $("quit-sheet").hidden = true;
    $("quit").focus();
  }
  $("quit").addEventListener("click", openQuit);
  $("quit-stay").addEventListener("click", closeQuit);
  $("quit-leave").addEventListener("click", () => {
    $("quit-sheet").hidden = true;
    session = null;
    current = null;
    history.replaceState(null, "", location.pathname + location.search);
    showHome();
  });
  window.addEventListener("popstate", () => {
    if (session && !$("player").hidden) {
      history.pushState({practice: "lesson"}, "", "#lesson");
      openQuit();
    }
  });
  document.addEventListener("keydown", event => {
    if ($("player").hidden) return;
    if (!$("quit-sheet").hidden) {
      if (event.key === "Escape") { event.preventDefault(); closeQuit(); }
      else if (event.key === "Tab") {
        event.preventDefault();
        ($("quit-stay") === document.activeElement ? $("quit-leave") : $("quit-stay")).focus();
      }
      return;
    }
    if (event.key === "Escape") { event.preventDefault(); openQuit(); return; }
    if (event.target.closest("button, a, input, textarea, select, summary")) return;
    if (event.key === "Enter") {
      event.preventDefault();
      if (feedbackOpen) proceed();
      else if (!$("check").disabled) primary();
    } else if (!feedbackOpen && current && current.keys && /^[1-9]$/.test(event.key)) {
      const choice = current.keys[Number(event.key) - 1];
      if (choice && !choice.disabled) choice.click();
    }
  });
  $("retry").addEventListener("click", () => { if (retryAction) retryAction(); });

  // Start ---------------------------------------------------------------------------------------------
  async function boot() {
    notice("Loading practice…");
    show("none");
    try {
      const session_ = await call("/web/session", null, "GET");
      if (session_.status === 404) return signedOut("The SkillCoach web app isn't switched on right now.");
      if (session_.status === 403) return signedOut();
      if (!session_.ok) return notice(session_.data.error || "SkillCoach is temporarily unavailable.", true, boot);
      csrf = session_.data.csrf;
      const result = await call("/web/practice/catalog", {});
      if (result.status === 403) return signedOut();
      if (!result.ok) return notice(result.data.error || "Practice is temporarily unavailable.", true, boot);
      catalog = result.data;
      storeKey = STORE + catalog.progress_key;
      store = loadStore(storeKey);
      const featured = catalog.modules.find(module => module.topics.some(topic => topic.id === catalog.featured));
      moduleId = moduleById(store.module) ? store.module : (featured || catalog.modules[0]).id;
      if (location.hash === "#lesson") history.replaceState(null, "", location.pathname + location.search);
      showHome();
    } catch {
      notice("SkillCoach couldn't be reached. Check your connection.", true, boot);
    }
  }
  boot();
})();
