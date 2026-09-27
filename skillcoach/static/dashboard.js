(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const app = window.Telegram && window.Telegram.WebApp;
  let expiryTimer;
  let controller;
  let authenticated = false;
  let epoch = 0;
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (className) element.className = className;
    return element;
  };
  function clearPrivate(message, error = false) {
    epoch += 1;
    if (controller) controller.abort();
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
      if (day.objective) item.append(node("p", day.objective), node("p", day.practice));
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
    $("preferences").textContent = `Scheduled coaching ${data.preferences.paused ? "paused" : "active"} · Media: ${data.preferences.media} · Voice: ${data.preferences.voice ? "on" : "off"}`;
    $("updated").textContent = `Updated ${new Date(data.generated_at).toLocaleString()}`;
    $("notice").hidden = true;
    $("content").hidden = false;
    authenticated = true;
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => clearPrivate("For privacy, this view has expired. Reopen /dashboard from the bot."),
                             Math.max(0, data.auth_expires_at * 1000 - Date.now()));
  }
  async function refresh() {
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
