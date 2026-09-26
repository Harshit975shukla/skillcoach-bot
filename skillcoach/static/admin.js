(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const telegram = window.Telegram && window.Telegram.WebApp;
  const framed = window.self !== window.top;
  let csrf = "", preview = null, overview = null, poll = null, sessionTimer = null, busy = false;
  let requestId = null;
  let epoch = 0, actionVersion = 0, pendingLogin = null, loginPollBusy = false;
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
    csrf = ""; preview = null; overview = null; requestId = null; busy = false; actionVersion += 1;
    if (!keepLogin) {
      pendingLogin = null; $("login-challenge").hidden = true;
      $("login-code").textContent = ""; $("telegram-login-link").removeAttribute("href");
    }
    clearTimeout(sessionTimer);
    $("console").hidden = true; $("login").hidden = false;
    $("refresh").hidden = true; $("logout").hidden = true;
    $("action-preview").hidden = true; $("action-result").hidden = true;
    for (const id of ["members", "invites", "jobs", "deliveries", "audit", "result-messages", "action-fields",
                      "action-kind", "action-target", "preview-details", "preview-warnings", "summary-line",
                      "privacy-note", "limits", "updated", "session-expiry", "preview-recipient", "preview-title"]) {
      $(id).replaceChildren();
    }
    $("invite-url").value = "";
    $("start-login").disabled = false; $("preview-action").disabled = false;
  }
  function showError(error) {
    if (error instanceof StaleRequest) return;
    if (error.status === 403) clearPrivate();
    message(error.message, true);
  }
  async function api(path, body, method = "POST", csrfOverride) {
    const requestEpoch = epoch, controller = new AbortController();
    controllers.add(controller);
    const options = {method, cache: "no-store", credentials: "same-origin", headers: {}, signal: controller.signal};
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
    $("login").hidden = true; $("refresh").hidden = false; $("logout").hidden = false;
    if (poll) { clearInterval(poll); poll = null; }
    clearTimeout(sessionTimer);
    sessionTimer = setTimeout(() => {
      clearPrivate(); message("Your admin session expired. Sign in again.");
    }, Math.max(0, new Date(session.expires_at).getTime() - Date.now()));
    $("session-expiry").textContent = `Owner session expires ${date(session.expires_at)} IST.`;
  }
  async function signIn() {
    try {
      let session;
      try { session = await api("/admin/session", null, "GET"); }
      catch (error) {
        if (error instanceof StaleRequest || error.status !== 403) throw error;
        if (!telegram || !telegram.initData) {
          clearPrivate(); message("Owner sign-in is required."); return;
        }
        session = await api("/admin/session", {init_data: telegram.initData});
      }
      establish(session); await refresh();
    } catch (error) {
      if (!(error instanceof StaleRequest)) { clearPrivate(); message(error.message, true); }
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
    for (const id of ["members", "invites", "jobs", "deliveries", "audit"]) $(id).replaceChildren();
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
      controls.append(group);
      row.append(name, state, progress, node("td", date(member.last_interaction)), controls);
      $("members").append(row);
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
    $("updated").textContent = `Updated ${date(data.generated_at)} IST`;
    $("console").hidden = false;
  }
  async function refresh() {
    if (!csrf || busy) return;
    const requestEpoch = epoch;
    $("refresh").disabled = true;
    try { render(await api("/admin/data", {})); message(""); }
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
  $("action-target").addEventListener("change", invalidatePreview);
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
  $("logout").addEventListener("click", async () => {
    const previousCsrf = csrf;
    clearPrivate();
    try { await api("/admin/logout", {}, "POST", previousCsrf); message("Signed out."); }
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
    else if (!framed) signIn();
  });
  if (framed) {
    clearPrivate();
    $("start-login").hidden = true;
    $("open-browser").hidden = false;
    $("open-browser").href = new URL("/admin", location.href).href;
    message("Open administration in your browser. Embedded Telegram Web frames can block secure session cookies.");
  } else signIn();
})();
