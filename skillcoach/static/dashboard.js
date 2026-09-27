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
    documentCsrf = ""; uploadId = null; uploadPreview = null; uploadBusy = false;
    labBusy = false; labRequests = {};
    $("document-file").value = ""; $("document-preview").hidden = true;
    for (const id of ["document-file", "document-kind", "document-confirm", "document-cancel", "document-choice"]) $(id).disabled = false;
    $("document-status").textContent = ""; $("document-preview-summary").textContent = "";
    authenticated = false;
    $("content").hidden = true;
    for (const id of ["learner-name", "target-role", "tasks", "plan-days", "skills", "interviews",
                      "done", "streak", "minutes", "graded", "preferences", "updated", "task-count",
                      "plan-status", "plan-rationale", "lab-items", "lab-catalog", "lab-count", "lab-status",
                      "lab-cost", "lab-gate"]) {
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
      if (task.detail) {
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
    const proposed = data.learning && data.learning.plan;
    documentCsrf = data.document_csrf || "";
    renderLabs(data.labs);
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
    $("content").hidden = false;
    authenticated = true;
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => clearPrivate("For privacy, this view has expired. Reopen /dashboard from the bot."),
                             Math.max(0, data.auth_expires_at * 1000 - Date.now()));
  }
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
