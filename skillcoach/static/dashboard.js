(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const app = window.Telegram && window.Telegram.WebApp;
  // Served at /web/dashboard in web + email mode, without Telegram's script: the page then uses the
  // /web session (cookie and CSRF token) and actions open the web conversation instead of the bot.
  const WEB = location.pathname === "/web/dashboard";
  const WHERE = WEB ? "in your conversation" : "in Telegram";
  const IN_BOT = WEB ? "in your conversation" : "in the bot";
  const REOPEN = WEB ? "Open it again from SkillCoach on the web." : "Reopen /dashboard from the bot.";
  if (WEB) {
    $("notice").textContent = "Checking your sign-in…";
    $("chat-link").hidden = false;
    for (const element of document.querySelectorAll("[data-where]")) element.textContent = WHERE;
  }
  let webCsrf = "";
  let expiryTimer, warningTimer;
  let controller;
  let authenticated = false;
  let epoch = 0;
  let documentCsrf = "", uploadId = null, uploadPreview = null, uploadBusy = false, uploadController;
  let labBusy = false, labController, labRequests = {};
  let exerciseBusy = false, exerciseController;
  let resourceCatalog = [], resourceLimit = 6;
  let courseModules = [], courseLimit = 10, lastLessonButton = null, mastery = null;
  const LESSON = /^[0-9a-f]{20}$/;
  const TOPIC = /^[a-z0-9-]+\/[a-z0-9-]+$/;
  const linked = new URLSearchParams(location.search).get("lesson");
  const linkedTopic = new URLSearchParams(location.search).get("topic");
  let wantedLesson = linkedTopic && TOPIC.test(linkedTopic) ? "course:" + linkedTopic
    : linked && LESSON.test(linked) ? linked : null, shownLesson = null, lessonController;
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (className) element.className = className;
    return element;
  };
  function cancelPrivateWork() {
    // Invalidate in-flight private requests so a late reply can never land; reading content stays.
    epoch += 1;
    for (const pending of [controller, uploadController, labController, exerciseController, lessonController]) {
      if (pending) pending.abort();
    }
    uploadId = null; uploadPreview = null; uploadBusy = false;
    labBusy = false; labRequests = {}; exerciseBusy = false;
    $("document-file").value = ""; $("document-preview").hidden = true;
    for (const id of ["document-file", "document-kind", "document-confirm", "document-cancel", "document-choice"]) $(id).disabled = false;
    $("document-status").textContent = ""; $("document-preview-summary").textContent = "";
    for (const id of ["lab-status", "task-status"]) $(id).textContent = "";
    for (const input of document.querySelectorAll(".lab-input")) input.value = "";
    setLabControls(false); setExerciseControls(false);
  }
  function clearPrivate(message, error = false) {
    cancelPrivateWork();
    hideLesson();
    documentCsrf = ""; webCsrf = "";
    resourceCatalog = []; resourceLimit = 6;
    courseModules = []; courseLimit = 10; lastLessonButton = null; mastery = null;
    $("roadmap").hidden = true; $("roadmap-open").hidden = true;
    $("course-search").value = ""; $("course-module").replaceChildren(node("option", "All modules"));
    $("course-module").firstChild.value = ""; $("course-more").hidden = true;
    $("resource-search").value = ""; $("resource-group").value = ""; $("resource-no-account").checked = false;
    $("resource-more").hidden = true;
    authenticated = false;
    $("content").hidden = true;
    for (const id of ["learner-name", "target-role", "tasks", "earlier-list", "plan-days", "skills", "interviews",
                      "done", "streak", "minutes", "graded", "study-days", "accuracy", "understood", "labs-verified",
                      "reviews", "roadmap-summary", "roadmap-next", "cert-title", "cert-format", "cert-overall",
                      "cert-domains", "cert-labs", "cert-tracks", "cert-disclaimer", "capstone-list", "portfolio-status",
                      "preferences", "updated", "task-count", "quiz-list", "quiz-count",
                      "today-next", "today-actions", "today-status",
                      "plan-status", "plan-rationale", "lab-items", "lab-catalog", "lab-count", "lab-status",
                      "lab-cost", "lab-gate", "lesson-list", "resource-list", "resource-count",
                      "resource-notice", "resource-rights", "course-list", "course-count", "course-notice"]) {
      $(id).replaceChildren();
    }
    $("lab-gate").hidden = true; $("today-card").hidden = true; $("earlier-tasks").hidden = true;
    $("cert-selected").hidden = true; $("cert-guide").removeAttribute("href");
    $("plan-bot-link").hidden = true; $("plan-bot-link").removeAttribute("href");
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = false;
    clearTimeout(expiryTimer); clearTimeout(warningTimer);
  }
  function empty(id, message) { $(id).append(node("li", message, "empty")); }
  const QUIZ_START = /^(?:quiz_(?:[a-f0-9]{20}|\d{4}-\d{2}-\d{2})|review|resume|cert_[a-z-]{2,20}(?:_\d{1,2})?|capstone_[a-z0-9-]{2,30})$/;
  function telegramLink(botUrl, start, label) {
    if (!QUIZ_START.test(start || "")) return null;
    if (WEB) {
      const link = node("a", label.replace(/ in Telegram$/, " " + WHERE), "quiz-link");
      link.href = "/web#start=" + start;
      return link;
    }
    if (!botUrl || !/^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(botUrl)) return null;
    const link = node("a", label, "quiz-link");
    link.href = botUrl + "?start=" + start;
    link.rel = "noopener noreferrer";
    link.addEventListener("click", event => {
      if (app && app.openTelegramLink) { event.preventDefault(); app.openTelegramLink(link.href); }
    });
    return link;
  }
  function renderToday(today, progress, botUrl) {
    const actions = $("today-actions"), status = $("today-status");
    actions.replaceChildren(); status.replaceChildren();
    if (!today || !today.next) { $("today-card").hidden = true; return; }
    const next = today.next;
    $("today-next").textContent = next.text;
    if (next.lesson && LESSON.test(next.lesson)) {
      const read = node("button", "Read today's lesson");
      read.type = "button";
      read.addEventListener("click", () => { lastLessonButton = read; openLesson(next.lesson); });
      actions.append(read);
    }
    const labels = {quiz: "Take the quiz in Telegram", review: "Start the review in Telegram", resume: "Continue in Telegram"};
    const link = telegramLink(botUrl, next.start, labels[next.kind] || "Catch up in Telegram");
    if (link) actions.append(link);
    else if (next.kind === "exercise") {
      const jump = node("a", "Go to your exercises", "quiz-link");
      jump.href = "#tasks-heading";
      actions.append(jump);
    }
    const lesson = today.lesson, quiz = today.quiz, exercises = today.exercises || [];
    if (lesson) {
      status.append(node("li", `Lesson: ${lesson.topic}${lesson.today ? "" : " · " + day(lesson.date)}`
        + (lesson.understood ? " · understood" : lesson.delivered ? "" : " · still arriving")));
    }
    if (quiz) {
      status.append(node("li", quiz.status === "completed" ? `Quiz: done · ${quiz.score}/${quiz.total} correct`
        : quiz.can_resume ? `Quiz: ${quiz.answered}/${quiz.total} answered` : "Quiz: deadline passed"));
    }
    if (exercises.length) {
      status.append(node("li", `Exercises: ${exercises.filter(e => e.status === "done").length} of ${exercises.length} done`));
    }
    if (today.review_due) status.append(node("li", `Reviews due: ${today.review_due}`));
    if (progress) {
      status.append(node("li", `Study days this week: ${progress.study_days_week} of ${progress.weekly_goal} · streak ${progress.streak}`));
    }
    $("today-card").hidden = false;
  }
  function taskItem(task) {
    const item = node("li");
    item.append(node("span", task.title, "task-title"));
    item.append(node("p", `${task.skill} · about ${task.estimated_minutes} min · assigned ${day(task.assigned_date)}`, "task-meta"));
    if (task.detail_blocks && task.detail_blocks.length) {
      const details = node("details");
      details.append(node("summary", "Exercise details"), prose(task.detail_blocks));
      item.append(details);
    } else if (task.detail) {
      const details = node("details");
      details.append(node("summary", "Exercise details"), node("p", task.detail, "task-detail"));
      item.append(details);
    }
    const actions = node("div", undefined, "task-actions");
    for (const [action, label] of [["done", "Mark done"], ["skip", "Skip"]]) {
      const button = node("button", label, "exercise-button");
      button.type = "button";
      button.setAttribute("aria-label", `${label}: ${task.title}`);
      button.addEventListener("click", () => exerciseAction(task.id, action));
      actions.append(button);
    }
    item.append(actions);
    return item;
  }
  function setExerciseControls(disabled) {
    for (const element of document.querySelectorAll(".exercise-button")) element.disabled = disabled || !documentCsrf;
  }
  async function exerciseAction(taskId, action) {
    if (exerciseBusy || uploadBusy || labBusy || !documentCsrf) return;
    const requestEpoch = epoch;
    let saved = false;
    exerciseBusy = true; setExerciseControls(true);
    $("task-status").textContent = action === "done" ? "Saving…" : "Skipping…";
    try {
      const result = await privateRequest("/app/exercise", {request_id: crypto.randomUUID(), task_id: taskId, action}, true, "exercise");
      if (!result) return;
      saved = true;
      $("task-status").textContent = action === "done" ? "Nice work. Exercise recorded as done."
        : "Skipped. It stays on the lesson page as optional practice.";
    } catch (error) {
      if (requestEpoch === epoch) $("task-status").textContent = (error.message || "Could not save.") + " Tap again to retry.";
    } finally {
      if (requestEpoch === epoch) { exerciseBusy = false; setExerciseControls(false); }
    }
    if (saved && requestEpoch === epoch) refresh();
  }
  function renderQuizzes(quizzes, botUrl) {
    const list = $("quiz-list"); list.replaceChildren();
    $("quiz-count").textContent = `${quizzes.filter(quiz => quiz.can_resume).length} available`;
    for (const quiz of quizzes) {
      const item = node("li"), detail = node("div");
      const status = quiz.status === "completed" ? `Completed · ${quiz.score}/${quiz.total} correct`
        : quiz.status === "expired" ? "Deadline passed" : `${quiz.answered}/${quiz.total} answered`;
      detail.append(node("span", quiz.title, "plan-topic"), node("p", `${day(quiz.date)} · ${status}`, "task-meta"));
      if (quiz.can_resume) {
        const closes = new Date(new Date(quiz.deadline).getTime() - 1000).toLocaleString("en-IN", {
          timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
        });
        detail.append(node("p", `Available through ${closes} IST`, "task-meta"));
      }
      item.append(detail);
      if (quiz.can_resume && /^(?:[a-f0-9]{20}|\d{4}-\d{2}-\d{2})$/.test(quiz.id)) {
        if (WEB) {
          const link = node("a", `${quiz.answered ? "Resume" : "Start"} ${WHERE}`, "quiz-link");
          link.href = "/web#start=quiz_" + quiz.id;
          item.append(link);
        } else if (botUrl && /^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(botUrl)) {
          const link = node("a", quiz.answered ? "Resume in Telegram" : "Start in Telegram", "quiz-link");
          link.href = botUrl + "?start=quiz_" + quiz.id;
          link.rel = "noopener noreferrer";
          link.addEventListener("click", event => {
            if (app && app.openTelegramLink) { event.preventDefault(); app.openTelegramLink(link.href); }
          });
          item.append(link);
        } else detail.append(node("code", `/quiz ${quiz.id}`, "task-command"));
      }
      list.append(item);
    }
    if (!quizzes.length) empty("quiz-list", "Your daily quizzes will appear here after your first delivered lesson.");
  }
  const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
  const day = value => value ? new Date(value + "T00:00:00").toLocaleDateString(undefined,
    {weekday: "short", day: "numeric", month: "short", year: "numeric"}) : "";
  const {renderBlocks, prose, lessonSection, walkthrough} = window.SkillCoachLesson;
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
  function renderCertification(view, botUrl) {
    for (const id of ["cert-domains", "cert-tracks"]) $(id).replaceChildren();
    $("cert-selected").hidden = true; $("cert-labs").textContent = ""; $("cert-disclaimer").textContent = "";
    if (!view) return;
    const track = view.track;
    if (track) {
      $("cert-title").textContent = `Your goal: ${track.name} · ${track.code}`;
      $("cert-format").textContent = track.format + (track.hands_on
        ? " Hands-on exam: practise the commands in your labs; these questions check reasoning." : "");
      $("cert-overall").textContent = track.overall === null
        ? "Practise a domain to see your exam-style accuracy."
        : `Exam-style practice accuracy: ${track.overall}% across ${track.covered_domains} practised domain${track.covered_domains === 1 ? "" : "s"}.`;
      if (/^https:\/\/[A-Za-z0-9.-]+\//.test(track.source)) {
        $("cert-guide").href = track.source;
        $("cert-guide").onclick = event => { if (app && app.openLink) { event.preventDefault(); app.openLink(track.source); } };
      }
      $("cert-selected").hidden = false;
      for (const domain of track.domains) {
        const item = node("li"), detail = node("div");
        detail.append(node("span", domain.name + (domain.weight ? ` · ${domain.weight}% of the exam` : ""), "plan-topic"),
          node("p", (domain.practice_answers ? `${domain.practice_accuracy}% of ${domain.practice_answers} practice answers`
            : "No practice yet") + ` · ${domain.topics_started} of ${domain.topics_total} related topics started`, "task-meta"),
          node("span", domain.label, "state-badge " + (domain.label === "Needs work" ? "needs_review"
            : domain.label === "Strong in practice" ? "solid" : "")));
        item.append(detail);
        const link = telegramLink(botUrl, `cert_${track.id}_${domain.index}`, "Practise in Telegram");
        if (link) item.append(link);
        $("cert-domains").append(item);
      }
      if (track.labs.length) $("cert-labs").textContent = "Hands-on labs for this exam: " + track.labs.map(lab => lab.title).join(" · ");
    }
    $("cert-tracks-heading").textContent = track ? "Other exams" : "Exams you can prepare for";
    for (const option of view.tracks.filter(item => !track || item.id !== track.id)) {
      const item = node("li"), detail = node("div");
      detail.append(node("span", option.name, "plan-topic"), node("p", option.code + (option.hands_on ? " · hands-on exam" : ""), "task-meta"));
      item.append(detail);
      const link = telegramLink(botUrl, `cert_${option.id}`, track ? "Switch in Telegram" : "Choose in Telegram");
      if (link) item.append(link);
      $("cert-tracks").append(item);
    }
    $("cert-disclaimer").textContent = `${view.disclaimer} Exam details checked ${view.verified}.`;
  }
  function renderCapstones(capstones, portfolio, botUrl) {
    $("capstone-list").replaceChildren();
    const labels = {verified: "Verified", needs_fix: "Needs a fix", started: "Started", not_started: "Not started"};
    for (const capstone of capstones || []) {
      const item = node("li"), detail = node("div");
      detail.append(node("span", capstone.title, "plan-topic"),
        node("p", `${capstone.hours} · ${labels[capstone.status] || capstone.status}`
          + (capstone.verified_at ? ` · ${day(capstone.verified_at.slice(0, 10))}` : ""), "task-meta"),
        node("p", capstone.goal, "task-detail"));
      item.append(detail);
      const link = telegramLink(botUrl, `capstone_${capstone.id}`, capstone.status === "not_started" ? "Open brief in Telegram" : "Open in Telegram");
      if (link) item.append(link);
      $("capstone-list").append(item);
    }
    $("portfolio-status").replaceChildren();
    if (portfolio && portfolio.enabled && /^\/portfolio\/[A-Za-z0-9_-]{16}$/.test(portfolio.path)) {
      const link = node("a", "your public portfolio");
      link.href = portfolio.path; link.target = "_blank"; link.rel = "noopener noreferrer";
      $("portfolio-status").append(document.createTextNode("Public portfolio is on: "), link,
        document.createTextNode(". Turn it off any time with /portfolio off."));
    } else {
      $("portfolio-status").textContent = `Public portfolio is off. Send /portfolio on ${WHERE} to share verified labs and capstones.`;
    }
  }
  function renderRoadmap(view) {
    mastery = view || null;
    if (!view) { $("roadmap").hidden = true; return; }
    const s = view.summary;
    $("roadmap-summary").textContent = `Roadmap: ${s.started} of ${s.total} topics started · ${s.solid} solid · `
      + `${s.needs_review} need${s.needs_review === 1 ? "s" : ""} review`;
    const next = view.next;
    $("roadmap-next").textContent = next ? `${next.reason}: ${next.title}` : "";
    $("roadmap-open").hidden = !(next && TOPIC.test(next.id));
    $("roadmap").hidden = false;
    renderCourses();
  }
  function renderCourses() {
    const group = $("course-module").value;
    const words = $("course-search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const topics = courseModules.flatMap(module => module.topics.map(topic => ({...topic, module})))
      .filter(topic => (!group || topic.module.id === group)
        && words.every(word => (topic.title + " " + topic.module.title).toLowerCase().includes(word)));
    const list = $("course-list"); list.replaceChildren();
    for (const topic of topics.slice(0, courseLimit)) {
      const item = node("li"), detail = node("div"), button = node("button", "Read lesson");
      detail.append(node("span", topic.title, "plan-topic"), node("p", topic.module.title, "task-meta"));
      const state = mastery && mastery.states[topic.id];
      if (state) detail.append(node("span", state.label, "state-badge " + state.state));
      button.type = "button"; button.setAttribute("aria-label", `Read ${topic.title}`);
      button.addEventListener("click", () => { lastLessonButton = button; openLesson("course:" + topic.id); });
      item.append(detail, button); list.append(item);
    }
    if (!topics.length) empty("course-list", "No matching lessons. Try another topic or choose All modules.");
    $("course-count").textContent = `Showing ${Math.min(courseLimit, topics.length)} of ${topics.length} stored lessons`;
    $("course-more").hidden = topics.length <= courseLimit;
  }
  function renderLesson(lesson) {
    $("lesson-title").textContent = lesson.title;
    $("lesson-meta").textContent = [day(lesson.date), lesson.library ? "Course version " + lesson.version : "", lesson.review].filter(Boolean).join(" · ");
    const body = $("lesson-body"), jump = $("lesson-jump");
    body.replaceChildren(); jump.replaceChildren();
    const anchor = (label, id) => { const link = node("a", label); link.href = "#" + id; jump.append(link); };
    if (lesson.library) {
      const note = node("p", undefined, "guidance");
      note.append(document.createTextNode("Browse freely; this does not change your plan, tasks or lab progress. For tracked practice and a video, send "),
                  node("code", lesson.learn_command), document.createTextNode(` ${WHERE}.`));
      body.append(note);
    }
    if (!lesson.available) {
      body.append(node("p", "The full text of this older lesson was not kept. Its tracked exercises are below.", "guidance"));
    }
    for (const section of lesson.sections || []) {
      const element = lessonSection(section.heading); element.append(prose(section.blocks)); body.append(element);
    }
    if (lesson.walkthrough) {
      anchor("Walkthrough", "lesson-walkthrough"); body.append(walkthrough(lesson.walkthrough));
    }
    if (lesson.exercises.length) {
      anchor("Exercises", "lesson-exercises");
      const element = lessonSection("Today's exercises", "lesson-exercises");
      element.append(node("p", `Tracked in your practice list. Record each one ${IN_BOT} with its command.`, "section-description"));
      const list = node("ol", undefined, "task-list");
      for (const exercise of lesson.exercises) list.append(renderExercise(exercise));
      element.append(list); body.append(element);
    }
    if (lesson.extension && lesson.extension.length) {
      const element = lessonSection(lesson.library ? "Practice on your own" : "Optional extension practice");
      element.append(node("p", lesson.library ? `Untracked exercises. Use /learn ${IN_BOT} to assign practice.`
        : "Outside today's time target and not tracked.", "section-description"));
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
      element.append(node("p", `Answer out loud in about two minutes first. For a graded round, send /interview ${IN_BOT}.`, "section-description"));
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
      ? `You rated this lesson “${ratings[lesson.feedback]}”. You can change it with the buttons at the end of the lesson ${WHERE}.`
      : `Rate this lesson with the buttons at the end of the lesson ${WHERE}. Only the button you pick is stored.`;
    $("lesson-feedback").hidden = !lesson.available || lesson.library;
    $("lesson-status").hidden = true;
    $("lesson-page").hidden = false;
  }
  // How private requests prove who is asking: Telegram launch data, or in web mode the /web session
  // cookie plus its CSRF token. Never a learner ID.
  function identity(body) {
    if (WEB) {
      return {credentials: "same-origin", body: JSON.stringify(body),
              headers: {"Content-Type": "application/json", "X-CSRF-Token": webCsrf}};
    }
    return {credentials: "omit", body: JSON.stringify({init_data: app.initData, ...body}),
            headers: {"Content-Type": "application/json"}};
  }
  async function openLesson(id) {
    const isCourse = id.startsWith("course:"), topic = isCourse ? id.slice(7) : null;
    if (!authenticated || !(WEB ? webCsrf : app && app.initData) || (isCourse ? !TOPIC.test(topic) : !LESSON.test(id))) return;
    wantedLesson = id; shownLesson = null;
    if (lessonController) lessonController.abort();
    const token = lessonController = new AbortController(), requestEpoch = epoch;
    $("content").hidden = true; $("lesson-view").hidden = false;
    lessonStatus("Opening your lesson…");
    if (app && app.BackButton) app.BackButton.show();
    window.scrollTo(0, 0);
    try {
      const response = await fetch(isCourse ? "/app/course" : "/app/lesson", {
        method: "POST", cache: "no-store", signal: token.signal,
        ...identity(isCourse ? {topic} : {lesson: id}),
      });
      const data = await response.json();
      if (requestEpoch !== epoch || token.signal.aborted) return;
      if (response.status === 403) { clearPrivate(data.error || `Session expired. ${REOPEN}`, true); return; }
      shownLesson = id;
      if (!response.ok) { lessonStatus(data.error || "This lesson could not be opened.", true); return; }
      renderLesson(data.lesson);
      $("lesson-title").tabIndex = -1; $("lesson-title").focus({preventScroll: true});
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
    if (lastLessonButton && lastLessonButton.isConnected) lastLessonButton.focus({preventScroll: true});
  }
  function labRoute(lab, route) {
    const details = node("details");
    details.append(node("summary", route.label));
    if (route.route === "scenario") {
      details.append(node("p", `Runs ${WEB ? "in your conversation" : "inside the bot"}: four decisions with explanations. Pass with 3 of 4. Free, no cloud account.`, "task-detail"));
      const command = node("span", undefined, "task-command");
      command.append(node("code", `/lab ${lab.lab_id}`));
      details.append(command);
      return details;
    }
    const steps = node("ol", undefined, "lab-steps");
    for (const step of route.steps) steps.append(node("li", step));
    details.append(steps);
    if (route.cleanup.length) {
      details.append(node("p", route.route === "local" ? "Cleanup when you finish" : "Cleanup — right after verification", "lab-subhead"));
      const cleanup = node("ul", undefined, "lab-cleanup");
      for (const step of route.cleanup) cleanup.append(node("li", step));
      details.append(cleanup);
    }
    details.append(node("p", route.route === "local"
      ? "Self-checked practice on your own machine: nothing is deployed, charged or submitted. Verify the lab with the in-app scenario."
      : "Submit: " + route.submit, "task-detail"));
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
      : `The resource library is unavailable in this view. Tap Refresh or use /resources ${IN_BOT}.`);
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
      $("lab-gate").textContent = `${plural(required, "required lab")} still open. Unfinished required labs carry `
        + "forward to next week; your quizzes and plan never wait for them.";
    }
    labs.items.forEach((lab, index) => {
      const item = node("li");
      item.append(node("span", lab.title, "task-title"));
      item.append(node("p", `~${lab.minutes} min · ${lab.required ? "Required" : "Optional"}${lab.carried ? " · carried over" : ""} · assigned ${lab.assigned_date}`, "task-meta"));
      const state = lab.status === "verified" ? `Verified${lab.verified_route ? " · " + lab.verified_route : ""}`
        : lab.status === "needs_fix" ? "Needs a fix" : lab.carried ? "Carried to this week" : "Not verified yet";
      item.append(node("span", state, "lab-state"));
      item.append(node("p", lab.goal, "lab-reason"));
      if (lab.reason) item.append(node("p", "Last check: " + lab.reason, "lab-reason"));
      if (lab.status === "verified") {
        if (lab.cleanup === "reminder") item.append(node("p", `Delete the AWS resources to avoid charges, then send /labcleanup ${lab.lab_id} <your verified link> ${IN_BOT}.`, "lab-reason"));
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
    if (!labs.items.length) empty("lab-items", `No labs yet. Approved lessons add labs here; ${WEB ? "send /labs in your conversation to list them" : "the bot also lists them with /labs"}.`);
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
    renderQuizzes(data.quizzes || [], data.bot_url);
    renderToday(data.today, data.progress, data.bot_url);
    $("learner-name").textContent = data.profile.name;
    $("target-role").textContent = data.profile.target_role || "A plan built around your goals starts with /setup.";
    $("setup-note").hidden = data.profile.setup_complete;
    $("task-count").textContent = `${data.stats.pending} open`;
    documentCsrf = data.document_csrf || "";
    for (const id of ["tasks", "earlier-list", "plan-days", "skills", "interviews"]) $(id).replaceChildren();
    const earlier = data.tasks.filter(task => task.earlier);
    for (const task of data.tasks) (task.earlier ? $("earlier-list") : $("tasks")).append(taskItem(task));
    if (data.tasks.length === earlier.length) {
      empty("tasks", earlier.length ? "You're up to date. Older exercises are optional practice below."
                                    : "No open exercises. Your next lesson will add practice here.");
    }
    $("earlier-tasks").hidden = !earlier.length;
    $("earlier-summary").textContent = `Earlier practice (${earlier.length}, optional)`;
    setExerciseControls(exerciseBusy);
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
    const selectedModule = $("course-module").value;
    courseModules = data.courses ? data.courses.modules : [];
    $("course-module").replaceChildren(node("option", "All modules"));
    $("course-module").firstChild.value = "";
    for (const module of courseModules) {
      const option = node("option", `${module.title} (${module.topics.length})`);
      option.value = module.id; $("course-module").append(option);
    }
    $("course-module").value = courseModules.some(m => m.id === selectedModule) ? selectedModule : "";
    $("course-notice").textContent = data.courses ? data.courses.notice
      : "The stored library is unavailable. Try Refresh shortly.";
    renderCourses();
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
    if (WEB) {
      $("plan-bot-link").href = "/web#start=" + (proposed ? "plan" : "onboard");
      $("plan-bot-link").hidden = false;
    } else if (data.bot_url && /^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(data.bot_url)) {
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
    const progress = data.progress || {};
    const streakDays = progress.streak ?? data.stats.streak;
    $("study-days").textContent = `${progress.study_days_week ?? 0} of ${progress.weekly_goal ?? 4}`;
    $("streak").textContent = `${streakDays} day${streakDays === 1 ? "" : "s"}`;
    $("accuracy").replaceChildren();
    if (progress.questions_answered) {
      $("accuracy").append(document.createTextNode(`${progress.accuracy}%`),
                           node("span", ` · ${progress.questions_answered} answered`, "metric-note"));
    } else $("accuracy").textContent = "No answers yet";
    $("understood").textContent = `${progress.lessons_understood ?? 0} of ${progress.lessons_delivered ?? 0}`;
    $("done").textContent = `${data.stats.done} / ${data.stats.total}`;
    $("minutes").textContent = `${data.stats.minutes_practiced} min`;
    $("labs-verified").textContent = progress.labs_verified ?? 0;
    $("reviews").replaceChildren();
    if (progress.reviews_answered) {
      $("reviews").append(document.createTextNode(`${progress.review_accuracy}%`),
                          node("span", ` · ${progress.reviews_answered} answered`, "metric-note"));
    } else $("reviews").textContent = progress.review_due ? `${progress.review_due} due` : "None yet";
    $("graded").textContent = data.stats.answers_graded ? `(${data.stats.answers_graded} graded)` : "";
    renderRoadmap(data.mastery);
    renderCertification(data.certification, data.bot_url);
    renderCapstones(data.capstones, data.portfolio, data.bot_url);
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
    if (!data.recent_interviews.length) empty("interviews", `No graded interviews yet. Try /interview ${IN_BOT}.`);
    const awaiting = data.learning && data.learning.stage !== "legacy" && !data.learning.active_plan_id;
    $("preferences").textContent = `Scheduled coaching ${data.preferences.paused ? "paused" : awaiting ? "waiting for plan approval" : "active"} · Media: ${data.preferences.media} · Voice: ${data.preferences.voice ? "on" : "off"}`;
    $("updated").textContent = `Updated ${new Date(data.generated_at).toLocaleString()}`;
    $("notice").hidden = true;
    $("content").hidden = Boolean(wantedLesson);
    authenticated = true;
    clearTimeout(expiryTimer); clearTimeout(warningTimer);
    // A web session can last days; setTimeout fires at once beyond about 24.8 days, so clamp.
    const remaining = Math.min(data.auth_expires_at * 1000 - Date.now(), 2 ** 31 - 1);
    warningTimer = setTimeout(() => {
      if (!authenticated) return;
      $("notice").textContent = `This private view closes in about 2 minutes. ${REOPEN}`;
      $("notice").classList.remove("error");
      $("notice").hidden = false;
    }, Math.max(0, remaining - 120000));
    expiryTimer = setTimeout(() => clearPrivate(`For privacy, this view has closed. ${REOPEN}`),
                             Math.max(0, remaining));
    if (wantedLesson && shownLesson !== wantedLesson) openLesson(wantedLesson);
  }
  for (const id of ["resource-search", "resource-group", "resource-no-account"]) {
    $(id).addEventListener(id === "resource-search" ? "input" : "change", () => {
      resourceLimit = 6; renderResourceLibrary();
    });
  }
  $("resource-more").addEventListener("click", () => { resourceLimit += 6; renderResourceLibrary(); });
  for (const id of ["course-search", "course-module"]) {
    $(id).addEventListener(id === "course-search" ? "input" : "change", () => { courseLimit = 10; renderCourses(); });
  }
  $("course-more").addEventListener("click", () => { courseLimit += 10; renderCourses(); });
  $("roadmap-open").addEventListener("click", () => {
    if (mastery && mastery.next && TOPIC.test(mastery.next.id)) {
      lastLessonButton = $("roadmap-open"); openLesson("course:" + mastery.next.id);
    }
  });
  async function refresh() {
    if (uploadBusy || labBusy) return;
    if (!WEB && (!app || !app.initData)) {
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
      if (WEB && !webCsrf) {
        // The signed-in /web session supplies the CSRF token; its cookie never reaches script.
        const session = await fetch("/web/session", {cache: "no-store", credentials: "same-origin", signal: activeController.signal});
        const signedIn = await session.json();
        if (requestEpoch !== epoch || activeController.signal.aborted) return;
        if (!session.ok || typeof signedIn.csrf !== "string" || !/^[0-9a-f]{64}$/.test(signedIn.csrf)) {
          clearPrivate(session.status === 403 ? "Sign in to SkillCoach on the web to see your private progress."
            : signedIn.error || "Could not check your sign-in. Tap Refresh shortly.", session.status !== 403);
          return;
        }
        webCsrf = signedIn.csrf;
      }
      const response = await fetch("/app/data", {
        method: "POST", cache: "no-store", signal: activeController.signal, ...identity({}),
      });
      const data = await response.json();
      if (requestEpoch !== epoch || activeController.signal.aborted) return;
      if (!response.ok) {
        clearPrivate(data.error || (WEB ? "Could not verify your sign-in. Sign in again on the web."
          : "Access could not be verified. Reopen the dashboard from Telegram."), true);
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
    if (slot === "lab") labController = token;
    else if (slot === "exercise") exerciseController = token;
    else uploadController = token;
    const options = {method: "POST", cache: "no-store", signal: token.signal, body,
      ...(WEB ? {credentials: "same-origin", headers: {"X-CSRF-Token": documentCsrf}}
        : {credentials: "omit", headers: {"X-Telegram-Init-Data": app.initData, "X-CSRF-Token": documentCsrf}})};
    if (json) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const data = await response.json();
    if (requestEpoch !== epoch || token.signal.aborted) return null;
    if (!response.ok) {
      if (response.status === 403) clearPrivate(`Session expired. ${REOPEN}`);
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
        ? `That check was already submitted. ${WEB ? "Your coach posts its result in your conversation." : "The bot sends its result in Telegram."}`
        : `Check submitted. ${WEB ? "Your coach posts the result in your conversation" : "The bot sends the result in Telegram"}, and this page updates.`;
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
    if (!file || file.size > 4 * 1024 * 1024) {
      $("document-status").textContent = "Choose one PDF or TXT file up to 4 MB."; return;
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
        : `Update queued safely. ${WEB ? "Your coach confirms in your conversation" : "The bot will confirm"} when saved. Your learning history will not be reset.`;
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
    // Switching to the chat keeps what the learner is reading; only in-flight private work is cancelled.
    if (document.hidden) cancelPrivateWork();
    else if (authenticated || app || WEB) refresh();
  });
  setInterval(() => { if (!document.hidden && authenticated) refresh(); }, 60000);
  refresh();
})();
