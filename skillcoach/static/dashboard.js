(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const app = window.Telegram && window.Telegram.WebApp;
  let expiryTimer;
  let controller;
  let authenticated = false;
  let epoch = 0;
  let documentCsrf = "", uploadId = null, uploadPreview = null, uploadBusy = false, uploadController;
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
    documentCsrf = ""; uploadId = null; uploadPreview = null; uploadBusy = false;
    $("document-file").value = ""; $("document-preview").hidden = true;
    for (const id of ["document-file", "document-kind", "document-confirm", "document-cancel", "document-choice"]) $(id).disabled = false;
    $("document-status").textContent = ""; $("document-preview-summary").textContent = "";
    authenticated = false;
    $("content").hidden = true;
    for (const id of ["learner-name", "target-role", "tasks", "plan-days", "skills", "interviews",
                      "done", "streak", "minutes", "graded", "preferences", "updated", "task-count",
                      "plan-status", "plan-rationale"]) {
      $(id).replaceChildren();
    }
    $("plan-bot-link").hidden = true; $("plan-bot-link").removeAttribute("href");
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = false;
    clearTimeout(expiryTimer);
  }
  function empty(id, message) { $(id).append(node("li", message, "empty")); }
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
    if (uploadBusy) return;
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
  async function uploadRequest(path, body, json = false) {
    const requestEpoch = epoch, token = new AbortController();
    uploadController = token;
    const options = {method: "POST", cache: "no-store", credentials: "omit", signal: token.signal,
      headers: {"X-Telegram-Init-Data": app.initData, "X-CSRF-Token": documentCsrf}, body};
    if (json) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const data = await response.json();
    if (requestEpoch !== epoch || token.signal.aborted) return null;
    if (!response.ok) {
      if (response.status === 403) clearPrivate("Session expired. Reopen /dashboard to update your documents.");
      throw new Error(data.error || "Upload failed. Retry the same request.");
    }
    return data;
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
