(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const telegram = window.Telegram && window.Telegram.WebApp;
  const framed = window.self !== window.top;
  let csrf = "", telegramSession = "", preview = null, overview = null, poll = null, sessionTimer = null, busy = false;
  let requestId = null;
  let materials = null, courseLimit = 10, courseVersion = 0, learnerVersion = 0;
  let lessonNext = null, deliveryNext = null, historyBusy = false, lastCourseButton = null;
  let epoch = 0, actionVersion = 0, pendingLogin = null, loginPollBusy = false, signedOut = false;
  const controllers = new Set();
  class StaleRequest extends Error {}
  const node = (tag, value, cls) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (cls) element.className = cls;
    return element;
  };
  const date = value => value ? new Date(value).toLocaleString("en-IN", {timeZone: "Asia/Kolkata"}) : "No bot interaction yet";
  function message(text, error = false) {
    $("message").textContent = text;
    $("message").classList.toggle("error", error);
    $("message").hidden = !text;
  }
  function invalidateRequests() {
    epoch += 1;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    clearInterval(poll); poll = null;
    loginPollBusy = false;
  }
  function clearPrivate(keepLogin = false) {
    invalidateRequests();
    csrf = ""; telegramSession = ""; preview = null; overview = null; requestId = null; busy = false; actionVersion += 1;
    materials = null; courseLimit = 10; courseVersion += 1; lastCourseButton = null;
    clearLearner();
    $("learner-select").replaceChildren(new Option("Choose a learner", ""));
    $("materials-index").hidden = true; $("course-review").hidden = true;
    $("materials-load").disabled = false; $("admin-course-more").hidden = true;
    $("admin-course-search").value = "";
    $("admin-course-module").replaceChildren(new Option("All modules", ""));
    for (const id of ["materials-status", "admin-course-count", "admin-course-list", "admin-labs", "admin-resources",
                      "admin-lab-notice", "admin-resource-notice", "course-review-title", "course-review-meta", "course-review-body"]) $(id).replaceChildren();
    if (!keepLogin) {
      pendingLogin = null; $("login-challenge").hidden = true;
      $("login-code").textContent = ""; $("telegram-login-link").removeAttribute("href");
    }
    clearTimeout(sessionTimer);
    $("console").hidden = true; $("login").hidden = false;
    $("refresh").hidden = true; $("logout").hidden = true;
    $("action-preview").hidden = true; $("action-result").hidden = true;
    for (const id of ["members", "invites", "jobs", "deliveries", "audit", "learning-plans", "result-messages", "action-fields",
                      "action-kind", "action-target", "preview-details", "preview-warnings", "summary-line",
                      "privacy-note", "limits", "lesson-feedback", "updated", "session-expiry", "preview-recipient", "preview-title"]) {
      $(id).replaceChildren();
    }
    $("invite-url").value = "";
    $("start-login").disabled = false; $("preview-action").disabled = false;
  }
  function showError(error) {
    if (error instanceof StaleRequest) return;
    if (error.status === 403) {
      if (framed || (telegram && telegram.initData)) { browserFallback(error.message); return; }
      clearPrivate();
    }
    message(error.message, true);
  }
  async function api(path, body, method = "POST", csrfOverride, telegramOverride) {
    const requestEpoch = epoch, controller = new AbortController();
    controllers.add(controller);
    const memoryToken = telegramOverride || telegramSession;
    const options = {method, cache: "no-store",
      credentials: memoryToken || (telegram && telegram.initData) ? "omit" : "same-origin",
      headers: {}, signal: controller.signal};
    if (memoryToken) {
      options.headers["X-Admin-Session"] = memoryToken;
      options.headers["X-Telegram-Init-Data"] = telegram.initData;
    }
    if (method !== "GET") {
      options.headers["Content-Type"] = "application/json";
      if (csrfOverride || csrf) options.headers["X-CSRF-Token"] = csrfOverride || csrf;
      options.body = JSON.stringify(body || {});
    }
    let response, data;
    try {
      response = await fetch(path, options);
      data = await response.json();
    } catch {
      if (requestEpoch !== epoch || controller.signal.aborted) throw new StaleRequest();
      throw new Error("Connection interrupted. Do not create a new action; retry the same confirmation to check its result.");
    } finally {
      controllers.delete(controller);
    }
    if (requestEpoch !== epoch || controller.signal.aborted) throw new StaleRequest();
    if (!response.ok) {
      const error = new Error(data.error || "The request could not be completed.");
      error.status = response.status; throw error;
    }
    return data;
  }
  function establish(session) {
    pendingLogin = null;
    csrf = session.csrf;
    telegramSession = session.session_token || "";
    $("login").hidden = true; $("refresh").hidden = false; $("logout").hidden = false;
    if (poll) { clearInterval(poll); poll = null; }
    clearTimeout(sessionTimer);
    sessionTimer = setTimeout(() => {
      clearPrivate();
      if (framed || (telegram && telegram.initData)) browserFallback("Your admin session expired.");
      else message("Your admin session expired. Sign in again.");
    }, Math.max(0, new Date(session.expires_at).getTime() - Date.now()));
    $("session-expiry").textContent = `Owner session expires ${date(session.expires_at)} IST.`;
  }
  async function signIn() {
    try {
      let session;
      if (telegram && telegram.initData) {
        session = await api("/admin/telegram-session", {init_data: telegram.initData});
      } else {
        try { session = await api("/admin/session", null, "GET"); }
        catch (error) {
          if (error instanceof StaleRequest || error.status !== 403) throw error;
          clearPrivate(); message("Owner sign-in is required."); return;
        }
      }
      establish(session); await refresh();
    } catch (error) {
      if (!(error instanceof StaleRequest)) {
        clearPrivate(); message(error.message, true);
        if (framed || (telegram && telegram.initData)) browserFallback(error.message);
      }
    }
  }
  const empty = (id, text) => $(id).append(node("li", text, "empty"));
  function pick(action, target = "owner", args = {}) {
    $("action-kind").value = action;
    $("action-target").value = target;
    fields();
    for (const [key, value] of Object.entries(args)) {
      const input = document.querySelector(`[name="${key}"]`);
      if (input) input.value = value;
    }
    $("actions").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
    $("action-kind").focus();
  }
  function actionButton(label, action, target, args) {
    const button = node("button", label);
    button.type = "button"; button.addEventListener("click", () => pick(action, target, args));
    return button;
  }
  function render(data) {
    overview = data;
    const names = new Map(data.learners.map(member => [member.id, member.name]));
    const active = data.learners.filter(member => member.status === "active").length;
    const pending = data.learners.filter(member => member.status === "pending").length;
    const failed = data.deliveries.filter(item => item.status === "failed").length;
    $("summary-line").textContent = `${active} active · ${pending} awaiting approval · ${failed} failed deliveries`;
    for (const id of ["members", "invites", "jobs", "deliveries", "audit", "learning-plans"]) $(id).replaceChildren();
    for (const member of data.learners) {
      const row = node("tr");
      const name = node("td");
      name.append(node("strong", member.name), node("span", member.id, "member-id"));
      const state = node("td"); state.append(node("span", member.status, `status status-${member.status}`));
      const progress = node("td");
      if (member.progress) {
        progress.append(node("span", `${member.progress.done}/${member.progress.assigned} tasks · ${member.progress.quizzes_completed} quizzes completed`));
        progress.append(node("span", `${member.progress.lessons_delivered} lessons delivered · ${member.ai_operations_today} AI operations today`, "detail"));
        progress.append(node("span", member.progress.paused ? "Notifications paused" : "Notifications active", "detail"));
      } else progress.append(node("span", "Progress temporarily unavailable", "detail"));
      const controls = node("td"), group = node("div", undefined, "row-actions");
      if (member.status === "pending") {
        group.append(actionButton("Approve", "approve", member.id), actionButton("Reject", "reject", member.id));
      }
      if (member.id !== "owner" && ["active", "pending"].includes(member.status)) {
        group.append(actionButton("Revoke", "revoke", member.id));
      }
      if (member.status === "active") group.append(actionButton("Choose action", "send_lesson", member.id));
      const inspect = node("button", "Learning details"); inspect.type = "button";
      inspect.addEventListener("click", () => {
        $("learner-select").value = member.id; loadLearner();
        $("learner-history").scrollIntoView(); $("learner-select").focus({preventScroll: true});
      });
      group.append(inspect);
      controls.append(group);
      row.append(name, state, progress, node("td", date(member.last_interaction)), controls);
      $("members").append(row);
      const learning = member.learning;
      const panel = node("li"), detail = node("div");
      detail.append(node("strong", member.name));
      if (!learning || !learning.shared) {
        detail.append(node("p", "Learning plan not shared. Guided setup and learner consent are required.", "detail"));
      } else {
        detail.append(node("p", `${learning.status} · ${learning.sessions_practiced}/5 sessions with all tasks completed · ${learning.streak} day streak`, "detail"));
        detail.append(node("p", learning.basis, "detail"));
        detail.append(node("p", `Active days this week: ${learning.active_days_this_week} · Last practice: ${learning.last_practice || "Not yet"}`, "detail"));
        if (learning.labs) {
          const labs = learning.labs;
          detail.append(node("p", `Labs: ${labs.verified} verified · ${labs.pending} pending · ${labs.required} required${labs.gate_blocked ? " · next week waits for required labs" : ""}`, "detail"));
        }
        const days = node("ol", undefined, "task-list");
        for (const day of learning.sessions) {
          const entry = node("li");
          entry.append(node("strong", `Day ${day.day}: ${day.topic}`),
            node("p", day.reason, "detail"),
            node("p", `${day.date || "Unscheduled"} · ${day.delivered ? "Delivered" : "Not delivered"} · ${day.tasks_done}/${day.tasks_total} tasks complete · Understanding: ${day.learner_understood ? "learner confirmed" : "not recorded"}`, "detail"));
          days.append(entry);
        }
        detail.append(days);
        if (!learning.sessions.length) detail.append(node("p", "No approved plan yet.", "detail"));
        for (const assessment of learning.assessments) {
          detail.append(node("p", `${assessment.date} ${assessment.kind}: ${assessment.correct}/${assessment.total}. Sampled assessment evidence, not overall mastery.`, "detail"));
        }
        if (learning.plan_id && member.status === "active") {
          detail.append(actionButton("Suggest a topic", "suggest_plan", member.id, {plan_id: learning.plan_id}));
        }
      }
      panel.append(detail); $("learning-plans").append(panel);
    }
    for (const invite of data.invitations) {
      const item = node("li"), detail = node("div");
      detail.append(node("strong", invite.label || "Unlabelled invitation"),
                    node("span", `${invite.id} · ${invite.status} · expires ${date(invite.expires_at)} IST`, "detail"));
      item.append(detail);
      if (invite.status === "open") item.append(actionButton("Cancel link", "revokeinvite", "owner", {invite_id: invite.id}));
      $("invites").append(item);
    }
    if (!data.invitations.length) empty("invites", "No invitations yet. Create one and share it privately.");
    for (const [id, items] of [["jobs", data.jobs], ["deliveries", data.deliveries]]) {
      for (const entry of items) {
        const item = node("li"), detail = node("div");
        detail.append(node("strong", names.get(entry.learner_id) || entry.learner_id));
        detail.append(node("span", `${entry.command || entry.scheduled_kind || entry.kind || "work"} · ${entry.status} · attempts ${entry.attempts}`, "detail"));
        if (entry.available_at) detail.append(node("span", `Eligible after ${date(entry.available_at)} IST`, "detail"));
        if (entry.error_code) detail.append(node("span", entry.error_code, "detail"));
        item.append(detail);
        if (entry.status === "failed") item.append(actionButton("Review retry", "retry", entry.learner_id));
        $(id).append(item);
      }
      if (!items.length) empty(id, "No pending or failed work.");
    }
    for (const event of data.audit) {
      const item = node("li"), detail = node("div");
      detail.append(node("span", `${event.action} · ${names.get(event.subject_id) || event.subject_id}`),
                    node("span", event.source, "detail"));
      item.append(node("time", date(event.created_at)), detail);
      $("audit").append(item);
    }
    if (!data.audit.length) empty("audit", "Access and confirmed admin actions will appear here.");
    const oldAction = $("action-kind").value, oldTarget = $("action-target").value;
    $("action-kind").replaceChildren(...Object.entries(data.actions).map(([key, title]) => {
      const option = node("option", title); option.value = key; return option;
    }));
    $("action-target").replaceChildren(...data.learners.map(member => {
      const option = node("option", `${member.name} (${member.status})`); option.value = member.id; return option;
    }));
    if (oldAction) $("action-kind").value = oldAction;
    if (oldTarget && names.has(oldTarget)) $("action-target").value = oldTarget;
    if (!$("action-fields").children.length) fields();
    $("limits").textContent = `Configured limits: ${data.limits.members} active learners including you, ${data.limits.ai_operations_per_learner} AI operations per learner/day. These do not guarantee free-tier capacity.`;
    $("privacy-note").textContent = data.privacy;
    const feedback = data.lesson_feedback;
    if (feedback) {
      const reasons = {wrong: "wrong", outdated: "outdated", confusing: "confusing", hard: "too hard", easy: "too easy"};
      const reported = Object.entries(feedback.reports).filter(([, count]) => count > 0)
        .map(([code, count]) => `${count} ${reasons[code] || "other"}`);
      $("lesson-feedback").textContent = `Lesson feedback, totals across all learners: ${feedback.ratings.up} useful · ${feedback.ratings.down} not useful`
        + (reported.length ? ` · reported: ${reported.join(", ")}` : " · no problem reports");
    }
    $("updated").textContent = `Updated ${date(data.generated_at)} IST`;
    const selected = $("learner-select").value;
    $("learner-select").replaceChildren(new Option("Choose a learner", ""),
      ...data.learners.map(member => new Option(`${member.name} (${member.status})`, member.id)));
    if (data.learners.some(member => member.id === selected)) $("learner-select").value = selected;
    else clearLearner();
    $("console").hidden = false;
  }
  function clearLearner() {
    learnerVersion += 1; historyBusy = false; lessonNext = deliveryNext = null;
    $("learner-detail").hidden = true; $("learner-refresh").disabled = true;
    $("lessons-more").hidden = $("deliveries-more").hidden = true;
    for (const id of ["learner-status", "learner-summary", "upcoming-notice", "learner-upcoming",
                      "learner-lessons", "learner-deliveries", "delivery-notice"]) $(id).replaceChildren();
  }
  function courseButton(topic, version, label = "Review lesson") {
    const button = node("button", label); button.type = "button";
    button.setAttribute("aria-label", `${label}: ${topic.title}`);
    button.addEventListener("click", () => { lastCourseButton = button; openCourse(topic.id, version); });
    return button;
  }
  async function loadLearner(more = null) {
    const learner = $("learner-select").value;
    if (more && historyBusy) return;
    if (!more) clearLearner();
    if (!learner || !csrf) return;
    const version = learnerVersion, requestEpoch = epoch;
    historyBusy = true; $("learner-refresh").disabled = true;
    $("lessons-more").disabled = $("deliveries-more").disabled = true;
    $("learner-status").textContent = more ? "Loading older records…" : "Loading learner history…";
    try {
      const data = await api("/admin/learner", {learner,
        lesson_before: more === "lessons" ? lessonNext : null,
        delivery_before: more === "deliveries" ? deliveryNext : null});
      if (version !== learnerVersion || learner !== $("learner-select").value) return;
      if (!data.learning.shared) {
        clearLearner(); $("learner-status").textContent = data.upcoming.status;
        $("learner-refresh").disabled = false; return;
      }
      $("learner-summary").textContent = `${data.learning.status} · ${data.learning.streak} day streak · ${data.learning.sessions_practiced}/5 sessions with all tasks complete`;
      $("upcoming-notice").textContent = data.upcoming.status;
      $("learner-upcoming").replaceChildren();
      for (const slot of data.upcoming.slots) {
        const item = node("li");
        item.append(node("strong", `${slot.title} · ${date(slot.at)} IST`),
          node("p", slot.topic ? slot.topic.title : "Content depends on learning progress"),
          node("p", slot.detail, "detail"));
        if (slot.topic) item.append(courseButton(slot.topic, null, "Review shared reference"));
        $("learner-upcoming").append(item);
      }
      if (!data.upcoming.slots.length) empty("learner-upcoming", "No automatic next delivery to preview.");
      if (more !== "deliveries") {
        if (!more) $("learner-lessons").replaceChildren();
        for (const lesson of data.lessons) {
          const item = node("li");
          item.append(node("strong", lesson.topic.title),
            node("p", `${lesson.date || "Date unavailable"} · ${lesson.source}${lesson.version ? " · " + lesson.version : ""}`, "detail"),
            node("p", lesson.delivered_at ? `Lesson delivery completed ${date(lesson.delivered_at)} IST`
              : "No completed lesson-delivery receipt; check the bot delivery log.", "detail"),
            node("p", `${lesson.tasks_done}/${lesson.tasks_total} tasks complete`, "detail"));
          if (lesson.topic.id) item.append(courseButton(lesson.topic, lesson.version,
            lesson.version ? "Review versioned reference" : "Review current reference"));
          $("learner-lessons").append(item);
        }
        if (!more && !data.lessons.length) empty("learner-lessons", "No saved lessons for this learner.");
        lessonNext = data.lesson_next; $("lessons-more").hidden = !lessonNext;
      }
      if (more !== "lessons") {
        if (!more) $("learner-deliveries").replaceChildren();
        for (const delivery of data.deliveries) {
          const item = node("li"), counts = delivery.messages;
          item.append(node("strong", `${delivery.title} · ${delivery.status}`),
            node("p", `Created ${date(delivery.created_at)} IST · processing: ${delivery.processing}`, "detail"),
            node("p", `${counts.sent}/${counts.total} messages sent · ${counts.pending} pending · ${counts.failed} failed · ${counts.suppressed} suppressed · ${delivery.media_sent} media sent`, "detail"));
          if (["pending", "running", "failed"].includes(delivery.processing)) {
            item.append(node("p", `Eligible after ${date(delivery.eligible_at)} IST; not a promised send time.`, "detail"));
          }
          if (delivery.last_sent_at) item.append(node("p", `Last successful send ${date(delivery.last_sent_at)} IST`, "detail"));
          $("learner-deliveries").append(item);
        }
        if (!more && !data.deliveries.length) empty("learner-deliveries", "No retained delivery records for this learner.");
        deliveryNext = data.delivery_next; $("deliveries-more").hidden = !deliveryNext;
      }
      $("delivery-notice").textContent = data.notice;
      $("learner-detail").hidden = false;
      $("learner-status").textContent = `History updated ${date(data.generated_at)} IST`;
    } catch (error) {
      if (version !== learnerVersion || requestEpoch !== epoch) return;
      $("learner-status").textContent = "Could not load history. Use Refresh learner to retry.";
      showError(error);
    } finally {
      if (requestEpoch === epoch && version === learnerVersion) {
        historyBusy = false; $("learner-refresh").disabled = false;
        $("lessons-more").disabled = $("deliveries-more").disabled = false;
      }
    }
  }
  function safeLink(url, title) {
    if (!/^https:\/\/[A-Za-z0-9.-]+\//.test(url)) return node("span", title);
    const link = node("a", title); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
    return link;
  }
  function renderMaterialIndex() {
    const words = $("admin-course-search").value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const group = $("admin-course-module").value;
    const topics = materials.courses.modules.flatMap(module => module.topics.map(topic => ({...topic, module})))
      .filter(topic => (!group || topic.module.id === group) && words.every(word =>
        (topic.title + " " + topic.module.title).toLowerCase().includes(word)));
    $("admin-course-list").replaceChildren();
    for (const topic of topics.slice(0, courseLimit)) {
      const item = node("li"), detail = node("div");
      detail.append(node("strong", topic.title), node("p", topic.module.title, "detail"));
      item.append(detail, courseButton(topic, materials.courses.version)); $("admin-course-list").append(item);
    }
    if (!topics.length) empty("admin-course-list", "No matching lessons. Try another search or module.");
    $("admin-course-count").textContent = `Showing ${Math.min(courseLimit, topics.length)} of ${topics.length} stored lessons`;
    $("admin-course-more").hidden = topics.length <= courseLimit;
  }
  async function loadMaterials() {
    const requestEpoch = epoch;
    $("materials-load").disabled = true; $("materials-status").textContent = "Loading stored materials…";
    try {
      materials = await api("/admin/materials", {});
      $("admin-course-module").replaceChildren(new Option("All modules", ""),
        ...materials.courses.modules.map(module => new Option(module.title, module.id)));
      courseLimit = 10; renderMaterialIndex();
      $("materials-status").textContent = `${materials.courses.total} lessons · ${materials.courses.modules.length} modules · version ${materials.courses.version}. ${materials.courses.notice}`;
      $("admin-resource-notice").textContent = materials.resources.notice + " " + materials.resources.rights;
      $("admin-resources").replaceChildren();
      for (const resource of materials.resources.items) {
        const item = node("li");
        item.append(safeLink(resource.url, resource.title), node("p", `${resource.provider} · ${resource.account_label}`, "detail"),
          node("p", resource.summary), node("p", resource.start), node("p", resource.cost_note, "detail"));
        $("admin-resources").append(item);
      }
      $("admin-lab-notice").textContent = `${materials.labs.items.length} templates · ${materials.labs.review}. ${materials.labs.enabled ? "" : "Lab delivery is disabled. "}${materials.labs.cost} Placeholder tokens below are not learner credentials. Scenario questions and answer keys stay in the bot.`;
      $("admin-labs").replaceChildren();
      for (const lab of materials.labs.items) {
        const item = node("li"), detail = node("details");
        detail.append(node("summary", `${lab.title} · about ${lab.minutes} min`), node("p", lab.goal));
        for (const route of lab.routes) {
          detail.append(node("h3", route.label));
          if (!route.steps.length) detail.append(node("p", "Learners practice through question-bound scenarios in Telegram."));
          const steps = node("ol", undefined, "lab-steps");
          for (const step of route.steps) steps.append(node("li", step));
          detail.append(steps);
          for (const step of route.cleanup) detail.append(node("p", "Cleanup: " + step));
        }
        for (const url of lab.references) detail.append(safeLink(url, url));
        item.append(detail); $("admin-labs").append(item);
      }
      if ($("course-review").hidden) $("materials-index").hidden = false;
    } catch (error) {
      if (requestEpoch !== epoch) return;
      $("materials-status").textContent = "Materials could not be loaded. Use Load learning materials to retry.";
      showError(error);
    } finally { if (requestEpoch === epoch) $("materials-load").disabled = false; }
  }
  async function openCourse(topic, version) {
    const current = ++courseVersion, requestEpoch = epoch;
    $("course-review").hidden = true; $("course-review-body").replaceChildren();
    $("materials-status").textContent = "Opening shared course reference…";
    $("materials").scrollIntoView();
    try {
      if (!version) {
        if (!materials) await loadMaterials();
        if (current !== courseVersion || requestEpoch !== epoch || !materials) return;
        version = materials.courses.version;
      }
      const data = await api("/admin/course", {topic, version});
      if (current !== courseVersion) return;
      const lesson = data.lesson, body = $("course-review-body");
      const {prose, renderBlocks, lessonSection, walkthrough} = window.SkillCoachLesson;
      $("course-review-title").textContent = lesson.title;
      $("course-review-meta").textContent = `Version ${lesson.version} · ${lesson.review}`;
      body.replaceChildren();
      for (const section of lesson.sections) {
        const element = lessonSection(section.heading); element.append(prose(section.blocks)); body.append(element);
      }
      if (lesson.walkthrough) body.append(walkthrough(lesson.walkthrough));
      const exercises = lessonSection("Practice exercises");
      for (const exercise of lesson.extension) exercises.append(node("h3", `${exercise.title} · about ${exercise.minutes} min`), prose(exercise.blocks));
      body.append(exercises);
      for (const note of lesson.notes) {
        const element = lessonSection(note.heading); element.append(prose(note.blocks)); body.append(element);
      }
      const interview = lessonSection("Sample interview practice");
      interview.append(prose(lesson.interview.question));
      const points = node("ul", undefined, "prose checklist");
      for (const point of lesson.interview.points) points.append(renderBlocks(node("li"), point));
      interview.append(points); body.append(interview);
      const references = lessonSection("Official references"), links = node("ul", undefined, "lesson-refs");
      for (const url of lesson.references) { const item = node("li"); item.append(safeLink(url, url)); links.append(item); }
      references.append(links); body.append(references);
      $("materials-index").hidden = true; $("course-review").hidden = false;
      $("materials-status").textContent = "Read-only preview. No learner or delivery state has changed.";
      $("course-review-title").focus({preventScroll: true});
    } catch (error) {
      if (current !== courseVersion || requestEpoch !== epoch) return;
      $("materials-status").textContent = "This reference could not be opened. Retry its review button.";
      showError(error);
    }
  }
  $("learner-select").addEventListener("change", () => loadLearner());
  $("learner-refresh").addEventListener("click", () => loadLearner());
  $("lessons-more").addEventListener("click", () => loadLearner("lessons"));
  $("deliveries-more").addEventListener("click", () => loadLearner("deliveries"));
  $("materials-load").addEventListener("click", loadMaterials);
  for (const id of ["admin-course-search", "admin-course-module"]) {
    $(id).addEventListener(id.endsWith("search") ? "input" : "change", () => {
      if (materials) { courseLimit = 10; renderMaterialIndex(); }
    });
  }
  $("admin-course-more").addEventListener("click", () => { courseLimit += 10; renderMaterialIndex(); });
  $("course-review-close").addEventListener("click", () => {
    courseVersion += 1; $("course-review").hidden = true; $("course-review-body").replaceChildren();
    $("materials-index").hidden = !materials;
    if (lastCourseButton && lastCourseButton.isConnected) lastCourseButton.focus();
  });
  async function refresh() {
    if (!csrf || busy) return;
    const requestEpoch = epoch;
    $("refresh").disabled = true;
    try { render(await api("/admin/data", {})); message(""); if ($("learner-select").value) await loadLearner(); }
    catch (error) { showError(error); }
    finally { if (requestEpoch === epoch) $("refresh").disabled = false; }
  }
  function invalidatePreview() {
    actionVersion += 1;
    preview = null; requestId = null; $("action-preview").hidden = true;
    $("confirm-checkbox").checked = false; $("execute-action").disabled = true;
  }
  function field(label, name, tag = "input", type = "text") {
    const wrapper = node("label", label), input = node(tag);
    input.name = name;
    if (tag === "input") input.type = type;
    if (tag === "input" || tag === "textarea") input.maxLength = name === "argument" ? 16000 : 300;
    wrapper.append(input); $("action-fields").append(wrapper); return input;
  }
  function fields() {
    invalidatePreview(); $("action-fields").replaceChildren();
    const action = $("action-kind").value;
    const ownerOnly = ["invite", "revokeinvite", "owner_command"].includes(action);
    $("action-target").disabled = ownerOnly;
    if (ownerOnly) $("action-target").value = "owner";
    if (action === "invite") field("Invitation label (optional)", "label").maxLength = 100;
    if (action === "revokeinvite") field("Invitation ID", "invite_id");
    if (["send_lesson", "schedule_quiz"].includes(action)) field("Cloud / DevOps topic", "topic");
    if (action === "schedule_quiz") field("Due date and time (Asia/Kolkata)", "at", "input", "datetime-local");
    if (action === "suggest_plan") {
      const select = field("Suggested catalog topic", "topic_id", "select");
      for (const [key, title] of Object.entries(overview.topics || {})) {
        const option = node("option", title); option.value = key; select.append(option);
      }
      const plan = field("Approved plan ID", "plan_id");
      plan.readOnly = true;
      const member = overview.learners.find(item => item.id === $("action-target").value);
      plan.value = member && member.learning ? member.learning.plan_id || "" : "";
    }
    if (action === "owner_command") {
      const select = field("Your bot command", "command", "select");
      for (const [name, description] of Object.entries(overview.owner_commands)) {
        const option = node("option", `/${name} — ${description}`); option.value = name; select.append(option);
      }
      field("Command argument (when required)", "argument", "textarea");
    }
    $("action-help").textContent = action === "owner_command"
      ? "Commands run in your own chat. Submit answers, complete tasks and manage private setup documents in Telegram, not here."
      : "The next step previews the exact recipient and effect. Nothing is executed yet.";
  }
  $("action-kind").addEventListener("change", fields);
  $("action-target").addEventListener("change", () => {
    if ($("action-kind").value === "suggest_plan") fields();
    else invalidatePreview();
  });
  $("action-fields").addEventListener("input", invalidatePreview);
  $("new-invite").addEventListener("click", () => pick("invite"));
  $("action-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy) return;
    const args = {};
    for (const input of $("action-fields").querySelectorAll("[name]")) {
      args[input.name] = input.name === "at" && input.value
        ? input.value + (input.value.length === 16 ? ":00" : "") + "+05:30" : input.value;
    }
    if (!requestId) requestId = crypto.randomUUID();
    const requestEpoch = epoch, version = actionVersion;
    busy = true; $("preview-action").disabled = true;
    try {
      const result = await api("/admin/action/preview", {request_id: requestId, action: $("action-kind").value,
                        target: $("action-target").value, arguments: args});
      if (version !== actionVersion) throw new StaleRequest();
      preview = result;
      $("preview-title").textContent = preview.preview.title;
      $("preview-recipient").textContent = `Recipient: ${preview.preview.recipient} (${preview.preview.recipient_id})`;
      $("preview-details").replaceChildren(...preview.preview.details.map(value => node("li", value)));
      $("preview-warnings").replaceChildren(...preview.preview.warnings.map(value => node("li", value)));
      $("preview-delivery").textContent = preview.preview.delivery;
      $("action-preview").hidden = false; $("action-result").hidden = true;
      $("confirm-checkbox").checked = false; $("execute-action").disabled = true;
      message("Review the action and recipient before confirming.");
    } catch (error) { showError(error); }
    finally { if (requestEpoch === epoch) { busy = false; $("preview-action").disabled = false; } }
  });
  $("confirm-checkbox").addEventListener("change", () => {
    $("execute-action").disabled = !$("confirm-checkbox").checked || !preview || busy;
  });
  $("cancel-preview").addEventListener("click", () => { invalidatePreview(); message("Preview cancelled. Nothing was executed."); });
  $("execute-action").addEventListener("click", async () => {
    if (!preview || !$("confirm-checkbox").checked || busy) return;
    const requestEpoch = epoch, version = actionVersion;
    busy = true; $("execute-action").disabled = true;
    try {
      const result = await api("/admin/action/execute", {request_id: preview.request_id, confirmation: preview.confirmation});
      if (version !== actionVersion) throw new StaleRequest();
      $("result-messages").replaceChildren(...result.messages.map(value => node("p", value)));
      const link = result.messages.join("\n").match(/https:\/\/t\.me\/[A-Za-z0-9_]+\?start=invite_[A-Za-z0-9_-]{32}/);
      $("invite-result").hidden = !link;
      $("invite-url").value = link ? link[0] : "";
      $("action-result").hidden = false;
      invalidatePreview();
      message(result.state === "queued" ? "Queued. Delivery health shows when processing finishes." : "Request handled. Review the result below.");
    } catch (error) { showError(error); }
    finally {
      if (requestEpoch === epoch) {
        busy = false; $("execute-action").disabled = !preview || !$("confirm-checkbox").checked;
        if (!preview) await refresh();
      }
    }
  });
  $("copy-invite").addEventListener("click", async () => {
    const requestEpoch = epoch;
    try {
      await navigator.clipboard.writeText($("invite-url").value);
      if (requestEpoch === epoch) message("Invitation copied. Share it privately with one person.");
    } catch {
      if (requestEpoch === epoch) { $("invite-url").focus(); $("invite-url").select(); message("Copy is unavailable. Select and copy the invitation field manually."); }
    }
  });
  function pollLogin() {
    clearInterval(poll);
    poll = setInterval(async () => {
      if (document.hidden || !pendingLogin || loginPollBusy) return;
      if (Date.now() >= new Date(pendingLogin.expires_at).getTime()) {
        clearInterval(poll); poll = null; pendingLogin = null; message("Sign-in expired. Start again."); return;
      }
      const requestEpoch = epoch;
      loginPollBusy = true;
      try {
        const session = await api("/admin/login/status", {});
        if (session.authenticated) { establish(session); await refresh(); }
      } catch (error) {
        if (!(error instanceof StaleRequest)) { clearInterval(poll); poll = null; showError(error); }
      } finally {
        if (requestEpoch === epoch) loginPollBusy = false;
      }
    }, 3000);
  }
  $("start-login").addEventListener("click", async () => {
    signedOut = false;
    clearPrivate();
    const requestEpoch = epoch;
    $("start-login").disabled = true;
    try {
      const data = await api("/admin/login/start", {});
      $("login-code").textContent = data.code; $("telegram-login-link").href = data.telegram_url;
      $("login-challenge").hidden = false;
      pendingLogin = data; pollLogin();
      message("Open the request in Telegram and approve only the matching code.");
    } catch (error) { showError(error); }
    finally { if (requestEpoch === epoch) $("start-login").disabled = false; }
  });
  $("refresh").addEventListener("click", refresh);
  $("open-browser").addEventListener("click", event => {
    if (telegram && typeof telegram.openLink === "function") {
      event.preventDefault();
      telegram.openLink(new URL("/admin", location.href).href);
    }
  });
  $("logout").addEventListener("click", async () => {
    const previousCsrf = csrf, previousTelegramSession = telegramSession;
    signedOut = true;
    clearPrivate();
    try {
      await api("/admin/logout", {}, "POST", previousCsrf, previousTelegramSession);
      if (framed || previousTelegramSession) browserFallback("Signed out.");
      else message("Signed out.");
    }
    catch (error) { showError(error); }
  });
  if (telegram) {
    telegram.ready();
    const theme = () => {
      document.body.classList.toggle("telegram-dark", telegram.colorScheme === "dark");
      document.body.classList.toggle("telegram-light", telegram.colorScheme !== "dark");
    };
    theme(); telegram.onEvent("themeChanged", theme);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearPrivate(true);
    else if (pendingLogin) pollLogin();
    else if (!signedOut && (!framed || (telegram && telegram.initData))) signIn();
  });
  function browserFallback(errorText) {
    clearPrivate();
    $("start-login").hidden = true;
    $("open-browser").hidden = false;
    $("open-browser").href = new URL("/admin", location.href).href;
    message((errorText ? errorText + " " : "") +
      "Reopen using /admin in Telegram for a fresh owner login, or use the browser approval option.", Boolean(errorText));
  }
  if (framed && !(telegram && telegram.initData)) browserFallback();
  else signIn();
})();
