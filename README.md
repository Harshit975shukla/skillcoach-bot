# SkillCoach Bot

## Prewritten Cloud and DevOps library

The 199-topic syllabus is bundled with the application as versioned JSON lesson packages in
`skillcoach/course_data/2026-09-29/`. It is a maintained curriculum, not a claim to cover every vendor
product. The private dashboard's **Lessons** section searches all modules and opens theory immediately;
**My assigned lessons** keeps personal delivery history separate. `/read <topic_id>` reads the stored
reference without creating tasks, grading answers, marking a lab complete or changing a plan.
`/topics <module_id>` lists the IDs; `/learn <topic_id>` assigns the lesson's tracked exercises and video.

Each package contains four concepts, worked practice, prerequisites/objectives, an end-to-end flow,
cost/safety/cleanup, official references, interview practice and a subject-specific diagram/storyboard
with its transcript. New content is **AI-assisted and not independently expert-reviewed**, explicitly
labelled in the app. Previously reviewed exact-topic lessons retain their existing provenance. Links
and technical examples should be checked against current vendor documentation; hypothetical exercises
are not claims that a real deployment was performed. No roadmap.sh articles or diagrams are copied.

Catalog-topic theory, core session pacing and storyboards require **no runtime AI or GitHub fetch**.
Personalized planning, quizzes, feedback and free-form questions still use the configured AI providers.
Legacy topic aliases and historical authored/AI lessons remain supported. New delivered library lessons
record their topic ID and version; do not edit a released version in place or delete it while history
references it. Publish a new version and retain the old content when revising a course.
Keep prior IDs in `course_library.VERSIONS` when changing the default version.

The diagram/transcript browser is not a prerecorded MP4 library. Animated Telegram videos remain the
default and use the existing local renderer and delivery cache; Git holds their scripts, not video
binaries. No new media-hosting service, paid account, database migration or scheduler change is needed.
Once a bundled walkthrough is delivered, its bot-specific Telegram media ID is reusable across learners
with the same voice/mode settings. Sharing a public course asset does not mark it expert-reviewed;
personalized AI media stays learner-scoped.
Course content in this public repository is public; private progress, answers and documents never belong
in course packages. Opening the dashboard still requires current approved Telegram access.
Authenticated readiness checks validate every bundled module and report the installed curriculum
version/counts, so a partial course-data upload cannot pass the deployment readiness gate.

## Safe learning updates and missed lessons

`/recoverlesson` (or the specific unfinished-day button in `/plan`) explicitly resumes only unsent
parts of an existing approved lesson. It does not regenerate content or create tasks again, never
reopens confirmed sent items, respects pause/access generation, and refreshes the intended delivery
date for those unsent parts. Use `/unpause` first if paused. Next-week approval still requires the
actual final delivery marker; expired/suppressed content is not silently treated as delivered.

Plan revisions preserve the latest validated profile and reassessment, including its provenance and
documents. Only first onboarding approval initializes the profile from the initial diagnostic.
Guided diagnostic completion counts as one practice day, without invented minutes or task completion.
Migration 007 repairs prior completed diagnostics only with all five answer receipts, a matching saved
rating, and an identifiable successful completion notice bounding the completion to the same IST date
as the final submitted answer. Failure notices do not count; ambiguous cross-date histories are left alone.

Approved session objectives, practice and level now produce a separate bounded core study section:
15/30/45/60-minute targets allocate 5/10/15/20 minutes to reading/video review and respectively
one/two/three/four required exercises totaling the remaining time. Estimates are validated, not logged
as actual practice. The full reference stays one tap away ("Read the full lesson here" and the
private lesson page) for optional deeper study; extra reference exercises are labelled optional.
Changing pace never rewrites already prepared or completed tasks.

### Private resume and job-description updates

Use `/updateresume` or `/updatejd`, paste text, then explicitly confirm **Keep current plan** or
**Propose future changes**. To switch from a Telegram paste prompt to upload, `/cancel` the prompt
before opening `/dashboard`. The personal dashboard supports UTF-8 TXT and text-based PDF uploads:
256 KB maximum, 15 PDF pages, 16000 extracted characters. Resume text must have at least 80 characters
and job descriptions at least 50. Encrypted/scanned PDFs, images, DOCX and non-UTF-8 text fail explicitly.
PDFs are processed locally in a short-lived bounded process (8-second wall limit; Linux CPU/address-space
limits), without external OCR or persisted original files. Parser failures do not replace saved documents.

Dashboard uploads require fresh verified Telegram launch data/current membership, same-origin POST,
CSRF, and a five-minute preview bound to the document/session/profile/access generation. Confirmation
is transactional and idempotent. Replays cannot create another update; changes during parsing or before
processing cannot overwrite a newer profile. Preview text is cleared after confirmation/cancellation
or expiry cleanup; raw filenames and document content are never returned to admin views or logged.
The original valid profile remains until a confirmed update is processed. **No reset-all option exists.**
Future-session changes produce another learner-approved proposal while the current plan continues.
Changing a document invalidates stale resume/JD alignment, not newer tested diagnostic scores.

This release needs private migrations 007 and 008 and restricted-role grants before new routes are
used. Back up both learners, quiesce old writers, apply the reviewed upgrade, then promote the matching
code and restore scheduling. The intentional state difference is only proven diagnostic activity;
all existing plans, tasks, documents, grades and answer receipts must remain unchanged.

An owner-approved Telegram interview coach: **full lessons and animated videos by default**, personalized plans, tracked practice tasks, five-question daily quizzes, ten-question weekly assessments, and question-first interviews. Vercel handles authenticated webhooks; GitHub Actions owns scheduled coaching and recovery. Private PostgreSQL is the only authoritative state store.

## Request access, guided setup and learner-owned plans

Share `/join` on the bot's existing Vercel domain. It is a generic public page, **not the private
admin portal**. With `ACCESS_REQUESTS_ENABLED=true`, its button opens the configured Telegram bot
with `start=request`. Tapping Telegram's Start submits a request through the authenticated webhook.
No typed Telegram ID, unsigned browser parameter or public GET grants access. Pending users cannot
read learner APIs or run coaching; `/request` reports their own status. Repeated requests do not
create duplicates or repeat owner notifications. The admin portal lists requests; there is no
unsolicited owner alert for each public request. Admission is bounded to 100 pending requests and
30 new public requests per hour; the configured active-learner limit still applies at approval.
Rejected/revoked users need a fresh owner invitation rather than reactivating themselves.

The owner approves or rejects through `/admin`. An approval queues one welcome message with
**Set up my learning**. New public requesters and new invitees admitted while the public-request
flag is enabled use the guided path:

1. `/onboard`: agree to the privacy/AI-processing and admin learning-oversight disclosure.
2. Supply a goal, actual years of experience, level, daily time target and display timezone.
3. Optionally paste resume and job-description text, or skip either. Neither document is required.
4. Answer exactly five diagnostic questions, including an honest **I don't know yet** choice.
5. Review a five-session study-week proposal: catalog topics, objectives, practice, private rationale
   and dates. Diagnostic estimates are limited evidence, not certification or job readiness.
6. Approve the next lesson slot or explicitly start Day 1 now. Change topics freely in a private
   revision request; `/pace 15|30|45|60` and `/level beginner|intermediate|advanced` adjust the next
   proposal. The learner reviews the new version before it takes effect.

No artificial 10-15 minute wait is imposed. Validated AI results and follow-up jobs are committed
transactionally; provider failure leaves the flow retryable without regrading saved answers.
After delivering the immediate answer acknowledgement, a webhook may process one newly committed
plan-proposal follow-up if at least 12 seconds remain in its original 20-second budget. It reuses
that request's connection, never skips a different learner's next fair turn, and never runs a
Day 1 lesson/video in this fast path. If time is short, an older job is next, or the provider fails,
the proposal remains recoverable normally. This is a best-effort latency improvement, not a promise
that every plan finishes in the request. GitHub's scheduled recovery can still be delayed.
Recovery's media preflight recognizes eligible journey Day 1 lesson jobs as well as legacy lessons,
so an already queued Day 1 installs renderers and can deliver videos in the same worker run.
Work that becomes eligible after preflight remains safely queued if its tools were not installed.
The previously validated profile is replaced only when the learner approves the completed
diagnostic and proposal. `/cancel` keeps it and all completed history. New guided learners remain
schedule-gated until they approve; cancelling a revision restores the previously approved plan.
An existing approved plan keeps running while a revision is awaiting review; editing is not a pause.
If an approved session advances meanwhile, approval shows a reconciled proposal for confirmation
rather than replacing newly prepared work. Use `/pause` to actually stop scheduled coaching.

Plan buttons bind to the exact learner-owned proposal version. Old buttons cannot approve a
replacement. A passed start date is shown as a fresh dated version before approval. Five sessions
normally occupy weekday lesson slots and may span calendar weeks; an explicit Start now can begin
on a weekend. Dates are scheduled in Asia/Kolkata and displayed in the learner's chosen timezone;
choosing another timezone does **not** change delivery times. Weekday 09:00 lessons/18:00 quizzes,
Saturday 09:00 assessments and Sunday 10:00 reviews remain canonical. A same-day explicit start and
scheduled run cannot prepare Day 1 twice. Missed lesson slots resume the next unprepared session,
not multiple days of catch-up. Full lesson delivery is required before guided quiz generation.

Admin learning oversight is opt-in during guided setup. It uses a separate allowlisted DTO:
approved **catalog** topic names, controlled reason templates, dates, activity/streak, task counts,
learner-confirmed understanding and aggregate completed-assessment scores. It never serializes
custom goals, resume/JD text, private answers, question text, generated objectives/practice text or
raw AI rationale. Sending a lesson is not watching it; confirming understanding does not complete
tasks or change grades. An admin topic suggestion is bound to the current plan and remains
optional: declining changes nothing; accepting generates a proposal that still needs learner
approval. Prepared lessons and existing tasks are preserved across plan revisions.

**Existing-user compatibility:** absent `journey` state means the previous setup and schedule
behavior remains intact. No existing profile, plan, quiz answer, task or scheduled job is rewritten
on deployment. Existing users can opt into `/onboard`; their detailed plan is not newly shared
without consent. The private `/app` dashboard shows the learner's own proposed/approved plan and
links back to Telegram for approval; `/admin` remains owner-authenticated.

**Rollout:** this upgrade uses existing private JSONB state and transactional tables; no DDL or
data migration is required. Back up source/configuration/private state, complete offline and
disposable-PostgreSQL CI, briefly quiesce old writers for the code cutover, then enable the flag
consistently in Vercel and Actions. Old binaries do not understand new JSON fields: do not roll
back to an older binary after guided state has been written without a compatible rollback or a
reviewed restore that preserves new learner data. Never reset live learning to roll back a UI.

## Invite-only multi-user upgrade

### Owner administration

The owner console is served at `/admin` on the existing Vercel application. Use `/admin` in your
bot and tap **Open Admin in Telegram** for the simplest sign-in: Telegram supplies signed launch
data and the server verifies the configured owner automatically. No code needs to be copied or shared.
An **Open in browser** alternative is also available. It is not a public GitHub Pages data file and does not require a paid
authentication provider.

In a normal browser, select **Send PIN to Telegram**, then enter the four-digit PIN sent to the
configured owner's private bot chat and select **Sign in**. Each PIN expires after five minutes,
works once, and is bound to a high-entropy HttpOnly cookie in the requesting browser. Refreshing or
reopening `/admin` in that browser resumes an unexpired request. Cookies must be enabled; a different
browser or private window cannot finish the request.

PINs have three attempts each, with owner-wide limits of five incorrect attempts per hour and ten per
day. Sending is limited to one PIN per minute, five per hour and ten per day; a new PIN replaces earlier
PINs. Limits persist in PostgreSQL and are serialized across concurrent requests. Only a keyed PIN hash
is stored, never the plaintext PIN in the database, learning history or logs. Telegram delivery is a
single bounded attempt outside DB locks; an uncertain/failed send invalidates that PIN and reports
the failure. It is never automatically resent. One-tap `/admin` access in Telegram remains available
even when browser PIN requests are throttled.

Existing matching-code approvals remain supported for already-open older pages. The link identifier
alone cannot claim a login: only that browser's
private verifier can exchange the owner-approved request, once. Reject unexpected requests.
The cookie-free Telegram flow also works in embedded Telegram Web frames. It creates a distinct
short-lived session token stored only in JavaScript memory. Each request sends that token plus
fresh signed Telegram initData in dedicated headers; the backend rechecks signature, owner,
session expiry, Origin and CSRF. Its lifetime cannot exceed the launch data's five-minute freshness.
It cannot be used as a browser-cookie credential, and conflicting header/cookie identities are rejected.
No tokens are put in URLs, localStorage or sessionStorage. If Telegram authentication is absent,
expired or denied, the interface offers a clear browser fallback rather than repeated sign-in attempts.

Browser admin sessions expire after 15 minutes, use Secure/HttpOnly/SameSite=Strict cookies and can be
signed out. Telegram memory sessions expire within five minutes and also support logout.
Every private request rechecks the configured owner; every data/action POST checks its
Origin and CSRF token. No credentials are stored in URLs or localStorage. Pending browser responses
are aborted and epoch-checked after logout, expiry or hiding the page, so an old response cannot
repopulate private content.

The console shows member access, invitations, participation counts, last bot interaction, queued
work, delivery failures and access/action audit history. It does **not** return learner resumes,
job descriptions, private task descriptions, questions, answers or feedback. Learners are told
which participation/health summaries the owner can see. Delivery is never labelled as viewing or
mastery.

**Learning library:** choose **Load learning materials** in `/admin` to search all 199 stored lessons
by module or topic and review the complete shared theory, exercises, safety/cleanup, official references,
sample interview checklist and visual walkthrough/transcript. Lab templates (with placeholder tokens)
and the 24 attributed external resources are available there too. This is a read-only preview, not a
send, assignment, expert-review approval or library of prerecorded MP4s. Lab scenario answer keys,
learner tokens and active assessment questions are not exposed.

**Learner history:** select a learner or use their **Learning details** button to inspect all retained
lesson records and a paginated bot-delivery log. Catalog topics, source/version, completed-delivery
timestamps and task counts are shown only with guided-setup consent; custom topics are redacted.
Each delivery group reports actual sent/pending/failed/suppressed message counts and media sends.
Processing completion alone is not a successful delivery. Older imported records without receipts
are explicitly unknown, and reviewing the versioned shared reference does not expose a learner's
personalized message or exercises.

**Upcoming work:** the learner view forecasts the next IST lesson/quiz/assessment/review opportunities
from the existing scheduler and approved plan, including the next unprepared topic after missed days.
It does not generate content or mutate queues. Paused/inactive/unapproved learners have no automatic
next delivery. Quizzes and weekly assessments are conditional on lesson delivery; a forecast is not a
queued job or promised send time. Existing **Delivery health** and the delivery log show actual queued
work. Learner plan choices govern subsequent weeks; required labs carry forward and never pause them.

These views use the existing owner authentication, Origin/CSRF checks, private no-store responses and
session-expiry cleanup. They do not require a schema migration or change scheduling/delivery behavior.

Actions require a server-generated preview and explicit confirmation bound to the same session,
exact action/recipient/arguments, membership generation and five-minute expiry. Confirmation,
job/invitation creation and audit recording share one PostgreSQL transaction; retries and concurrent
double-clicks return the same result. Stale recipients, expired previews, unknown actions and
unexpected fields are rejected.

Available controls are invitations/approval/rejection/revocation, one-recipient lesson or quiz
requests, pause/unpause, cancel/retry, and an allowlisted **own-chat** bot-command panel. There is no
shell, SQL, bulk-send or grade editor. Submit quiz/interview answers, complete tasks and edit private
setup/resume data in Telegram, not through the admin console. Scheduling a quiz cannot overwrite an
existing request for that learner/date. Queued commands retain normal learner limits and routing.

Schema migration `006_owner_admin_console.sql` adds private login/session/request/audit tables.
Apply it and grant the existing restricted runtime role access using the explicit upgrade procedure,
after a fresh backup. It does not alter learner records or existing scheduled quizzes.

The invite-only access model is deployed. Its additive schema cutover preserved the existing owner's profile, history, revision and displayed question exactly. The administrator remains the configured `OWNER_ID` (legacy `CHAT_ID` alias), validated against Telegram sender identity and matching private chat. Users cannot choose, promote or reassign the administrator.

The admission flow is **one-use invitation, then owner approval**. `/invite [label]` creates a cryptographically random link valid for 24 hours; `TELEGRAM_BOT_USERNAME` must identify the existing bot. The intended recipient opens it and becomes pending, with no AI/coaching access. The owner receives an opaque learner ID and can `/approve <id>` or `/reject <id>`. `/requests` lists pending invitations, `/members` lists access status, `/invites` lists unclaimed links, and `/revokeinvite <id>` cancels an unused link. Treat invitation links as private bearer credentials: only the first claimant can consume a link, and possession alone does not grant coaching access.

`/revoke <learner_id>` immediately invalidates that learner's access generation and cancels pending/running/failed work and queued coaching. A provider call already running cannot commit after revocation. A Telegram send already in flight cannot be recalled; no exactly-once/in-flight cancellation guarantee is claimed. One explicit access-status notice is allowed after rejection/revocation. History is retained privately, and returning requires a fresh invitation and approval. The owner cannot revoke themselves.

Every state row, setup draft, displayed question, job, AI cache lookup, task/answer key, outbox recipient, preference and schedule is learner-scoped. A learner's `/pause`, `/cancel`, `/retry` and completions never modify another learner. Schedules fan out to active, unpaused learners, with an independent receipt per intended IST date. A guest cannot `/publish`; the public dashboard remains the owner's explicit anonymous summary, not a new multi-user directory or a source of guest data. Admin lists show admission metadata, not resumes, answers or other learners' profile contents.

Usage is bounded by `MAX_LEARNERS` (default 10 including the owner), `DAILY_AI_OPERATIONS` (default 40 structured generation attempts per learner per IST date), and a 20-input/minute coaching admission limit. Pending/rejected/revoked users cannot invoke AI. These are protection limits, not a guarantee that every workload fits free provider quotas. Do not enable paid overages or increase admission limits without reviewing capacity.

The worker selects the least-recently-served eligible learner, preserving order within each operation, and interleaves one domain job with up to three deliveries. For two continuously eligible learners, a newly queued small request receives a domain turn within two selections rather than waiting for the other learner's backlog. Ready text is preferred over starting a video render. An already-running bounded provider call or render can still delay later work; this is not a realtime SLA. Access is rechecked after media rendering and immediately before upload, so revocation during rendering prevents that upload. Late delivery acknowledgements never reactivate suppressed outbox entries.

**Migration:** take a new private backup of the current production state, pause scheduled writers, stop admitting webhook work and drain/stop in-flight workers. With administrator DB credentials, run `python -m skillcoach.cli upgrade-schema --writers-stopped`. It applies the additive version-two migration, preserves the owner's state/revision/displayed question exactly and grants the existing restricted runtime role access to the new private tables; it does not change the runtime password. Deploy the matching application, verify owner history and admission/isolation, then restore the intended schedules/webhook.

**Rollback compatibility:** do not run the old single-owner worker against a database that contains multi-user jobs. Keep workers/webhook paused; preserve a backup of all new private data, and restore the matching pre-upgrade database snapshot before returning to the old code. Do not drop guest history or reset the database automatically. The normal test suite uses synthetic Telegram users and a disposable PostgreSQL schema; it never seeds fake users in production.

The upgraded application is deployed at **https://skillcoach-bot-seven.vercel.app** on Vercel Hobby with private Supabase Free PostgreSQL. The approved fresh start contains no imported learner profile or invented progress; send `/setup` in the existing Telegram bot to begin personalized coaching. Automatic Git-triggered Vercel deployments remain disabled in `vercel.json`: future production changes still require explicit testing, backup and deployment.

Cutover verification on 2026-09-25 passed 73 tests including real PostgreSQL integration, rendered all 30 authored diagrams, verified the 25-second animated MP4, and completed a real default-branch recovery run with one owner help message. The Groq primary produced ten schema-valid synthetic questions within the processing budget. The existing Gemini fallback has **not** been verified as usable; it needs a valid free-tier key before relying on fallback availability. No paid plan or add-on was enabled. Rotate the temporarily shared Supabase administrator password after setup; the running app uses a separately generated, restricted database role and does not depend on that administrator password.

## Schedule (Asia/Kolkata)

| Operation | Intended local time | UTC cron | Entry point |
|---|---|---|---|
| Full lesson | Monday-Friday 09:00 | `30 3 * * 1-5` | `morning_lesson.py` |
| Five-question quiz | Monday-Friday 18:00 | `30 12 * * 1-5` | `evening_quiz.py` |
| Ten-question assessment | Saturday 09:00 | `30 3 * * 6` | `weekend_test.py` |
| Weekly review and next plan | Sunday 10:00 | `30 4 * * 0` | `sunday_plan.py` |
| Pending work recovery | Every five minutes | `*/5 * * * *` | `python -m skillcoach.cli recover` |

**On-time trigger.** GitHub's `schedule:` events have started this repository's runs 5-7 hours late (a Monday 18:00 quiz ran after midnight). Vercel crons in `vercel.json` therefore call the authenticated `GET /cron/<lesson|quiz|weekly|review>` endpoint once a day during the hour before each slot (`0 2 * * 1-5`, `0 11 * * 1-5`, `0 2 * * 6`, `0 3 * * 0` UTC; Hobby fires anywhere within that hour). The endpoint reads no learner state: it verifies `Authorization: Bearer <CRON_SECRET>`, then dispatches the matching workflow on `main` with the slot's IST `date` and a `not_before` UTC instant. The worker installs its tools, sleeps until exactly the slot (refusing waits over 100 minutes), then runs. The GitHub crons above remain as a backup: every per-learner schedule key is idempotent, so whichever run is second is a no-op. Vercel crons run only for the production deployment and are not retried, so a missed cron still falls back to the delayed GitHub run. The waiting runner time is free on this public repository.

These are intended times, not delivery guarantees. GitHub can delay/drop scheduled runs; schedules run only from the default branch and public-repository schedules can be disabled after 60 days without repository activity. Dashboard-repository commits do **not** keep this bot's workflows enabled. Monitor/re-enable workflows and use manual recovery when needed. Five-minute recovery consumes Actions minutes; browser installation/video encoding can be significant. Empty/no-media work avoids the browser installation.

Each schedule has a unique local-date receipt. A run without an explicit date takes the IST date of the latest slot at or before its original creation timestamp, so reruns and late runs keep their own slot: a quiz created after midnight is a stale no-op for the previous day instead of consuming the next day's quiz receipt; weekend operations are selected explicitly, never from the runner's current weekday. An operation-specific concurrency group keeps recovery from evicting a queued lesson. Messages from an earlier local date are suppressed rather than replayed as today's learning. If a schedule was dropped before GitHub created a run, select the intended date manually; a past-date run does not replay old notifications.

## Architecture and delivery semantics

For an explicitly requested one-off owner quiz, the operator can run
`python -m skillcoach.cli queue-owner-quiz --at <timezone-aware-ISO-time> --topic <topic>`.
This saves a durable future-due job (one request per local date), not a new recurring cron.
Recovery cannot claim it before `available_at`; repeated queueing preserves the original time/topic.
It requires the matching day's lesson to have finished delivery and does not overwrite another
active assessment. This quiz can follow a manually requested lesson even before profile setup;
it is lesson-based rather than claimed to be personalized. Paused notifications are respected.
Actual delivery begins on a recovery run at or after the due time, so Actions delays still apply.

`skillcoach/config.py`, `clients.py`, `models.py`, `storage.py`, `service.py`, `runtime.py`, `export.py`, and `media.py` are shared by the thin existing entry points.

Webhook and recovery turns reuse one request-local PostgreSQL TCP connection to avoid repeated TLS/
connection setup consuming the answer-delivery budget. Each repository operation still uses its own
short transaction with transaction-local settings; no transaction or row lock spans AI or Telegram
calls. Learner-scoped repositories share only that request's connection, not authorization/state,
and concurrent threads/requests use separate connections. Connections close at the end of the turn.
Callback acknowledgement has its own small timeout so a stale toast cannot block grading or feedback.

The current deployment pins its single Vercel Function region to `hnd1` (Tokyo), matching the
existing Supabase `ap-northeast-1` database. This avoids trans-Pacific latency on every SQL
round trip; it does not add multi-region or paid failover. If the database moves, review this
setting and measure end-to-end webhook feedback delivery again. Transaction timeouts and
search path are applied together in one parameterized SQL round trip.

Vercel uses the native Flask entry point `api.webhook:app` from `pyproject.toml`. Do not add a catch-all rewrite to `/api/webhook`: backend rewrites change the path Flask receives and would break health/readiness routes.

PostgreSQL stores the validated profile and separate setup draft, curriculum, task history, assessments/answers, interviews, preferences and dated activity in the dedicated `skillcoach_private` schema, **not `public`**. Migrations revoke PUBLIC access to that schema. Every real connection explicitly sets a transaction-local schema and statement/lock timeouts, including through poolers; URL search-path hints are not relied on. Do not add this schema to a provider's exposed Data API schemas or grant anonymous/API roles access. Grant only the bot's runtime role the required schema/table/sequence access. Versioned SQL migrations create a single-owner JSONB state row plus relational unique task/answer keys, update/schedule receipts, AI-result checkpoints, worker leases and an ordered transactional outbox. This is not an in-memory dedup cache and there is no GitHub-state fallback.

Workers acquire short-lived **fenced leases**, not transaction locks held across network calls. Domain computation occurs outside transactions. State revision checks, answer uniqueness and outbox writes commit together. Validated AI results are checkpointed privately so delivery retries do not regrade answers. A crash before an AI result is checkpointed can repeat the provider call, but only a committed result affects progress.

Webhook behavior:

- Requires a constant-time-verified `X-Telegram-Bot-Api-Secret-Token`, configured owner **user and private chat**, and private PostgreSQL. Missing configuration fails closed.
- Ignores edited/unsupported updates. Deduplicates exact `update_id` receipts, not a monotonic high-water mark.
- Button payloads contain stable session/question IDs. `/q A` and free-text answers bind to the last successfully delivered prompt; concurrent answers to one question cannot become answers to the next unseen question.
- Uses a conservative 20-second external-call budget and bounded connection/statement timeouts. No fire-and-forget threads. Vercel has a separate 60-second function ceiling.
- Returns `202 persisted` only after durable insertion. This means **accepted for processing**, not delivered or graded. Failures before persistence return retryable errors. Telegram's retries are finite and updates are retained for at most 24 hours.
- The recovery workflow is required for deferred text/media, contention and transient failures; it is not an exact five-minute SLA. Configure and verify it before registering the webhook. `/retry` or the recovery CLI can drain work manually.

Outbox items preserve order within an operation. Error notices can bypass a failed item, but a “published” success message cannot pass a failed export. Unrelated commands continue. Automatic retries have five attempts and a five-minute backoff; `/retry` resets failed work after the underlying issue is fixed. `/status` shows queue counts. Secret-safe error codes are retained privately in `jobs.error_code` and `outbox.error_code`; logs omit request URLs, provider bodies, prompts and credentials.

AI diagnostics distinguish malformed provider envelopes, truncated/refused responses, JSON/schema
errors and storyboard semantic errors using safe categories, never raw responses or learner text.
Generated storyboard references use an exact-host HTTPS allowlist, including the official Terraform
Registry (`registry.terraform.io`) for provider documentation. Lookalike domains and credential-bearing
URLs remain rejected. Fixing a failed storyboard resumes its existing job from the validated lesson
checkpoint; it does not regenerate that lesson, regrade quizzes or substitute a generic video.
An unavailable fallback remains an explicit provider error, not a successful recovery.
On Groq's GPT-OSS 120B/20B, storyboard generation uses strict structured output rather than
prompt-only JSON. The wire format uses a bounded array of actor/state entries instead of a dynamic
dictionary, so every object has explicit required properties and rejects additional fields.
Entries are validated and converted back to the existing persisted format; all local graph,
reference, identifier, text-length and narration checks still run. This does not claim factual
accuracy or semantic validity merely because the provider returned schema-valid JSON. Other
models/providers retain the original validated contract; no additional repair call is introduced.

**Telegram is not exactly-once transport.** If a send succeeds but recording its receipt fails, recovery may send it again. Pause/cancel cannot retract a message already sent or in flight. Domain answers/task progress remain idempotent. `/pause` atomically suppresses queued scheduled deliveries and cancels queued scheduled jobs; `/unpause` enables future runs without resurrecting old messages. Manual coaching remains usable.

Supabase transaction poolers are supported: automatic prepared statements are disabled, and schema/timeouts are transaction-local. Use the exact provider-issued pooler endpoint; do not buy an IPv4 add-on or guess the region/cluster hostname.

For Supabase TLS, set `DATABASE_CA_CERT_FILE=certs/supabase-ca-2021.crt` in Vercel and the Actions repository variables, while retaining `sslmode=verify-full`. This public CA is distributed by Supabase's [official dashboard download configuration](https://github.com/supabase/supabase/blob/master/apps/studio/hooks/custom-content/custom-content.json) at [the official certificate URL](https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt). It is not a private key. Relative CA paths resolve inside the installed Python package; other PostgreSQL providers may supply their own absolute CA path. Never fix certificate errors by disabling hostname/certificate verification.

For an explicitly approved **empty** project, `python -m skillcoach.cli bootstrap-fresh` uses an admin `DATABASE_URL` and a separately generated `SKILLCOACH_RUNTIME_PASSWORD` to apply migrations and create the restricted `skillcoach_runtime` role. It refuses existing learning/processing history and unrelated pre-existing roles. The app uses the runtime role afterward, not the administrator password. Its write-permission probe is rolled back and seeds no learner profile or grades.

The optional database-preparation CI job runs only after all tests pass, only for a push, and only when `SKILLCOACH_BOOTSTRAP_SHA` exactly matches that reviewed commit. Administrator credentials are confined to that job. Remove the temporary commit gate and `SKILLCOACH_BOOTSTRAP_DATABASE_URL`/`SKILLCOACH_RUNTIME_PASSWORD` secrets after successful preparation. Never enable this gate for unreviewed code or pull requests.

The authenticated `GET /health/ready` endpoint checks private storage without exposing state; it requires the webhook-secret header. After cutover, manually dispatch the default-branch recovery workflow to verify real configuration and role permissions. Its optional `notify_owner` input sends one idempotent, release-keyed help message and creates no fake learner profile or grades. Scheduled recovery never sends that announcement by default.

For a production-runner media check, dispatch recovery with `verify_media=true`. It installs the
normal offline tools and locally renders/decodes a narrated EC2 clip before recovery, without
uploading that clip, calling AI, or creating learner tasks or grades. This option defaults to false
for scheduled recovery.

## Learning and commands

`/dashboard` opens a read-only private Telegram Mini App when `PRIVATE_DASHBOARD_URL` is configured
to this deployment's `/app` route. The shared URL contains no learner identifier and returns no
personal data by itself. `/app/data` verifies Telegram's HMAC-signed `initData`, a 30-minute age,
the authenticated numeric user ID and current active membership. An authentication receipt binds
each launch to the membership generation, so revoking and then reapproving a learner does not
reactivate their old dashboard launch. The owner sees only their own learning in this view.

Private responses use `Cache-Control: no-store`; the frontend keeps no localStorage copy, clears
on expiry, and rechecks access every minute and whenever the learner returns to the view. Learners
read full lessons in the Mini App, so the signed launch stays usable for 30 minutes (admin launches
keep five) and switching to the chat no longer wipes the page or its reading position; in-flight
uploads, lab checks and exercise taps are cancelled instead, so late replies can never land. A notice
appears two minutes before the view closes. It renders all user/AI strings as
text, never as HTML. Revocation blocks the next request; already downloaded content cannot be
remotely recalled. No administration actions are exposed in the Mini App. The separate public
dashboard remains anonymous and owner-controlled.

### Missed daily quizzes

Daily quizzes stay available through **Sunday 23:59 Asia/Kolkata of the lesson's week** (the
cutoff is Monday 00:00, exclusive), rather than expiring at midnight each day. The private
dashboard's **Quizzes** section shows available quizzes, saved progress, completed scores and
deadlines. **Start / Resume in Telegram** opens a learner-scoped bot link; answers are entered
in Telegram using the existing question-bound buttons. `/quizzes` shows the same catch-up choices.
No quiz is started merely by viewing the dashboard or opening an unauthenticated URL.

Resuming preserves the original quiz date, question IDs, saved answers and grading receipts.
Completed quizzes cannot be reset or rescored. A delivered lesson whose quiz was missed can
generate one validated five-question quiz on demand; unsent lessons and past-week lessons cannot.
Only one assessment is active at a time. Catch-up buttons never replace another open assessment:
finish it or explicitly `/cancel` before switching. Normal scheduled daily/weekly assessments
still take priority over the active question; the unfinished daily quiz remains resumable from
the catalogue until its Sunday deadline. Saturday's ten-question assessment is separate and
keeps its existing same-day deadline. Neither schedules nor historical lesson dates are changed.

### Daily learning loop

These behaviors keep full lessons and animated video as the default while making practice lighter
and more rewarding:

- **One tap for everything.** Every exercise has **✅ done**, **⏭ Skip** and **🆘 Stuck** buttons in
  Telegram, and **Mark done**/**Skip** on the dashboard. After Done, optional 10/20/30/45-minute
  buttons log practice once. **Stuck** generates three private hints once (nudge, stronger hint,
  solution outline) and reveals one per tap. `/complete` still works.
- **Quiz me now.** Each lesson ends with **Quiz me now** (today's validated five questions) and
  **Explain it differently** (one cached AI re-explanation grounded in the lesson). The 18:00 run
  never creates a second quiz for the same date: it only reminds about an unfinished one.
- **One message per answer.** Answer feedback and the next question arrive together. The final
  message shows the score and asks one tap about the lesson: Clear, Confusing, Too easy or Too hard.
  Those counts feed the next plan proposal and the owner's rating totals.
- **Quieter chat.** Only the first message of each lesson, quiz or reply makes a sound; follow-up
  parts, and everything between 22:00 and 07:00 in the learner's timezone, arrive silently.
- **Fair study days and streaks.** Study days start at 04:00 IST, so late-night study counts for the
  day you are finishing. Answering a question, finishing an exercise, asking the tutor, getting a hint,
  marking a lesson understood, re-explaining it and lab practice count. Sundays are rest days and one
  missed weekday per week is forgiven. Streak milestones (3, 7, 14, 30, 60, 100) are celebrated once.
  The weekly goal is 4 study days.
- **Wins-first Sunday recap.** The review reports study days, lessons received and understood,
  quiz answers and accuracy, exercises, labs, strongest and weakest quiz topics, and one focus for
  next week. It never reports "0/5 sessions" just because exercises were not ticked.
- **Weeks never stall.** Sunday's next-week proposal starts automatically at the next 09:00 IST
  lesson slot unless the learner changes it first, including when a change request was left
  unfinished. Learners are told in advance and can edit it afterwards; completed work is kept. The
  first plan after onboarding still needs explicit approval. A finished week without a proposal
  (for example after `/unpause`) is planned at the next lesson slot.
- **Home and menu.** `/start` and `/menu` show the next step with buttons for Today, Quizzes,
  Progress, Ask the tutor and the dashboard; **Ask the tutor** accepts the next typed message as a
  question. `python -m skillcoach.cli configure-telegram` idempotently registers the eight core
  commands in Telegram's command menu and sets the chat menu button to the private dashboard.
- **Dashboard Today card.** The learner dashboard opens with one next action (continue a quiz,
  read today's lesson, catch up or do an exercise), today's lesson/quiz/exercise status and the
  week's study days. Exercises show newest first; ones older than a week move to optional
  **Earlier practice**. Progress shows study days, streak, quiz accuracy, lessons understood,
  exercises, logged minutes, labs and interviews.
- **Late-delivery alerts.** When a scheduled lesson or quiz finishes reaching learners more than 20
  minutes after its slot, or still has parts waiting, the owner gets one alert for that slot.

### Spaced review, mistake practice and the roadmap

- **Spaced review (`/review`).** Every missed daily or weekly quiz question becomes a review card due the
  next study day; correct daily answers are checked again after a week. Remembered cards move through
  1, 3, 7, 14 and 30-day gaps and retire after a month; a miss sends a card back to one day. Sessions
  hold up to five due questions, reuse the quiz's validated question (no AI call) and use the same
  question-bound buttons and unique answer receipts. Due reviews become the Today/Home next step as a
  short warm-up, and never replace an open quiz.
- **Practise my mistakes.** A daily quiz with mistakes offers one AI-generated fresh question per
  mistake (a new angle, never the original wording), once per quiz. Practice and review answers never
  change quiz scores or quiz accuracy; they are reported separately.
- **Understanding checks.** After **I understand**, the bot offers five quick questions immediately
  (or shows the quiz score if already taken), because self-reported understanding is weak evidence.
- **Evidence-based roadmap.** The dashboard's lesson library shows each started topic as Learning,
  Needs review (due reviews or under 60% recently) or Solid (80%+ over at least four answers and a
  question still remembered a week later), plus the next recommended topic. These describe practice
  evidence, not certification.
- **Adaptive plans and better questions.** Plan proposals see recent quiz results by topic and lesson
  fit feedback, schedule revision for weak or confusing topics and move ahead when results are strong
  and lessons feel too easy. Quizzes mix scenario/troubleshooting and command/config questions with
  explanations of the tempting wrong option. The weekly assessment points to `/interview` for a graded
  written explanation.

Help is generated from `skillcoach/commands.py`. `/profile` displays the private profile or enters setup; `/profile setup` replaces it only after successful validation.

| Commands | Behavior |
|---|---|
| `/start`, `/menu`, `/help` | Home card with the next step and quick buttons; grouped command list |
| `/setup`, `/profile`, `/skip`, `/assess` | Resume + JD setup or exactly five open diagnostic questions; old profile survives cancel/failure |
| `/score`, `/gaps` | Actual evidence and skill ratings; unavailable is not fabricated as 50 |
| `/curriculum`, `/nextweek <preference>` | Dated six-day plan, including Saturday review; preferences apply to the next unplanned week |
| `/learn <topic>`, `/ask <question>`, `/tip` | Full lesson with tracked tasks, personalized coaching or practice tip |
| `/resources [cloud\|devops\|linux\|topic\|search]` | Curated free learning links; `--page 2` for more; no AI call |
| `/q A` (or B/C/D), question buttons | Answer only the active question; old buttons cannot grade a different question |
| `/review` | Spaced review of missed and previously correct questions that are due; up to five per session |
| `/quizzes`, `/quiz <id or lesson date>` | Resume unfinished daily quizzes through Sunday 23:59 IST without resetting answers; also available from the private dashboard |
| `/interview [topic]`, `/interview next` | Question first, learner answer, rubric feedback and hypothetical model answer afterward |
| `/mock [topic]` | Clearly labeled sample Q&A, **not** a graded interview |
| `/today`, `/tasks`, `/complete <id> [actual_minutes]` | Today's lesson, quiz and one-tap exercises; open exercises newest first; one-time completion, omitted minutes are zero, not estimated practice |
| `/progress`, `/skills`, `/stats`, `/streak` | Study days, streak, quiz accuracy, lessons understood, honest task counts and interview metrics |
| `/resume` | Feedback on the actual stored resume/JD; never resumes notifications |
| `/pause`, `/unpause`, `/cancel`, `/retry`, `/status` | Notification, flow and recovery controls |
| `/media video`, `/media static` | Animated video default; static is opt-in |
| `/publish`, `/dashboard` | Anonymous summary export and configured dashboard link |
| `/labs`, `/lab <id>` | Your labs, what is pending, and the steps for each free or optional route |
| `/submitlab <id> <link>`, `/labcleanup <id> <link>` | Verify a code or AWS lab link; confirm that AWS resources were deleted |
| `/labcarry` | Explains that unfinished required labs now carry forward automatically and lists open ones |

Plans use the actual target role, level, gaps, prior topics, task evidence and recent incorrect answers. Delivered/prepared lessons are not treated as mastery. Only completed, correctly dated weekly assessments enter a weekly score report. Missing or unfinished attempts remain unavailable. Practice on one study day contributes one streak day (see the daily learning loop below).

Resume/JD alignment scores are explicitly provisional document-based estimates. Diagnostic scores are limited evidence, not a guarantee of job readiness. Private resume/JD/answer text is sent to your configured AI provider when you invoke those features; configure an acceptable provider/data-retention policy before use.

## Free learning library

`/resources` and **Free resources** in the private dashboard expose 24 curated links across cloud,
DevOps and Linux. Search by provider, keyword, syllabus module/topic ID, or resource ID. Telegram
shows four results at a time (`/resources linux --page 2`); the dashboard supports area/search and
no-account-to-read filters. Each entry includes attribution, level, format, a suggested starting
point, account requirements, cost caveats and its link/access review date (initially 2026-09-29).
This is a link/access review, **not** an expert audit of entire courses or a permanent price guarantee.

Sources include AWS Educate and service documentation, Microsoft Learn, Google Cloud documentation,
Pro Git, GitHub Actions, Docker, Kubernetes, Terraform's local Docker track, Ansible, Prometheus,
Google SRE books, Killercoda, Argo CD, Helm, Ubuntu, GNU Bash, LinuxCommand.org, Debian, systemd and
MIT's Missing Semester. Related resources appear on the full lesson page, in the chat full-reference
view and with lab steps. Older lesson records are not rewritten. Full daily lessons and animated
videos remain unchanged; resources supplement rather than replace them.

**No new completion gates.** These external resources are optional. Opening a link does not create
tasks, log minutes, award grades, verify a lab or change a streak. They never block quizzes or
next-week planning.

**Free access is not free infrastructure.** Documentation can be read without deploying anything.
Provider-hosted practice can require a free account and impose session limits. Optional exams,
paid courses, software licensing and learner-owned cloud usage are separate; do not enter billing
details or create cloud resources just to read a guide. The linked Debian handbook edition covers
Bullseye; learners are told to check current release documentation.

**Publisher rights and privacy.** The catalog stores links and original SkillCoach descriptions,
not copied courses, videos, PDFs or translations. Pro Git and LinuxCommand.org have non-commercial
license restrictions; they are linked, not rehosted or sold. Other materials remain subject to their
publishers' terms; free availability is not a redistribution license. No endorsement or partnership
is implied. Outbound URLs contain no learner/profile/answer data, use no referral tracking and open
only on the learner's action. Providers apply their own privacy policies after opening. No content
is scraped or sent to an AI provider at runtime, and resource discovery makes no external API call.

Maintainers edit `skillcoach/resources.py`, recheck source availability/access and cost notes, and
bump `RESOURCE_VERSION` when reviewing the catalog. Regression tests validate catalog IDs, topic
mapping, safe URLs, bounded pagination, unchanged learning state and dashboard behavior using fakes.
There is no dependency, environment, database migration, scheduler or public-dashboard change.

## Hands-on labs

Approved lessons on eight AWS topics come with a hands-on lab. The labs cover S3 presigned access, Lambda Function URLs, IAM policy evaluation, API Gateway health routes, CloudFront private origins, DynamoDB conditional writes, SQS idempotent consumers and VPC subnet routing.

Each lab carries a per-learner token and offers up to three routes:

| Route | Cost | How it is verified |
|---|---|---|
| In-app scenario | Free, no account | Four decisions with explanations inside the bot. You pass with 3 of 4, and you get 3 attempts per day. |
| Code lab | Free on a personal GitHub account | You create a public repository from the template repo [`skillcoach-labs`](https://github.com/Harshit975shukla/skillcoach-labs) and edit only the starter file. You can work in Codespaces or locally. The tests use `moto` fakes, not real AWS. SkillCoach verifies the lab when three things hold: the `lab-<id>` Actions job passed on the default-branch head, the protected tests, workflow and requirements match pinned Git blob hashes, and your token file is present. |
| Your own AWS account | **Optional and may cost money** | You submit the S3 presigned, Lambda, API Gateway or CloudFront HTTPS link. SkillCoach checks three things: the host is a public AWS endpoint, there is no redirect, and the response contains your token. `/labcleanup` then confirms that the same link no longer serves the token. |

**When required labs are due.** Pace sets the number: 15–30 minute plans require 1 lab a week, and 45–60 minute plans require 2. Further labs are optional.

**Nothing waits for labs.** Quizzes, lessons, weekly assessments and next week's plan continue whether or not labs are done. On Friday, the quiz message reminds you about open required labs. At Sunday's review, unverified required labs from the finished week carry forward automatically and stay visible in `/labs` and the dashboard until verified. Carrying has no limit and never blocks planning.

**Grandfathered plans.** Plans approved before labs existed keep `labs_enabled=false` and never receive a lab or wait for one.

**Where to track labs.** Pending labs, tokens, steps and official references appear in `/labs` and in the dashboard's Labs section. The dashboard also accepts a link.

**Kill switch.** `LABS_ENABLED=false` stops new assignments, checks and the review gate. Lessons and quizzes continue. A gate that is already waiting releases at the next scheduled lesson, quiz or review job. Set the same value in the Vercel environment and the GitHub Actions `LABS_ENABLED` repository variable, because the webhook and the scheduled worker read their own copies.

**Limits and privacy.** There are 12 link checks per learner per day, and only one lab check can be queued at a time. Checks are idempotent by request ID: a retried job reuses its cached result and never runs the check again. Submitted links are removed from job payloads and command text once the job finishes. An AWS-verified lab keeps only a keyed digest of the link so that cleanup can be confirmed. The owner console shows only counts: verified, pending, required, and whether the gate is blocking.

This is a **practice-integrity check, not proctoring**. A passing check shows that the artifact behaves as specified and is linked to the learner's token. It does not prove who did the work. Never share AWS keys, passwords or console screenshots. SkillCoach never asks for them.

`LABS_GITHUB_TOKEN` is optional. Use it only to raise GitHub's unauthenticated API rate limit, with a fine-grained token that has **no repository permissions** (public read only). Never reuse `GH_PAT`. Maintainer references for the code labs live in `tests/lab_reference/`. CI runs every lab twice: against the starter, which must fail, and against the reference, which must pass the exact expected test count.

## Full lessons and media

### Lesson format

A lesson arrives as at most four Telegram messages, formatted with bold text and code blocks:

1. **Mission**: title, time split, today's goal, the core explanation, and cost and safety notes to
   read before starting. Buttons: **Open lesson page** (private dashboard) and **Read the full lesson
   here** (sends the complete reference in chat, with no AI call).
2. **One architecture video** (animated by default; `/media static` for an image).
3. **Exercises**: the required, tracked tasks with exact commands or file contents and a
   `/complete <id>` line for each.
4. **Closing**: cleanup steps, one scenario interview question for the exact topic (the answer
   checklist is in the full lesson), and feedback buttons.

The private lesson page (`/app?lesson=<id>`, opened from the button or the dashboard's Lessons list)
shows the whole lesson with copyable code blocks. It is authorized with the same signed Telegram launch
as the dashboard and only returns lessons in the signed learner's own history.

Feedback stores only the button pressed: Useful / Not useful, or one of five fixed report reasons
(wrong, outdated, confusing, too hard, too easy). No free text is collected. The owner's `/admin` view
shows totals only, never which learner or lesson.

Content checks run on every AI lesson before it is accepted, and the failure message is returned to the
provider as its single repair hint: retired or branch-pinned GitHub Actions majors, IAM actions for tools
that are not AWS services, cloud credentials configured after the cloud command, workflow triggers
nested inside a job, OIDC without `id-token: write`, invalid JSON blocks and missing official
references. Accepted lessons are upgraded to current action majors deterministically.

Ten lessons are human-reviewed against official documentation: the six AWS topics below, plus CI
pipeline design, Kubernetes Pods/Deployments/ReplicaSets, Terraform providers/resources/modules and
GitHub Actions OIDC. Those four use a fixed reviewed core and exercises (no AI call) scaled to the
approved minutes; for the AWS lessons the core session is condensed by AI from the reviewed reference
and validated. Other topics are AI-generated, checked automatically and labelled **not
human-reviewed**.

### Explanatory media and offline narration

`/topics` exposes a versioned Cloud/DevOps syllabus covering foundations, Linux, networking, Git,
scripting, AWS, Azure, Google Cloud, containers, Kubernetes, infrastructure as code, CI/CD, GitOps,
observability, SRE, DevSecOps, platform engineering, data systems, MLOps and FinOps. `/topics <module>`
lists stable topic IDs; `/learn <topic_id>` uses that entry. This is an explicit syllabus, not a promise
that every vendor feature or future version is already reviewed. The catalogue distinguishes broad
generation support from the ten human-reviewed lesson topics.

New media uses validated storyboards: two to six labelled actors, typed request/control/replication
edges, and three to five explanation scenes. Flow/decision scenes move markers along the active
paths; timeline/comparison scenes highlight the relevant steps rather than invent network traffic.
Each lesson sends one architecture video. The ten reviewed topics use authored behavior sequences
that can be shared across learners. Active edge labels are displayed rather than discarded.
Generated topics receive one end-to-end AI storyboard, clearly labelled
**AI-generated; verify the references**. Only supported JSON scene data is accepted; no generated
Python, HTML, shell commands, file paths or executable animation code is run.

Long lesson preparation is incremental: at most one new structured AI generation is started per
processing turn. Validated plan/lesson/storyboard results are checkpointed and reused; normal
continuation does **not** spend one of the five transient-failure attempts. Other learners receive
turns between those steps, and `/cancel` cancels the learner's unfinished preparation. The full
lesson/tasks commit only when preparation is complete. Static mode skips storyboard/narration AI
generation and uses the existing diagram path.

**Caption-only animation is now the safe default.** The original eSpeak voice was rejected for listening
quality. `NARRATION_ENABLED=false` keeps it unavailable; `/voice on` clearly explains that no approved
replacement is ready instead of silently reverting to the robotic voice. `/voice off` records the
learner's preference while keeping captions and motion. Existing explicit preferences are preserved
in storage, but cannot enable an unapproved narrator. No neural voice is downloaded or enabled
automatically. Approve the exact engine/model licence and a listening sample before enabling a
replacement; a syntactically valid audio file is not evidence of acceptable voice quality.

Pending media applies the current preference before selecting the cache/render variant and checks
again immediately before upload when narration was selected. A voice-off change during rendering
leaves that delivery pending for a silent rerender; already in-flight Telegram uploads cannot be
recalled. Narrated and silent cache keys are separate, so an old narrated file ID cannot satisfy a
silent request. `/media static` remains an optional, captioned first-scene walkthrough.

The explicit legacy renderer remains testable but is not an automatic fallback. Its spoken mode
times scenes from actual WAV lengths and encodes AAC; silent mode contains **no audio stream**.
Production worker verification checks that silent default using `ffprobe` and a full decode.
Readable fonts and FFmpeg are installed for video; eSpeak is installed only if narration has been
deliberately enabled by the operator.

MP4s/WAVs/frames exist in temporary worker storage during rendering. After successful Telegram upload,
the bot saves the Telegram media `file_id` and versioned rendering metadata in private PostgreSQL.
It reuses that file ID for unchanged media; the cache key includes storyboard, renderer, voice and
mode. Only fixed reviewed content can share a cache entry across learners. Generated/personalized
media is learner-scoped. No large media blobs or personal storyboards are committed to Git or sent
to an external diagram service. Telegram reuse is not an archival backup: preserve the source
templates/storyboards and database backups so assets can be regenerated.

The renderer uses Pillow and FFmpeg, and narration uses stock eSpeak NG. These do not require a
paid speech API or a software licence purchase, but their open-source licences still apply:
[Pillow licence](https://pillow.readthedocs.io/en/stable/about.html#license),
[FFmpeg licensing](https://ffmpeg.org/legal.html), and
[eSpeak NG GPLv3+](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING).
The system consumes installed tools; redistribution must preserve their applicable notices/source
obligations. No third-party neural voice model is bundled or assumed to share the engine's licence.

Authored EC2, S3, RDS, VPC, IAM and Lambda lessons contain four concepts, end-to-end flows, three stable tasks, key terms, official references, review metadata, cost cautions, cleanup instructions and a scenario interview question with an answer checklist. Other topics use validated full AI-generated lessons, explicitly not independently reviewed. Generic exercise-flow diagrams for generated topics are illustrative, not invented service architectures.

The original video enhancement was preserved before refactoring. `skillcoach/media.py` retains the 25-second center-anchored Ken Burns zoom (1.0x to 1.25x), one-second fade-in, two-second fade-out, caption overlay, H.264 1280x720 at 24fps, and static fallback on encoding failure. Captions use a text file to avoid filter injection. Static preference keeps the full lesson.

Mermaid rendering is **local**, using the pinned npm CLI/Chromium, never `mermaid.ink` or another third-party renderer. Only Actions/local workers render media; Vercel defers it. Missing Mermaid/failed rendering remains a visible recoverable delivery failure. An unavailable ffmpeg encoder produces a labeled static fallback. Telegram upload failures stay retryable rather than silently claiming delivery. Generated media uses temporary directories.

Content reviewed on 2026-09-25 distinguishes Standard/Unlimited EC2 credits, Object Ownership/BPA, non-MD5 ETags, RDS instance/cluster/Aurora distinctions, engine-specific storage limits, PITR windows, Lambda retry modes, ZIP sizes and SnapStart compatibility, and IAM evaluation/SCP exceptions. Prices and limits are conditional; follow the references for your actual region/account/runtime. Interview stories are hypothetical unless they are your own experience.

## Development and verification

Python **3.12** is pinned consistently. Install only in your isolated checkout, not another working copy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test,labs]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q skillcoach api
npm ci
npm run test:diagrams
```

`requirements.txt` and `pyproject.toml` share exact runtime dependency versions. `package-lock.json` pins local rendering dependencies. Tests block real HTTP APIs. PostgreSQL tests require `TEST_DATABASE_URL` pointing to a **disposable test database** (its name must include `test`); each test creates/removes only a uniquely named test schema. Without it, those integration cases skip explicitly. CI provides PostgreSQL 16 and uses only fake external APIs.

For the full real local media check, install ffmpeg/ffprobe and Mermaid's Chromium dependencies, put `node_modules\.bin` on `PATH`, then run:

```powershell
.\.venv\Scripts\python.exe tests\verify_media.py
```

It locally renders all 30 authored diagrams and verifies actual MP4 duration, dimensions and frame rate. It sends nothing. CI runs this too. The lighter npm check parses all diagrams without a renderer/browser download.

On machines where repeated browser startups time out, `npm run test:render` renders and screenshot-verifies all 30 diagrams in one reused browser, with external HTTP requests blocked. Set `PUPPETEER_EXECUTABLE_PATH` to an already installed compatible local browser if no bundled Chromium is available. This supplements, not substitutes for, the actual MP4 encoding check.

The opt-in polling adapter is `python bot.py`. It shares authentication/storage/domain services, refuses to start if a webhook is registered, never removes/replaces a webhook, and never schedules duplicate reminders. Retired `reminder.py` prints a deprecation message and sends nothing. Old Render/Procfile deployment definitions were removed to avoid a second active worker architecture.

## Configuration

See `.env.example`; environment variables are loaded at operation startup, not networked at import time. `.env` is **not automatically loaded**.

| Setting | Purpose |
|---|---|
| `DATABASE_URL` | Provider-neutral private PostgreSQL URL; verified TLS for remote DBs; use a least-privilege runtime role |
| `TELEGRAM_BOT_TOKEN`, `OWNER_ID` | Required messaging configuration; positive private-chat owner ID (`CHAT_ID` is a legacy alias) |
| `TELEGRAM_WEBHOOK_SECRET` | Vercel-only requirement: 32-256 random URL-safe characters matching webhook registration |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional primary provider. `GROQ_MODEL` is a comma-separated fallback list (default `openai/gpt-oss-120b,openai/gpt-oss-20b`); the first model is tried first and extra Groq models only after Gemini, because Groq quotas are per model |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional fallback. Comma-separated list (default `gemini-3.8-flash,gemini-3.5-flash,gemini-2.5-flash`); newer Google projects get HTTP 404 for models in the LEGACY stage, so the next listed model is tried |
| `GITHUB_TOKEN` | Optional dashboard publishing PAT; Actions maps **`secrets.GH_PAT`** to this variable |
| `DASHBOARD_REPO`, `DASHBOARD_PATH`, `DASHBOARD_URL` | Configured destination; no hard-coded personal repository or identity |
| `LABS_ENABLED`, `LABS_TEMPLATE_REPO` | Hands-on labs kill switch (default `true`) and the public `owner/repository` code-lab template |
| `LABS_GITHUB_TOKEN` | Optional secret: a fine-grained token with no repository permissions, used only for rate limits; never `GH_PAT` |
| `CRON_SECRET` | Vercel-only secret (at least 32 random characters) that Vercel sends as `Authorization: Bearer ...` to `/cron/*`; unset or short fails closed |
| `SCHEDULER_REPO`, `SCHEDULER_GITHUB_TOKEN` | Vercel-only: this bot's `owner/repository` and a token allowed to dispatch its workflows (Actions: write). The token falls back to `GITHUB_TOKEN` |

At least one AI provider is needed for generated coaching. Model quotas/free tiers are not promised. GitHub `DASHBOARD_*` and model settings are repository variables; database/Telegram/AI/PAT values are secrets. No secrets are needed for offline tests.

## Private import and privacy-safe dashboard

The separate dashboard frontend is out of mutation scope. Its `docs/app.js` blob `cb5427483bf2c43a136cb51c9c5792afb9271d61` expects `profile`, `stats`, `activity`, `skills`, `open_tasks`, `recent_done`, `recent_answers`, `resume`, and `generated_at`. The exporter builds these fields from scratch with `schema_version: 1`.

Names/roles are generic placeholders, skills use an exact controlled taxonomy, tasks/questions use generic labels, numeric IDs are public-only ordinals, and `resume` is null. No chat IDs, personal names, custom task text, answers, feedback, resume/JD contents, active questions, keys, arbitrary nested data or provider errors are copied. Counts are recalculated, actual practice minutes are not inferred from estimates, and missing average scores are null.

Publishing uses the configured single file and GitHub SHA preconditions. The original file SHA is persisted before writing; a timeout can be retried safely if the same content is already present. A concurrent edit remains a visible conflict; the retry does not refresh the SHA and overwrite it. Review the conflict outside the bot and explicitly issue a new `/publish`.

Import accepts only a **user-supplied local legacy snapshot**, never automatically downloads production/public data:

```powershell
python -m skillcoach.cli import-legacy C:\private\legacy-snapshot.json
# Review counts, preserved/quarantined history and the digest before an authorized import:
python -m skillcoach.cli import-legacy C:\private\legacy-snapshot.json --apply --confirm-digest <reviewed-digest>
```

Dry run requires no database or messaging credentials and makes no writes. Apply requires an explicitly migrated empty database and the exact reviewed digest. Repeating the same import is idempotent; another snapshot cannot overwrite existing learning. Both original `completed_tasks` and compatible `recent_done` are supported; identical duplicates collapse, conflicting duplicates fail. IDs, assigned dates and timezone-aware completion timestamps are required. Public dashboard exports cannot reconstruct private history and are rejected.

Validated task records, complete six-day legacy plans and dated lesson topics are imported. The full supplied snapshot remains private archival data. Historical scores, active questions and incomplete setup are quarantined, not activated or counted as current assessment evidence. Incomplete plans remain in the archive. Legacy lesson delivery is marked unverified. Reassess the profile after import; old aggregate counters are not trusted.

## Secure cutover checklist (operator-controlled; retain for future releases)

1. Review this worktree and run CI, including real PostgreSQL and media checks. The separate frontend stays unchanged.
2. Arrange private PostgreSQL, backups, TLS verification, retention and restricted access outside chat. Use an administrator only for the explicit additive `python -m skillcoach.cli migrate`; grant the runtime role only required table/sequence permissions afterward. Never point tests at production.
3. Securely configure Vercel and Actions secrets/variables. Verify outbound connectivity, supported AI models, runtime limits and optional GitHub PAT scope only to the dashboard repository.
4. Review and authorize a local legacy snapshot dry run/import. Check private task counts/profile and reassess untrusted readiness. Import does not send Telegram messages or publish data.
5. Disable the old reminder/polling deployments and old workflow versions before enabling the new default-branch schedule/recovery workflows. Verify manual recovery first against an explicitly approved environment.
6. Only with separate live approval, deploy Vercel and register its webhook with the shared secret and `allowed_updates` limited to `message` and `callback_query`. This implementation never calls `setWebhook` or `deleteWebhook`.
7. Explicitly verify owner authorization, database persistence, one lesson/quiz and recovery. Then approve `/publish` and inspect the anonymous JSON. No live activation is implied by a successful code build.
8. Inventory and remove previously public private data (including any per-chat JSON files) from the dashboard working tree, caches and hosting. **Old private data can remain in Git history**; history rewriting requires its own reviewed authorization. Rotate exposed credentials if applicable. This upgrade does not erase old disclosures.

Operational references: [Vercel Python](https://vercel.com/docs/functions/runtimes/python), [Vercel limits](https://vercel.com/docs/functions/limitations), [Telegram webhooks](https://core.telegram.org/bots/api#setwebhook), [Actions schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Zero-cost deployment gate and rollback

No software license purchase is required by this implementation, but open-source license terms still apply. Free hosting is conditional, not an unlimited availability promise. Do not enable paid plans, overages, add-ons, larger runners, payment-card setup or automatic credit reload for a zero-cost deployment.

- GitHub documents free standard GitHub-hosted runners for **public** repositories. These workflows use standard Ubuntu runners and do not upload artifacts or enable Actions caches. Reassess cost controls before making the repository private.
- Vercel Hobby is free for personal/non-commercial use and can pause features at usage limits. Verify the actual linked account is Hobby; a successful existing deployment does not prove its billing plan. Do not enable Pro or paid integrations.
- A user-owned free PostgreSQL plan must be verified before provisioning or import. For example, Supabase Free documents a 500 MB database, two active projects and inactivity pausing. Neon Free documents 0.5 GB/project and compute/transfer limits. Free quotas and pauses can interrupt coaching. Database tables must not be anonymously exposed through provider data APIs.
- Five-minute recovery can keep an autosuspending database awake. Check its compute quota against that polling frequency; do not assume “scale to zero” makes this usage free indefinitely. Any slower recovery frequency is a user-visible behavior change requiring an explicit decision.
- Use AI keys only from verified free-tier accounts/models with no paid billing enabled. Gemini free-tier data handling differs from paid service; review privacy terms before sending resumes/JDs. Limits cause recoverable failures, not permission to upgrade.

Before changing live state, create private, hash-verified backups outside the repository: the deployed-source Git bundle/ref, current original and upgraded source snapshots, deployed version/settings metadata, and the legacy dashboard JSON/private database snapshot. Never upload private snapshots as Actions artifacts or commit them. A source tag alone is not a data backup.

Rollback procedure: pause new scheduled writers and webhook mutations first; restore the prior deployed source/version and matching environment configuration, then restore the corresponding private-state snapshot using the database provider's approved restore process. Re-enable only the previously recorded workflow/webhook settings and verify one owner-only interaction. If returning to the old GitHub-state implementation, explicitly approve that older privacy model before any public write; do not blindly republish a private backup. Keep new private state intact for diagnosis. Do not force-push, rewrite history, or delete the new database to simulate rollback.

Free-plan references (reviewed 2026-09-25): [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Vercel Hobby](https://vercel.com/docs/plans/hobby), [Neon plans](https://neon.com/docs/introduction/plans), [Supabase pricing](https://supabase.com/pricing), [Gemini billing](https://ai.google.dev/gemini-api/docs/billing).
