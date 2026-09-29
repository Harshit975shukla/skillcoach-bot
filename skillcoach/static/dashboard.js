(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const app = window.Telegram && window.Telegram.WebApp;
  let expiryTimer;
  let controller;
  let authenticated = false;
  let epoch = 0;
  let documentCsrf = "", uploadId = null, uploadPreview = null, uploadBusy = false, uploadController;
  let labBusy = false, labController, labRequests = {};
  let resourceCatalog = [], resourceLimit = 6;
  const LESSON = /^[0-9a-f]{20}$/;
  const linked = new URLSearchParams(location.search).get("lesson");
  let wantedLesson = linked && LESSON.test(linked) ? linked : null, shownLesson = null, lessonController;
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (className) element.className = className;
    return element;
  };
  function clearPrivate(message, error = false) {
    epoch += 1;
    if (controller) controller.abort();
    if (uploadController) uploadController.abort();
    if (labController) labController.abort();
    if (lessonController) lessonController.abort();
    hideLesson();
    documentCsrf = ""; uploadId = null; uploadPreview = null; uploadBusy = false;
    labBusy = false; labRequests = {};
    resourceCatalog = []; resourceLimit = 6;
    $("resource-search").value = ""; $("resource-group").value = ""; $("resource-no-account").checked = false;
    $("resource-more").hidden = true;
    $("document-file").value = ""; $("document-preview").hidden = true;
    for (const id of ["document-file", "document-kind", "document-confirm", "document-cancel", "document-choice"]) $(id).disabled = false;
    $("document-status").textContent = ""; $("document-preview-summary").textContent = "";
    authenticated = false;
    $("content").hidden = true;
    for (const id of ["learner-name", "target-role", "tasks", "plan-days", "skills", "interviews",
                      "done", "streak", "minutes", "graded", "preferences", "updated", "task-count",
                      "plan-status", "plan-rationale", "lab-items", "lab-catalog", "lab-count", "lab-status",
                      "lab-cost", "lab-gate", "lesson-list", "resource-list", "resource-count",
                      "resource-notice", "resource-rights"]) {
      $(id).replaceChildren();
    }
    $("lab-gate").hidden = true;
    $("plan-bot-link").hidden = true; $("plan-bot-link").removeAttribute("href");
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = false;
    clearTimeout(expiryTimer);
  }
  function empty(id, message) { $(id).append(node("li", message, "empty")); }
  const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
  const day = value => value ? new Date(value + "T00:00:00").toLocaleDateString(undefined,
    {weekday: "short", day: "numeric", month: "short", year: "numeric"}) : "";
  function inline(parent, spans) {
    for (const span of spans || []) {
      if (span.t === "code") parent.append(node("code", span.v));
      else if (span.t === "b") parent.append(node("strong", span.v));
      else parent.append(document.createTextNode(String(span.v)));
    }
    return parent;
  }
  function codeBlock(block) {
    const figure = node("figure", undefined, "code-block"), bar = node("figcaption");
    const copy = node("button", "Copy"), pre = node("pre"), code = node("code", block.text);
    copy.type = "button";
    copy.setAttribute("aria-label", `Copy ${block.lang || "code"} example`);
    pre.tabIndex = 0; pre.setAttribute("role", "region");
    pre.setAttribute("aria-label", `${block.lang || "Code"} example`);
    pre.append(code); bar.append(node("span", block.lang || "code"), copy); figure.append(bar, pre);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(block.text);
        copy.textContent = "Copied";
      } catch {
        const range = document.createRange(), selection = getSelection();
        range.selectNodeContents(code); selection.removeAllRanges(); selection.addRange(range);
        copy.textContent = "Selected, copy it";
      }
      setTimeout(() => { copy.textContent = "Copy"; }, 2500);
    });
    return figure;
  }
  function renderBlocks(parent, blocks) {
    for (const block of blocks || []) {
      if (block.type === "code") parent.append(codeBlock(block));
      else if (block.type === "ul" || block.type === "ol") {
        const list = node(block.type);
        if (block.type === "ol" && block.start > 1) list.start = block.start;
        for (const item of block.items) list.append(inline(node("li"), item));
        parent.append(list);
      } else parent.append(inline(node(block.type === "h" ? "h3" : "p"), block.spans));
    }
    return parent;
  }
  const prose = blocks => renderBlocks(node("div", undefined, "prose"), blocks);
  function lessonSection(heading, id) {
    const section = node("section", undefined, "lesson-section");
    if (id) section.id = id;
    section.append(node("h2", heading));
    return section;
  }
  function renderExercise(exercise) {
    const item = node("li");
    const status = exercise.status === "done" ? "Done" : exercise.status === "skipped" ? "Skipped" : "Open";
    item.append(node("span", exercise.title, "task-title"),
                node("p", `About ${exercise.minutes} min · ${status}`, "task-meta"), prose(exercise.blocks));
    if (exercise.status === "pending") {
      const command = node("span", undefined, "task-command");
      command.append(node("code", `/complete ${exercise.id}`));
      item.append(command);
    }
    return item;
  }
  function lessonStatus(message, error = false) {
    $("lesson-page").hidden = true;
    $("lesson-status").textContent = message;
    $("lesson-status").classList.toggle("error", error);
    $("lesson-status").hidden = false;
  }
  function hideLesson() {
    shownLesson = null;
    for (const id of ["lesson-title", "lesson-meta", "lesson-jump", "lesson-body", "lesson-feedback", "lesson-status"]) {
      $(id).replaceChildren();
    }
    $("lesson-view").hidden = true; $("lesson-page").hidden = true;
    if (app && app.BackButton) app.BackButton.hide();
  }
  function renderLesson(lesson) {
    $("lesson-title").textContent = lesson.title;
    $("lesson-meta").textContent = [day(lesson.date), lesson.review].filter(Boolean).join(" · ");
    const body = $("lesson-body"), jump = $("lesson-jump");
    body.replaceChildren(); jump.replaceChildren();
    const anchor = (label, id) => { const link = node("a", label); link.href = "#" + id; jump.append(link); };
    if (!lesson.available) {
      body.append(node("p", "The full text of this older lesson was not kept. Its tracked exercises are below.", "guidance"));
    }
    for (const section of lesson.sections || []) {
      const element = lessonSection(section.heading); element.append(prose(section.blocks)); body.append(element);
    }
    if (lesson.exercises.length) {
      anchor("Exercises", "lesson-exercises");
      const element = lessonSection("Today's exercises", "lesson-exercises");
      element.append(node("p", "Tracked in your practice list. Record each one in the bot with its command.", "section-description"));
      const list = node("ol", undefined, "task-list");
      for (const exercise of lesson.exercises) list.append(renderExercise(exercise));
      element.append(list); body.append(element);
    }
    if (lesson.extension && lesson.extension.length) {
      const element = lessonSection("Optional extension practice");
      element.append(node("p", "Outside today's time target and not tracked.", "section-description"));
      for (const extra of lesson.extension) {
        element.append(node("h3", `${extra.title} · about ${extra.minutes} min`), prose(extra.blocks));
      }
      body.append(element);
    }
    for (const note of lesson.notes || []) {
      const element = lessonSection(note.heading); element.append(prose(note.blocks)); body.append(element);
    }
    if (lesson.interview) {
      anchor("Interview", "lesson-interview");
      const element = lessonSection("Interview practice", "lesson-interview");
      element.append(prose(lesson.interview.question));
      if (lesson.interview.points.length) {
        const details = node("details"), list = node("ul", undefined, "prose checklist");
        details.append(node("summary", "Show the answer checklist"));
        for (const point of lesson.interview.points) list.append(renderBlocks(node("li"), point));
        details.append(list); element.append(details);
      }
      element.append(node("p", "Answer out loud in about two minutes first. For a graded round, send /interview in the bot.", "section-description"));
      body.append(element);
    }
    const references = (lesson.references || []).filter(url => /^https:\/\/[A-Za-z0-9.-]+\//.test(url));
    if (references.length) {
      anchor("References", "lesson-references");
      const element = lessonSection("Official references", "lesson-references"), list = node("ul", undefined, "lesson-refs");
      for (const url of references) {
        const link = node("a", url.replace(/^https:\/\//, "")), item = node("li");
        link.href = url; link.rel = "noopener noreferrer"; link.target = "_blank";
        link.addEventListener("click", event => {
          if (app && app.openLink) { event.preventDefault(); app.openLink(url); }
        });
        item.append(link); list.append(item);
      }
      element.append(list); body.append(element);
    }
    if (lesson.resources && lesson.resources.length) {
      anchor("Free resources", "lesson-resources");
      const element = lessonSection("Optional free learning", "lesson-resources");
      element.append(node("p", "External links, not required practice. They do not change your progress or lab status.",
                          "section-description"), resourceList(lesson.resources));
      body.append(element);
    }
    const ratings = {up: "Useful", down: "Not useful"};
    $("lesson-feedback").textContent = lesson.feedback in ratings
      ? `You rated this lesson “${ratings[lesson.feedback]}”. You can change it with the buttons at the end of the lesson in Telegram.`
      : "Rate this lesson with the buttons at the end of the lesson in Telegram. Only the button you pick is stored.";
    $("lesson-feedback").hidden = !lesson.available;
    $("lesson-status").hidden = true;
    $("lesson-page").hidden = false;
  }
  async function openLesson(id) {
    if (!authenticated || !app || !app.initData || !LESSON.test(id)) return;
    wantedLesson = id; shownLesson = null;
    if (lessonController) lessonController.abort();
    const token = lessonController = new AbortController(), requestEpoch = epoch;
    $("content").hidden = true; $("lesson-view").hidden = false;
    lessonStatus("Opening your lesson…");
    if (app.BackButton) app.BackButton.show();
    window.scrollTo(0, 0);
    try {
      const response = await fetch("/app/lesson", {
        method: "POST", cache: "no-store", credentials: "omit", signal: token.signal,
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({init_data: app.initData, lesson: id}),
      });
      const data = await response.json();
      if (requestEpoch !== epoch || token.signal.aborted) return;
      if (response.status === 403) { clearPrivate(data.error || "Session expired. Reopen /dashboard from the bot.", true); return; }
      shownLesson = id;
      if (!response.ok) { lessonStatus(data.error || "This lesson could not be opened.", true); return; }
      renderLesson(data.lesson);
    } catch (error) {
      if (requestEpoch === epoch && error.name !== "AbortError") {
        lessonStatus("Could not load this lesson. Check your connection, then tap Refresh.", true);
      }
    }
  }
  function closeLesson() {
    wantedLesson = null;
    if (lessonController) lessonController.abort();
    hideLesson();
    if (authenticated) { $("content").hidden = false; $("lessons").scrollIntoView(); }
  }
  function labRoute(lab, route) {
    const details = node("details");
    details.append(node("summary", route.label));
    if (route.route === "scenario") {
      details.append(node("p", "Runs inside the bot: four decisions with explanations. Pass with 3 of 4. Free, no cloud account.", "task-detail"));
      const command = node("span", undefined, "task-command");
      command.append(node("code", `/lab ${lab.lab_id}`));
      details.append(command);
      return details;
    }
    const steps = node("ol", undefined, "lab-steps");
    for (const step of route.steps) steps.append(node("li", step));
    details.append(steps);
    if (route.cleanup.length) {
      details.append(node("p", "Cleanup — right after verification", "lab-subhead"));
      const cleanup = node("ul", undefined, "lab-cleanup");
      for (const step of route.cleanup) cleanup.append(node("li", step));
      details.append(cleanup);
    }
    details.append(node("p", "Submit: " + route.submit, "task-detail"));
    return details;
  }
  function resourceList(items) {
    const list = node("ul", undefined, "resource-list");
    for (const resource of items) {
      if (!/^https:\/\/[A-Za-z0-9.-]+\//.test(resource.url)) continue;
      const item = node("li"), link = node("a", resource.title);
      link.href = resource.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.referrerPolicy = "no-referrer";
      link.addEventListener("click", event => {
        if (app && app.openLink) { event.preventDefault(); app.openLink(resource.url); }
      });
      item.append(link, node("p", `${resource.provider} · ${resource.kind} · ${resource.level}`, "task-meta"),
        node("p", resource.summary), node("p", `${resource.account_label}. ${resource.cost_note}`, "resource-cost"));
      const details = node("details");
      details.append(node("summary", "Where to start and source details"), node("p", resource.start),
        node("p", `Link/access checked ${resource.checked_at}; not a full course audit. ${resource.rights_note}`, "task-meta"));
      item.append(details); list.append(item);
    }
    return list;
  }
  function renderResourceLibrary() {
    const group = $("resource-group").value, query = $("resource-search").value.trim().toLowerCase();
    const tokens = query.split(/\s+/).filter(Boolean);
    const items = resourceCatalog.filter(resource => {
      const text = [resource.title, resource.provider, resource.tags, resource.summary, ...(resource.modules || [])]
        .join(" ").toLowerCase();
      return (!group || resource.group === group || (resource.modules || []).includes(group))
        && (!$("resource-no-account").checked || resource.account !== "required")
        && tokens.every(token => text.includes(token));
    });
    $("resource-list").replaceChildren(...resourceList(items.slice(0, resourceLimit)).children);
    $("resource-count").textContent = `${Math.min(resourceLimit, items.length)} of ${items.length} resources`;
    $("resource-more").hidden = items.length <= resourceLimit;
    if (!items.length) empty("resource-list", resourceCatalog.length
      ? "No matching resources. Try a broader topic or change the filters."
      : "The resource library is unavailable in this view. Tap Refresh or use /resources in the bot.");
  }
  function renderLabs(labs) {
    for (const id of ["lab-items", "lab-catalog"]) $(id).replaceChildren();
    $("lab-gate").hidden = true; $("lab-cost").textContent = ""; $("lab-count").textContent = "";
    if (!labs || !labs.enabled) {
      empty("lab-items", labs ? "Hands-on labs are turned off right now. Lessons and quizzes continue."
                              : "Labs appear after your learning profile is set up.");
      $("lab-catalog-heading").hidden = true;
      return;
    }
    $("lab-catalog-heading").hidden = false;
    const pending = labs.items.filter(lab => lab.status !== "verified");
    $("lab-count").textContent = `${pending.length} pending`;
    const required = labs.gate.required_pending;
    if (required) {
      $("lab-gate").hidden = false;
      $("lab-gate").textContent = labs.gate.blocked
        ? `Next week's plan is waiting for ${plural(required, "required lab")}. Verify below or in the bot and it is prepared automatically.`
          + (labs.carry_available ? " Once every 28 days you can send /labcarry in the bot to move them into next week instead." : "")
        : `${plural(required, "required lab")} to verify before Sunday's review. Quizzes do not wait for labs.`;
    }
    labs.items.forEach((lab, index) => {
      const item = node("li");
      item.append(node("span", lab.title, "task-title"));
      item.append(node("p", `~${lab.minutes} min · ${lab.required ? "Required" : "Optional"}${lab.carried ? " · carried over" : ""} · assigned ${lab.assigned_date}`, "task-meta"));
      const state = lab.status === "verified" ? `Verified${lab.verified_route ? " · " + lab.verified_route : ""}`
        : lab.blocking ? "Needed before next week's plan" : lab.status === "needs_fix" ? "Needs a fix" : "Not verified yet";
      item.append(node("span", state, "lab-state" + (lab.blocking ? " blocking" : "")));
      item.append(node("p", lab.goal, "lab-reason"));
      if (lab.reason) item.append(node("p", "Last check: " + lab.reason, "lab-reason"));
      if (lab.status === "verified") {
        if (lab.cleanup === "reminder") item.append(node("p", `Delete the AWS resources to avoid charges, then send /labcleanup ${lab.lab_id} <your verified link> in the bot.`, "lab-reason"));
        if (lab.cleanup === "confirmed") item.append(node("p", "AWS cleanup confirmed.", "lab-reason"));
        $("lab-items").append(item);
        return;
      }
      if (lab.token) {
        const token = node("p", "Your lab token ", "lab-token");
        token.append(node("code", lab.token));
        item.append(token);
      }
      for (const route of lab.routes) item.append(labRoute(lab, route));
      const refs = lab.references.filter(url => /^https:\/\/[A-Za-z0-9.-]+\//.test(url));
      if (refs.length) {
        const details = node("details"), list = node("ul", undefined, "lab-refs");
        details.append(node("summary", "Official references"));
        for (const url of refs) {
          const link = node("a", url); link.href = url; link.rel = "noopener noreferrer"; link.target = "_blank";
          const entry = node("li"); entry.append(link); list.append(entry);
        }
        details.append(list); item.append(details);
      }
      if (lab.resources && lab.resources.length) {
        const details = node("details");
        details.append(node("summary", "Optional free learning (does not verify this lab)"), resourceList(lab.resources));
        item.append(details);
      }
      if (lab.routes.some(route => route.accepts_link)) {
        const form = node("form", undefined, "lab-form"), label = node("label", "Repository or AWS lab link");
        const input = node("input"), button = node("button", "Check link");
        input.type = "url"; input.required = true; input.maxLength = 2048; input.autocomplete = "off";
        input.inputMode = "url"; input.spellcheck = false; input.id = `lab-link-${index}`; input.className = "lab-input";
        input.placeholder = "https://";
        label.htmlFor = input.id; button.type = "submit"; button.className = "lab-button";
        form.append(label, input, button);
        form.addEventListener("submit", event => { event.preventDefault(); submitLab(lab.id, input); });
        item.append(form);
      }
      $("lab-items").append(item);
    });
    if (!labs.items.length) empty("lab-items", "No labs yet. Approved lessons add labs here; the bot also lists them with /labs.");
    const assigned = new Set(labs.items.map(lab => lab.lab_id));
    for (const lab of labs.catalog.filter(entry => !assigned.has(entry.lab_id))) {
      const item = node("li");
      item.append(node("span", `${lab.title} · ~${lab.minutes} min`));
      const command = node("span"); command.append(node("code", `/lab ${lab.lab_id}`));
      item.append(command);
      $("lab-catalog").append(item);
    }
    if (!$("lab-catalog").children.length) empty("lab-catalog", "Every lab in the catalog is already on your list.");
    $("lab-cost").textContent = labs.cost_note;
    setLabControls(labBusy);
  }
  function setLabControls(disabled) {
    for (const element of document.querySelectorAll(".lab-input, .lab-button")) element.disabled = disabled || !documentCsrf;
  }
  function render(data) {
    $("learner-name").textContent = data.profile.name;
    $("target-role").textContent = data.profile.target_role || "A plan built around your goals starts with /setup.";
    $("setup-note").hidden = data.profile.setup_complete;
    $("task-count").textContent = `${data.stats.pending} open`;
    for (const id of ["tasks", "plan-days", "skills", "interviews"]) $(id).replaceChildren();
    for (const task of data.tasks) {
      const item = node("li");
      item.append(node("span", task.title, "task-title"));
      item.append(node("p", `${task.skill} · ${task.estimated_minutes} min estimate · assigned ${task.assigned_date}`, "task-meta"));
      if (task.detail_blocks && task.detail_blocks.length) {
        const details = node("details");
        details.append(node("summary", "Exercise details"), prose(task.detail_blocks));
        item.append(details);
      } else if (task.detail) {
        const details = node("details");
        details.append(node("summary", "Exercise details"), node("p", task.detail, "task-detail"));
        item.append(details);
      }
      const command = node("span", undefined, "task-command");
      command.append(node("code", `/complete ${task.id}`));
      item.append(command);
      $("tasks").append(item);
    }
    if (!data.tasks.length) empty("tasks", "No open tasks. Your next lesson will add practice here.");
    $("lesson-list").replaceChildren();
    for (const lesson of data.lessons || []) {
      const item = node("li"), text = node("div"), button = node("button", "Read");
      text.append(node("span", lesson.topic, "plan-topic"),
                  node("p", day(lesson.date) + (lesson.delivered ? "" : " · still being delivered"), "task-meta"));
      button.type = "button"; button.setAttribute("aria-label", `Read ${lesson.topic}`);
      button.addEventListener("click", () => openLesson(lesson.id));
      item.append(text, button);
      $("lesson-list").append(item);
    }
    if (!(data.lessons || []).length) empty("lesson-list", "Lessons you receive appear here, so you can reread them anytime.");
    const proposed = data.learning && data.learning.plan;
    documentCsrf = data.document_csrf || "";
    renderLabs(data.labs);
    resourceCatalog = data.resources ? data.resources.items : [];
    $("resource-notice").textContent = data.resources ? data.resources.notice : "";
    $("resource-rights").textContent = data.resources ? data.resources.rights : "";
    renderResourceLibrary();
    $("document-preview-button").disabled = !documentCsrf || !data.documents || !data.documents.can_update;
    if (!uploadBusy && !uploadPreview) {
      $("document-status").textContent = data.documents
        ? `Resume: ${data.documents.resume_saved ? "saved privately" : "not added"} · Job description: ${data.documents.jd_saved ? "saved privately" : "not added"}.`
        : "Document updates require profile setup.";
    }
    $("plan-status").textContent = proposed
      ? `${proposed.approved ? "Approved" : "Awaiting your approval"} · version ${proposed.version} · ${proposed.minutes} minutes/session target`
      : `Setup: ${data.learning ? data.learning.stage : "existing learning"}`;
    $("plan-rationale").textContent = proposed ? proposed.rationale : "";
    if (data.bot_url && /^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(data.bot_url)) {
      $("plan-bot-link").href = data.bot_url + "?start=" + (proposed ? "plan" : "onboard");
      $("plan-bot-link").hidden = false;
    }
    for (const day of proposed ? proposed.sessions : data.plan) {
      const item = node("li");
      item.append(node("span", day.date, "plan-date"), node("span", day.topic, "plan-topic"));
      if (day.objective) item.append(node("p", "Objective: " + day.objective, "plan-detail"),
                                    node("p", "Practice: " + day.practice, "plan-detail"));
      $("plan-days").append(item);
    }
    if (!proposed && !data.plan.length) empty("plan-days", "No weekly plan yet. Complete /onboard and approve your proposal.");
    $("done").textContent = `${data.stats.done} / ${data.stats.total}`;
    $("streak").textContent = `${data.stats.streak} days`;
    $("minutes").textContent = `${data.stats.minutes_practiced} min`;
    $("graded").textContent = data.stats.answers_graded;
    for (const skill of data.skills) {
      const item = node("li");
      item.append(node("span", skill.skill), node("span", `${skill.done} / ${skill.total} tasks`));
      $("skills").append(item);
    }
    if (!data.skills.length) empty("skills", "Skill practice appears after tasks are assigned.");
    for (const interview of data.recent_interviews) {
      const item = node("li");
      item.append(node("span", `${interview.score}/10`, "interview-score"));
      item.append(node("p", interview.question));
      item.append(node("p", interview.feedback, "interview-feedback"));
      $("interviews").append(item);
    }
    if (!data.recent_interviews.length) empty("interviews", "No graded interviews yet. Try /interview in the bot.");
    const awaiting = data.learning && data.learning.stage !== "legacy" && !data.learning.active_plan_id;
    $("preferences").textContent = `Scheduled coaching ${data.preferences.paused ? "paused" : awaiting ? "waiting for plan approval" : "active"} · Media: ${data.preferences.media} · Voice: ${data.preferences.voice ? "on" : "off"}`;
    $("updated").textContent = `Updated ${new Date(data.generated_at).toLocaleString()}`;
    $("notice").hidden = true;
    $("content").hidden = Boolean(wantedLesson);
    authenticated = true;
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => clearPrivate("For privacy, this view has expired. Reopen /dashboard from the bot."),
                             Math.max(0, data.auth_expires_at * 1000 - Date.now()));
    if (wantedLesson && shownLesson !== wantedLesson) openLesson(wantedLesson);
  }
  for (const id of ["resource-search", "resource-group", "resource-no-account"]) {
    $(id).addEventListener(id === "resource-search" ? "input" : "change", () => {
      resourceLimit = 6; renderResourceLibrary();
    });
  }
  $("resource-more").addEventListener("click", () => { resourceLimit += 6; renderResourceLibrary(); });
  async function refresh() {
    if (uploadBusy || labBusy) return;
    if (!app || !app.initData) {
      clearPrivate("Open this private dashboard using /dashboard in the Telegram bot. A shared URL alone cannot grant access.");
      $("refresh").disabled = true;
      return;
    }
    if (controller) controller.abort();
    controller = new AbortController();
    const activeController = controller, requestEpoch = ++epoch;
    $("refresh").disabled = true;
    $("refresh").textContent = "Refreshing…";
    try {
      const response = await fetch("/app/data", {
        method: "POST", cache: "no-store", credentials: "omit",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({init_data: app.initData}), signal: activeController.signal,
      });
      const data = await response.json();
      if (requestEpoch !== epoch || activeController.signal.aborted) return;
      if (!response.ok) {
        clearPrivate(data.error || "Access could not be verified. Reopen the dashboard from Telegram.", true);
        return;
      }
      render(data);
    } catch (error) {
      if (requestEpoch === epoch && error.name !== "AbortError") clearPrivate("Could not load private progress. Check your connection and tap Refresh.", true);
    } finally {
      if (requestEpoch === epoch || activeController === controller) {
        $("refresh").disabled = false;
        $("refresh").textContent = "Refresh";
      }
    }
  }
  $("refresh").addEventListener("click", refresh);
  async function privateRequest(path, body, json, slot) {
    const requestEpoch = epoch, token = new AbortController();
    if (slot === "lab") labController = token; else uploadController = token;
    const options = {method: "POST", cache: "no-store", credentials: "omit", signal: token.signal,
      headers: {"X-Telegram-Init-Data": app.initData, "X-CSRF-Token": documentCsrf}, body};
    if (json) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const data = await response.json();
    if (requestEpoch !== epoch || token.signal.aborted) return null;
    if (!response.ok) {
      if (response.status === 403) clearPrivate("Session expired. Reopen /dashboard from the bot to continue.");
      throw new Error(data.error || "Request failed. Retry the same request.");
    }
    return data;
  }
  const uploadRequest = (path, body, json = false) => privateRequest(path, body, json, "upload");
  async function submitLab(assignmentId, input) {
    if (labBusy || uploadBusy || !documentCsrf) return;
    const url = input.value.trim();
    if (!/^https:\/\/\S{1,2040}$/.test(url)) {
      $("lab-status").textContent = "Paste one complete https:// link: your GitHub repository or the AWS lab URL."; return;
    }
    const previous = labRequests[assignmentId];
    const requestId = previous && previous.url === url ? previous.id : crypto.randomUUID();
    labRequests[assignmentId] = {id: requestId, url};
    const requestEpoch = epoch;
    let submitted = false;
    labBusy = true; setLabControls(true);
    $("lab-status").textContent = "Checking your lab link. This can take a few seconds…";
    try {
      const result = await privateRequest("/app/labs/submit", {request_id: requestId, assignment_id: assignmentId, url}, true, "lab");
      if (!result) return;
      delete labRequests[assignmentId];
      submitted = true;
      $("lab-status").textContent = result.duplicate
        ? "That check was already submitted. The bot sends its result in Telegram."
        : "Check submitted. The bot sends the result in Telegram, and this page updates.";
    } catch (error) {
      if (requestEpoch === epoch) $("lab-status").textContent = (error.message || "Connection interrupted.") + " Check link again retries the same request.";
    } finally {
      if (requestEpoch === epoch) { labBusy = false; setLabControls(false); }
    }
    if (submitted && requestEpoch === epoch) refresh();
  }
  function invalidateUpload() {
    uploadId = null; uploadPreview = null; $("document-preview").hidden = true;
  }
  $("document-file").addEventListener("change", invalidateUpload);
  $("document-kind").addEventListener("change", invalidateUpload);
  $("document-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (uploadBusy || !documentCsrf) return;
    const file = $("document-file").files[0];
    if (!file || file.size > 256 * 1024) {
      $("document-status").textContent = "Choose one PDF or TXT file up to 256 KB."; return;
    }
    const requestEpoch = epoch;
    uploadBusy = true; $("document-preview-button").disabled = true;
    $("document-file").disabled = true; $("document-kind").disabled = true;
    $("document-status").textContent = "Reading your document privately. Your saved document has not changed.";
    uploadId ||= crypto.randomUUID();
    const body = new FormData();
    body.append("request_id", uploadId); body.append("kind", $("document-kind").value); body.append("file", file);
    try {
      const result = await uploadRequest("/app/documents/preview", body);
      if (!result) return;
      uploadPreview = result;
      $("document-preview-summary").textContent = `${result.characters} characters extracted. Confirm to save privately; this is not an AI assessment.`;
      $("document-choice").value = "keep";
      $("document-choice").querySelector('[value="revise"]').disabled = !result.can_revise;
      $("document-preview").hidden = false;
      $("document-status").textContent = "Review how you want to use this document.";
    } catch (error) {
      if (requestEpoch === epoch) $("document-status").textContent = error.message || "Connection interrupted; retry the same upload.";
    } finally {
      if (requestEpoch === epoch) {
        uploadBusy = false; $("document-preview-button").disabled = false;
        $("document-file").disabled = false; $("document-kind").disabled = false;
      }
    }
  });
  async function confirmUpload(choice) {
    if (uploadBusy || !uploadPreview) return;
    uploadBusy = true;
    const requestEpoch = epoch;
    $("document-confirm").disabled = true; $("document-cancel").disabled = true;
    $("document-file").disabled = true; $("document-kind").disabled = true; $("document-choice").disabled = true;
    try {
      const result = await uploadRequest("/app/documents/confirm", {
        request_id: uploadPreview.request_id, confirmation: uploadPreview.confirmation, choice,
      }, true);
      if (!result) return;
      invalidateUpload(); $("document-file").value = "";
      $("document-status").textContent = result.cancelled ? "Upload cancelled. Your previous document is unchanged."
        : "Update queued safely. The bot will confirm when saved. Your learning history will not be reset.";
    } catch (error) {
      if (requestEpoch === epoch) $("document-status").textContent = error.message || "Connection interrupted. Retry the same confirmation.";
    } finally {
      if (requestEpoch === epoch) {
        uploadBusy = false; $("document-confirm").disabled = false; $("document-cancel").disabled = false;
        $("document-file").disabled = false; $("document-kind").disabled = false; $("document-choice").disabled = false;
      }
    }
  }
  $("document-confirm").addEventListener("click", () => confirmUpload($("document-choice").value));
  $("document-cancel").addEventListener("click", () => confirmUpload("cancel"));
  $("lesson-back").addEventListener("click", closeLesson);
  if (app && app.BackButton) app.BackButton.onClick(closeLesson);
  if (app) {
    const theme = () => {
      document.body.classList.toggle("telegram-dark", app.colorScheme === "dark");
      document.body.classList.toggle("telegram-light", app.colorScheme !== "dark");
    };
    app.ready();
    app.expand();
    theme();
    app.onEvent("themeChanged", theme);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearPrivate("Refreshing your private progress…");
    else refresh();
  });
  setInterval(() => { if (!document.hidden && authenticated) refresh(); }, 60000);
  refresh();
})();
