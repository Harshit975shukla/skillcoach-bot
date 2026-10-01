(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const {renderBlocks, prose, lessonSection, walkthrough} = window.SkillCoachLesson;
  const node = (tag, value, cls) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (cls) element.className = cls;
    return element;
  };
  const FAST_POLL = 3000, SLOW_POLL = 15000, FAST_WINDOW = 45000;
  let csrf = "", lastId = null, firstId = null, epoch = 0, sending = false, working = false;
  let fastUntil = 0, pollTimer = null, resendTimer = null, pendingEmail = "", feedScroll = 0, loadingFeed = false;
  // A web invitation token lives only in memory: it is read from the address fragment, which is
  // removed at once, and is sent only in the body of the join request.
  let invite = "", joinDetails = null, joinTimer = null;
  // A dashboard action arrives as /web#start=<payload>. It is removed from the address at once and
  // offered as one tap after sign-in; it is never sent by itself.
  let pendingStart = "";
  const controllers = new Set();

  function notice(text, error = false) {
    $("notice").textContent = text;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = !text;
  }
  async function call(path, body, {method = "POST"} = {}) {
    const controller = new AbortController();
    controllers.add(controller);
    const headers = {"Content-Type": "application/json"};
    if (csrf) headers["X-CSRF-Token"] = csrf;
    try {
      const response = await fetch(path, {
        method, headers, credentials: "same-origin", cache: "no-store", signal: controller.signal,
        body: method === "GET" ? undefined : JSON.stringify(body || {}),
      });
      let data = {};
      try { data = await response.json(); } catch { data = {}; }
      return {status: response.status, ok: response.ok, data};
    } finally { controllers.delete(controller); }
  }
  function show(view) {
    for (const id of ["signin", "join", "chat", "reader"]) $(id).hidden = id !== view;
    $("logout").hidden = !["chat", "reader"].includes(view);
    $("dashboard-link").hidden = $("logout").hidden;
  }
  function reset() {
    epoch += 1;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    clearTimeout(pollTimer); clearInterval(resendTimer); clearInterval(joinTimer);
    csrf = ""; lastId = null; firstId = null; sending = false; working = false; fastUntil = 0; loadingFeed = false;
    $("feed").replaceChildren(); $("lesson-body").replaceChildren();
    $("lesson-title").textContent = ""; $("lesson-meta").textContent = "";
    $("message").value = ""; $("older").hidden = true; $("working").hidden = true;
    $("start-prompt").hidden = true;
    updateControls();
  }

  // Sign-in ----------------------------------------------------------------------------------
  function signInView(message = "", error = false) {
    reset();
    show("signin");
    $("email-form").hidden = false; $("code-form").hidden = true;
    $("signin-error").textContent = error ? message : "";
    notice(error ? "" : message);
    $("email").focus();
  }
  function signinError(text) { $("signin-error").textContent = text; }
  function codeStep(data) {
    $("email-form").hidden = true; $("code-form").hidden = false;
    $("code-sent").textContent = `If ${pendingEmail} is registered with SkillCoach, a six-digit code is on its way. ` +
      "Check spam if it has not arrived in a minute.";
    signinError(""); $("code").value = ""; $("code").focus();
    const resendAt = new Date(data.resend_at).getTime();
    const tick = () => {
      const seconds = Math.ceil((resendAt - Date.now()) / 1000);
      $("code-resend").disabled = seconds > 0;
      $("code-resend").textContent = seconds > 0 ? `Send a new code (${seconds}s)` : "Send a new code";
      if (seconds <= 0) clearInterval(resendTimer);
    };
    clearInterval(resendTimer); resendTimer = setInterval(tick, 1000); tick();
  }
  async function requestCode(button) {
    const email = pendingEmail;
    if (!email) { signinError("Enter your email address."); return; }
    button.disabled = true; signinError("");
    let sent = false;
    try {
      const result = await call("/web/login/start", {email});
      if (result.status === 404) { disabled(); return; }
      if (!result.ok) { signinError(result.data.error || "A code could not be sent. Try again."); return; }
      sent = true;
      codeStep(result.data);
    } catch { signinError("SkillCoach could not be reached. Check your connection and try again."); }
    // After a new code, the countdown owns the resend button; after a failure it is usable again.
    finally { if (button.id === "email-submit" || !sent) button.disabled = false; }
  }
  $("email-form").addEventListener("submit", event => {
    event.preventDefault();
    const email = $("email").value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { signinError("Enter a valid email address."); $("email").focus(); return; }
    pendingEmail = email;
    requestCode($("email-submit"));
  });
  $("code-resend").addEventListener("click", () => requestCode($("code-resend")));
  $("code-back").addEventListener("click", () => {
    clearInterval(resendTimer);
    $("code-form").hidden = true; $("email-form").hidden = false; signinError(""); $("email").focus();
  });
  $("code-form").addEventListener("submit", async event => {
    event.preventDefault();
    const code = $("code").value.trim();
    if (!/^[0-9]{6}$/.test(code)) { signinError("Enter the six digits from your email."); $("code").focus(); return; }
    $("code-submit").disabled = true; signinError("");
    try {
      const result = await call("/web/login/verify", {code});
      if (result.status === 404) { disabled(); return; }
      if (!result.ok) {
        signinError(result.data.error || "That code did not work. Try again.");
        $("code").value = ""; $("code").focus();
        return;
      }
      clearInterval(resendTimer);
      startChat(result.data);
    } catch { signinError("SkillCoach could not be reached. Check your connection and try again."); }
    finally { $("code-submit").disabled = false; }
  });

  // Joining by invitation ----------------------------------------------------------------------
  function joinError(text) { $("join-error").textContent = text; }
  function joinView(message = "") {
    reset();
    show("join"); notice("");
    $("join-form").hidden = false; $("join-code-form").hidden = true; $("join-done").hidden = true;
    joinError(message);
    $("join-name").focus();
  }
  function joinCodeStep(data) {
    $("join-form").hidden = true; $("join-code-form").hidden = false;
    $("join-code-sent").textContent = `We sent a six-digit code to ${joinDetails.email}. ` +
      "Check spam if it has not arrived in a minute.";
    joinError(""); $("join-code").value = ""; $("join-code").focus();
    const resendAt = new Date(data.resend_at).getTime();
    const tick = () => {
      const seconds = Math.ceil((resendAt - Date.now()) / 1000);
      $("join-resend").disabled = seconds > 0;
      $("join-resend").textContent = seconds > 0 ? `Send a new code (${seconds}s)` : "Send a new code";
      if (seconds <= 0) clearInterval(joinTimer);
    };
    clearInterval(joinTimer); joinTimer = setInterval(tick, 1000); tick();
  }
  async function requestJoinCode(button) {
    button.disabled = true; joinError("");
    let sent = false;
    try {
      const result = await call("/web/join/start", {invite, name: joinDetails.name, email: joinDetails.email});
      if (result.status === 404) { disabled(); return; }
      if (!result.ok) { joinError(result.data.error || "A code could not be sent. Try again."); return; }
      sent = true;
      joinCodeStep(result.data);
    } catch { joinError("SkillCoach could not be reached. Check your connection and try again."); }
    finally { if (button.id === "join-submit" || !sent) button.disabled = false; }
  }
  $("join-form").addEventListener("submit", event => {
    event.preventDefault();
    const name = $("join-name").value.trim(), email = $("join-email").value.trim();
    if (!name || name.length > 60) { joinError("Enter your name, up to 60 characters."); $("join-name").focus(); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { joinError("Enter a valid email address."); $("join-email").focus(); return; }
    joinDetails = {name, email};
    requestJoinCode($("join-submit"));
  });
  $("join-resend").addEventListener("click", () => requestJoinCode($("join-resend")));
  $("join-back").addEventListener("click", () => {
    clearInterval(joinTimer);
    $("join-code-form").hidden = true; $("join-form").hidden = false; joinError(""); $("join-email").focus();
  });
  $("join-code-form").addEventListener("submit", async event => {
    event.preventDefault();
    const code = $("join-code").value.trim();
    if (!/^[0-9]{6}$/.test(code)) { joinError("Enter the six digits from your email."); $("join-code").focus(); return; }
    $("join-code-submit").disabled = true; joinError("");
    try {
      const result = await call("/web/join/verify", {code});
      if (result.status === 404) { disabled(); return; }
      if (!result.ok) {
        joinError(result.data.error || "That code did not work. Try again.");
        $("join-code").value = ""; $("join-code").focus();
        return;
      }
      clearInterval(joinTimer);
      invite = "";
      $("join-code-form").hidden = true; $("join-done").hidden = false;
      $("join-done-text").textContent = "Your coach will review your request. When you are approved you get an " +
        `email at ${joinDetails.email}; then sign in on this page with that address.`;
      $("join-done").querySelector("h2").focus();
    } catch { joinError("SkillCoach could not be reached. Check your connection and try again."); }
    finally { $("join-code-submit").disabled = false; }
  });
  $("join-signin").addEventListener("click", () => {
    const email = joinDetails ? joinDetails.email : "";
    joinDetails = null;
    signInView();
    $("email").value = email;
  });

  // Conversation -----------------------------------------------------------------------------
  function startChat(session) {
    reset();
    csrf = session.csrf;
    show("chat"); notice("");
    offerStart();
    loadFeed(true);
  }
  function takeStart() {
    // Strip the fragment before anything else; keep only a well-formed payload, in memory.
    const match = /^#start=([A-Za-z0-9_-]{1,64})$/.exec(location.hash);
    history.replaceState(null, "", location.pathname);
    if (match) pendingStart = match[1];
  }
  function offerStart() {
    if (!pendingStart || !csrf) return;
    const p = pendingStart;
    $("start-text").textContent = p.startsWith("quiz_") ? "Open the quiz you picked on your dashboard."
      : p === "review" ? "Start the review you picked on your dashboard."
      : p === "resume" ? "Continue your assessment where you left off."
      : p.startsWith("cert_") ? "Open the certification practice you picked."
      : p.startsWith("capstone_") ? "Open the capstone you picked."
      : p === "plan" ? "Review, change or approve your weekly plan."
      : p === "onboard" ? "Start your guided setup."
      : "Continue from your dashboard.";
    $("start-prompt").hidden = false;
  }
  $("start-go").addEventListener("click", () => {
    if (!pendingStart || sending || !csrf) return;
    const command = "/start " + pendingStart;
    pendingStart = ""; $("start-prompt").hidden = true;
    send({text: command}, command);
  });
  $("start-dismiss").addEventListener("click", () => { pendingStart = ""; $("start-prompt").hidden = true; });
  function sessionEnded(message) {
    signInView(message || "Your session ended. Sign in again with your email.");
  }
  function disabled() {
    reset(); show(null);
    notice("The web version of SkillCoach is not switched on. Use the SkillCoach bot in Telegram.");
  }
  function when(value) {
    if (!value) return "";
    return new Date(value).toLocaleString(undefined, {weekday: "short", day: "numeric", month: "short",
                                                      hour: "2-digit", minute: "2-digit"});
  }
  function linkified(text) {
    const paragraph = node("p", undefined, "text");
    const pattern = /https:\/\/[^\s<>"'()\]]+/g;
    let last = 0, match;
    while ((match = pattern.exec(text))) {
      const url = match[0].replace(/[.,;:!?]+$/, "");
      paragraph.append(document.createTextNode(text.slice(last, match.index)));
      const link = node("a", url);
      link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer";
      paragraph.append(link);
      last = match.index + url.length; pattern.lastIndex = last;
    }
    paragraph.append(document.createTextNode(text.slice(last)));
    return paragraph;
  }
  function actionButton(item, button) {
    if (button.kind === "link") {
      const safe = /^https:\/\/[A-Za-z0-9.-]+(?:[/?#]|$)/.test(button.url) || button.url === "/admin";
      if (!safe) return null;
      const link = node("a", button.text);
      link.href = button.url;
      if (button.url !== "/admin") { link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer"; }
      return link;
    }
    const element = node("button", button.text);
    element.type = "button";
    element.addEventListener("click", () => {
      if (button.kind === "lesson") openLesson({lesson: button.lesson});
      else if (button.kind === "topic") openLesson({topic: button.topic});
      else if (button.kind === "command") send({text: button.command}, button.command);
      else if (button.kind === "callback") {
        // The coach checks each tap against the current question, so a stale button cannot grade another.
        send({callback: button.data}, button.text, item);
      }
    });
    return element;
  }
  function renderMessage(message, arrived) {
    const item = node("li", undefined, "message" + (arrived ? " arrived" : ""));
    item.dataset.id = message.id;
    if (message.blocks) item.append(prose(message.blocks));
    else item.append(linkified(message.text || ""));
    for (const row of message.buttons || []) {
      const actions = node("div", undefined, "actions");
      for (const button of row) {
        const element = actionButton(item, button);
        if (element) actions.append(element);
      }
      if (actions.children.length) item.append(actions);
    }
    if (message.at) {
      const time = node("time", when(message.at));
      time.dateTime = message.at; item.append(time);
    }
    return item;
  }
  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
  }
  function toBottom() { window.scrollTo({top: document.documentElement.scrollHeight, behavior: "auto"}); }
  function showEmpty() {
    if ($("feed").querySelector(".message")) return;
    $("feed").append(node("li", "No messages yet. Tap Today to see your lesson, quiz and exercises, or ask your coach a question.", "empty"));
  }
  async function loadFeed(initial = false) {
    if (loadingFeed && !initial) return;
    loadingFeed = true;
    const requestEpoch = epoch;
    try {
      const result = await call("/web/feed", initial || lastId === null ? {} : {after: lastId});
      if (requestEpoch !== epoch) return;
      if (result.status === 403) { sessionEnded(result.data.error); return; }
      if (result.status === 404) { disabled(); return; }
      if (!result.ok) { notice(result.data.error || "New messages could not be loaded. Retrying shortly.", true); return; }
      notice("");
      const stay = initial || nearBottom();
      const messages = result.data.messages || [];
      if (messages.length) {
        const empty = $("feed").querySelector(".empty");
        if (empty) empty.remove();
        $("feed").setAttribute("aria-busy", "true");
        for (const message of messages) $("feed").append(renderMessage(message, !initial));
        $("feed").removeAttribute("aria-busy");
        lastId = messages[messages.length - 1].id;
        if (firstId === null) firstId = messages[0].id;
      }
      if (initial) { $("older").hidden = !result.data.older; showEmpty(); }
      working = Boolean(result.data.working);
      $("working").hidden = !working;
      if (stay) toBottom();
    } catch (error) {
      if (requestEpoch === epoch && error.name !== "AbortError") notice("You are offline or SkillCoach is unreachable. Retrying shortly.", true);
    } finally {
      if (requestEpoch === epoch) { loadingFeed = false; schedulePoll(); }
    }
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!csrf) return;
    const fast = working || Date.now() < fastUntil;
    pollTimer = setTimeout(() => { if (!document.hidden && !$("chat").hidden) loadFeed(); else schedulePoll(); },
                           fast ? FAST_POLL : SLOW_POLL);
  }
  $("older").addEventListener("click", async () => {
    if (firstId === null) return;
    const requestEpoch = epoch, button = $("older");
    button.disabled = true;
    try {
      const result = await call("/web/feed", {before: firstId});
      if (requestEpoch !== epoch) return;
      if (result.status === 403) { sessionEnded(result.data.error); return; }
      if (!result.ok) { notice(result.data.error || "Earlier messages could not be loaded.", true); return; }
      const messages = result.data.messages || [];
      const height = document.documentElement.scrollHeight;
      const fragment = document.createDocumentFragment();
      for (const message of messages) fragment.append(renderMessage(message, false));
      $("feed").prepend(fragment);
      if (messages.length) firstId = messages[0].id;
      button.hidden = !result.data.older;
      window.scrollBy(0, document.documentElement.scrollHeight - height);
    } catch { notice("Earlier messages could not be loaded.", true); }
    finally { button.disabled = false; }
  });

  // Sending ----------------------------------------------------------------------------------
  function updateControls() {
    $("send").disabled = sending;
    for (const button of document.querySelectorAll(".quick button")) button.disabled = sending;
  }
  function echo(text) {
    const item = node("li", undefined, "message mine pending");
    item.append(node("p", text, "text"), node("p", "Sending…", "state"));
    const empty = $("feed").querySelector(".empty");
    if (empty) empty.remove();
    $("feed").append(item); toBottom();
    return item;
  }
  async function send(payload, label, source) {
    if (sending || !csrf) return;
    sending = true; updateControls();
    const requestEpoch = epoch;
    const requestId = crypto.randomUUID();
    const mine = echo(label);
    if (source) for (const button of source.querySelectorAll(".actions button")) button.disabled = true;
    const attempt = async () => {
      mine.classList.remove("failed"); mine.classList.add("pending");
      mine.querySelector(".state").textContent = "Sending…";
      const retry = mine.querySelector(".retry");
      if (retry) retry.remove();
      try {
        // Retrying reuses the request ID, so the coach processes this message at most once.
        const result = await call("/web/send", {request_id: requestId, ...payload});
        if (requestEpoch !== epoch) return;
        if (result.status === 403) { sessionEnded(result.data.error); return; }
        if (result.status === 404) { disabled(); return; }
        if (!result.ok) throw new Error(result.data.error || "Not sent.");
        mine.classList.remove("pending");
        mine.querySelector(".state").textContent = "Sent";
        fastUntil = Date.now() + FAST_WINDOW;
        await loadFeed();
      } catch (error) {
        if (requestEpoch !== epoch || error.name === "AbortError") return;
        mine.classList.remove("pending"); mine.classList.add("failed");
        mine.querySelector(".state").textContent = error.message && error.message !== "Failed to fetch"
          ? error.message : "Not sent. Check your connection.";
        const again = node("button", "Try again", "retry");
        again.type = "button";
        again.addEventListener("click", async () => {
          if (sending) return;
          sending = true; updateControls();
          try { await attempt(); } finally { if (requestEpoch === epoch) { sending = false; updateControls(); } }
        });
        mine.append(again);
        // Keep the retry clear of the docked composer: at the end of the page the composer sits below the feed.
        if (mine === $("feed").lastElementChild) toBottom();
        else mine.scrollIntoView({block: "nearest"});
      }
    };
    try { await attempt(); }
    finally {
      if (requestEpoch === epoch) {
        sending = false; updateControls();
        if (source) for (const button of source.querySelectorAll(".actions button")) button.disabled = false;
      }
    }
  }
  $("composer").addEventListener("submit", event => {
    event.preventDefault();
    const text = $("message").value.trim();
    if (!text || sending) return;
    $("message").value = ""; grow();
    send({text}, text);
  });
  function grow() {
    const box = $("message");
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight + 2, window.innerHeight * 0.4) + "px";
  }
  $("message").addEventListener("input", grow);
  $("message").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  for (const button of document.querySelectorAll(".quick button")) {
    button.addEventListener("click", () => send({text: button.dataset.command}, button.dataset.command));
  }

  // Lesson reader ----------------------------------------------------------------------------
  const day = value => value ? new Date(value + "T00:00:00").toLocaleDateString(undefined,
    {weekday: "short", day: "numeric", month: "short", year: "numeric"}) : "";
  function references(urls) {
    const safe = (urls || []).filter(url => /^https:\/\/[A-Za-z0-9.-]+\//.test(url));
    if (!safe.length) return null;
    const element = lessonSection("Official references"), list = node("ul", undefined, "lesson-refs");
    for (const url of safe) {
      const item = node("li"), link = node("a", url.replace(/^https:\/\//, ""));
      link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer";
      item.append(link); list.append(item);
    }
    element.append(list);
    return element;
  }
  function renderLesson(lesson) {
    $("lesson-title").textContent = lesson.title;
    $("lesson-meta").textContent = [day(lesson.date), lesson.library ? "Course version " + lesson.version : "", lesson.review]
      .filter(Boolean).join(" · ");
    const body = $("lesson-body");
    body.replaceChildren();
    if (lesson.library) {
      body.append(node("p", "Browsing the library does not change your plan or progress. For tracked practice, send " +
        (lesson.learn_command || "/learn") + " in your conversation.", "guidance"));
    }
    if (lesson.available === false) {
      body.append(node("p", "The full text of this older lesson was not kept. Its tracked exercises are below.", "guidance"));
    }
    for (const section of lesson.sections || []) {
      const element = lessonSection(section.heading); element.append(prose(section.blocks)); body.append(element);
    }
    if (lesson.walkthrough) body.append(walkthrough(lesson.walkthrough));
    if ((lesson.exercises || []).length) {
      const element = lessonSection("Today's exercises"), list = node("ol", undefined, "task-list");
      element.append(node("p", "Mark each one with its buttons in your conversation, or send its command.", "section-description"));
      for (const exercise of lesson.exercises) {
        const status = exercise.status === "done" ? "Done" : exercise.status === "skipped" ? "Skipped" : "Open";
        const item = node("li");
        item.append(node("span", exercise.title, "task-title"),
                    node("p", `About ${exercise.minutes} min · ${status}`, "task-meta"), prose(exercise.blocks));
        if (exercise.status === "pending") {
          const command = node("span", undefined, "task-command");
          command.append(node("code", `/complete ${exercise.id}`)); item.append(command);
        }
        list.append(item);
      }
      element.append(list); body.append(element);
    }
    for (const extra of lesson.extension || []) {
      const element = lessonSection(extra.title);
      element.append(node("p", `Optional · about ${extra.minutes} min · not tracked`, "section-description"), prose(extra.blocks));
      body.append(element);
    }
    for (const note of lesson.notes || []) {
      const element = lessonSection(note.heading); element.append(prose(note.blocks)); body.append(element);
    }
    if (lesson.interview) {
      const element = lessonSection("Interview practice");
      element.append(prose(lesson.interview.question));
      if ((lesson.interview.points || []).length) {
        const details = node("details"), list = node("ul", undefined, "prose checklist");
        details.append(node("summary", "Show the answer checklist"));
        for (const point of lesson.interview.points) list.append(renderBlocks(node("li"), point));
        details.append(list); element.append(details);
      }
      element.append(node("p", "Answer out loud first. For a graded round, send /interview in your conversation.", "section-description"));
      body.append(element);
    }
    const refs = references(lesson.references);
    if (refs) body.append(refs);
  }
  async function openLesson(query) {
    const requestEpoch = epoch;
    feedScroll = window.scrollY;
    show("reader");
    $("lesson-title").textContent = "Opening the lesson…"; $("lesson-meta").textContent = "";
    $("lesson-body").replaceChildren();
    $("lesson-title").focus({preventScroll: true}); window.scrollTo(0, 0);
    try {
      const result = await call("/web/lesson", query);
      if (requestEpoch !== epoch) return;
      if (result.status === 403) { sessionEnded(result.data.error); return; }
      if (!result.ok) {
        $("lesson-title").textContent = "This lesson could not be opened";
        $("lesson-body").append(node("p", result.data.error || "Try again from your conversation.", "guidance"));
        return;
      }
      renderLesson(result.data.lesson);
    } catch {
      if (requestEpoch === epoch) {
        $("lesson-title").textContent = "This lesson could not be opened";
        $("lesson-body").append(node("p", "Check your connection, then try again.", "guidance"));
      }
    }
  }
  $("reader-back").addEventListener("click", () => {
    show("chat");
    $("lesson-body").replaceChildren();
    window.scrollTo(0, feedScroll);
    $("message").focus({preventScroll: true});
  });

  // Session ----------------------------------------------------------------------------------
  $("logout").addEventListener("click", async () => {
    reset();
    pendingStart = "";
    try { await call("/web/logout", {}); }
    catch { /* The page is already cleared; an unreachable server keeps the cookie until it expires. */ }
    signInView("Signed out.");
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && csrf && !$("chat").hidden) loadFeed();
  });
  async function boot() {
    const requestEpoch = epoch;
    const fragment = location.hash;
    if (fragment.startsWith("#invite=")) {
      // Remove the token from the address bar and history before anything else happens.
      history.replaceState(null, "", location.pathname);
      const match = /^#invite=([A-Za-z0-9_-]{32})$/.exec(fragment);
      invite = match ? match[1] : "";
      joinView(match ? "" : "This invitation link is incomplete. Ask your coach to send it again.");
      if (!match) $("join-submit").disabled = true;
      return;
    }
    if (fragment.startsWith("#start=")) takeStart();
    try {
      const result = await call("/web/session", null, {method: "GET"});
      if (requestEpoch !== epoch) return;
      if (result.status === 404) { disabled(); return; }
      if (result.status === 403) { signInView(); return; }
      if (!result.ok) { notice(result.data.error || "SkillCoach is temporarily unavailable. Reload shortly.", true); return; }
      startChat(result.data);
    } catch {
      notice("SkillCoach could not be reached. Check your connection and reload.", true);
    }
  }
  // An invitation or dashboard action opened in a tab already on this page only changes the fragment.
  window.addEventListener("hashchange", () => {
    if (location.hash.startsWith("#invite=")) boot();
    else if (location.hash.startsWith("#start=")) { takeStart(); offerStart(); }
  });
  boot();
})();
