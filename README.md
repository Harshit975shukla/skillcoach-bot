# SkillCoach Bot

An invite-only Telegram interview coach with one administrator: **full lessons and animated videos by default**, personalized plans, tracked practice tasks, five-question daily quizzes, ten-question weekly assessments, and question-first interviews. Vercel handles authenticated webhooks; GitHub Actions owns scheduled coaching and recovery. Private PostgreSQL is the only authoritative state store.

## Invite-only multi-user upgrade

The version-two access model is a code upgrade and requires its explicit schema cutover before activation; do not relax the currently deployed owner check without completing that cutover. The administrator remains the configured `OWNER_ID` (legacy `CHAT_ID` alias), validated against Telegram sender identity and matching private chat. Users cannot choose, promote or reassign the administrator.

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

These are intended times, not delivery guarantees. GitHub can delay/drop scheduled runs; schedules run only from the default branch and public-repository schedules can be disabled after 60 days without repository activity. Dashboard-repository commits do **not** keep this bot's workflows enabled. Monitor/re-enable workflows and use manual recovery when needed. Five-minute recovery consumes Actions minutes; browser installation/video encoding can be significant. Empty/no-media work avoids the browser installation.

Each schedule has a unique local-date receipt. Workflow reruns use the original run creation timestamp; weekend operations are selected explicitly, never from the runner's current weekday. An operation-specific concurrency group keeps recovery from evicting a queued lesson. Messages from an earlier local date are suppressed rather than replayed as today's learning. If a schedule was dropped before GitHub created a run, select the intended date manually; a past-date run does not replay old notifications.

## Architecture and delivery semantics

`skillcoach/config.py`, `clients.py`, `models.py`, `storage.py`, `service.py`, `runtime.py`, `export.py`, and `media.py` are shared by the thin existing entry points.

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

**Telegram is not exactly-once transport.** If a send succeeds but recording its receipt fails, recovery may send it again. Pause/cancel cannot retract a message already sent or in flight. Domain answers/task progress remain idempotent. `/pause` atomically suppresses queued scheduled deliveries and cancels queued scheduled jobs; `/unpause` enables future runs without resurrecting old messages. Manual coaching remains usable.

Supabase transaction poolers are supported: automatic prepared statements are disabled, and schema/timeouts are transaction-local. Use the exact provider-issued pooler endpoint; do not buy an IPv4 add-on or guess the region/cluster hostname.

For Supabase TLS, set `DATABASE_CA_CERT_FILE=certs/supabase-ca-2021.crt` in Vercel and the Actions repository variables, while retaining `sslmode=verify-full`. This public CA is distributed by Supabase's [official dashboard download configuration](https://github.com/supabase/supabase/blob/master/apps/studio/hooks/custom-content/custom-content.json) at [the official certificate URL](https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt). It is not a private key. Relative CA paths resolve inside the installed Python package; other PostgreSQL providers may supply their own absolute CA path. Never fix certificate errors by disabling hostname/certificate verification.

For an explicitly approved **empty** project, `python -m skillcoach.cli bootstrap-fresh` uses an admin `DATABASE_URL` and a separately generated `SKILLCOACH_RUNTIME_PASSWORD` to apply migrations and create the restricted `skillcoach_runtime` role. It refuses existing learning/processing history and unrelated pre-existing roles. The app uses the runtime role afterward, not the administrator password. Its write-permission probe is rolled back and seeds no learner profile or grades.

The optional database-preparation CI job runs only after all tests pass, only for a push, and only when `SKILLCOACH_BOOTSTRAP_SHA` exactly matches that reviewed commit. Administrator credentials are confined to that job. Remove the temporary commit gate and `SKILLCOACH_BOOTSTRAP_DATABASE_URL`/`SKILLCOACH_RUNTIME_PASSWORD` secrets after successful preparation. Never enable this gate for unreviewed code or pull requests.

The authenticated `GET /health/ready` endpoint checks private storage without exposing state; it requires the webhook-secret header. After cutover, manually dispatch the default-branch recovery workflow to verify real configuration and role permissions. Its optional `notify_owner` input sends one idempotent, release-keyed help message and creates no fake learner profile or grades. Scheduled recovery never sends that announcement by default.

## Learning and commands

`/dashboard` opens a read-only private Telegram Mini App when `PRIVATE_DASHBOARD_URL` is configured
to this deployment's `/app` route. The shared URL contains no learner identifier and returns no
personal data by itself. `/app/data` verifies Telegram's HMAC-signed `initData`, a five-minute age,
the authenticated numeric user ID and current active membership. An authentication receipt binds
each launch to the membership generation, so revoking and then reapproving a learner does not
reactivate their old dashboard launch. The owner sees only their own learning in this view.

Private responses use `Cache-Control: no-store`; the frontend keeps no localStorage copy, clears
on expiry/backgrounding, and rechecks active views periodically. It renders all user/AI strings as
text, never as HTML. Revocation blocks the next request; already downloaded content cannot be
remotely recalled. No administration actions are exposed in the Mini App. The separate public
dashboard remains anonymous and owner-controlled.

Help is generated from `skillcoach/commands.py`. `/profile` displays the private profile or enters setup; `/profile setup` replaces it only after successful validation.

| Commands | Behavior |
|---|---|
| `/start`, `/help` | Consistent supported command list |
| `/setup`, `/profile`, `/skip`, `/assess` | Resume + JD setup or exactly five open diagnostic questions; old profile survives cancel/failure |
| `/score`, `/gaps` | Actual evidence and skill ratings; unavailable is not fabricated as 50 |
| `/curriculum`, `/nextweek <preference>` | Dated six-day plan, including Saturday review; preferences apply to the next unplanned week |
| `/learn <topic>`, `/ask <question>`, `/tip` | Full lesson with tracked tasks, personalized coaching or practice tip |
| `/q A` (or B/C/D), question buttons | Answer only the active question; stale daily quizzes expire when weekly assessment starts |
| `/interview [topic]`, `/interview next` | Question first, learner answer, rubric feedback and hypothetical model answer afterward |
| `/mock [topic]` | Clearly labeled sample Q&A, **not** a graded interview |
| `/tasks`, `/today`, `/complete <id> [actual_minutes]` | Stable tasks and one-time completion; omitted actual minutes are zero, not estimated practice |
| `/skills`, `/stats`, `/streak` | Honest task counts, interview metrics and consecutive IST practice dates |
| `/resume` | Feedback on the actual stored resume/JD; never resumes notifications |
| `/pause`, `/unpause`, `/cancel`, `/retry`, `/status` | Notification, flow and recovery controls |
| `/media video`, `/media static` | Animated video default; static is opt-in |
| `/publish`, `/dashboard` | Anonymous summary export and configured dashboard link |

Plans use the actual target role, level, gaps, prior topics, task evidence and recent incorrect answers. Delivered/prepared lessons are not treated as mastery. Only completed, correctly dated weekly assessments enter a weekly score report. Missing or unfinished attempts remain unavailable. Practice on one date contributes only one streak day; a missed day resets the streak.

Resume/JD alignment scores are explicitly provisional document-based estimates. Diagnostic scores are limited evidence, not a guarantee of job readiness. Private resume/JD/answer text is sent to your configured AI provider when you invoke those features; configure an acceptable provider/data-retention policy before use.

## Full lessons and media

### Explanatory-media upgrade (requires the matching code/schema rollout)

`/topics` exposes a versioned Cloud/DevOps syllabus covering foundations, Linux, networking, Git,
scripting, AWS, Azure, Google Cloud, containers, Kubernetes, infrastructure as code, CI/CD, GitOps,
observability, SRE, DevSecOps, platform engineering, data systems, MLOps and FinOps. `/topics <module>`
lists stable topic IDs; `/learn <topic_id>` uses that entry. This is an explicit syllabus, not a promise
that every vendor feature or future version is already reviewed. The catalogue distinguishes broad
generation support from the six fully reviewed AWS lesson topics.

New media uses validated storyboards: two to six labelled actors, typed request/control/replication
edges, and three to five explanation scenes. Flow/decision scenes move markers along the active
paths; timeline/comparison scenes highlight the relevant steps rather than invent network traffic.
The six reviewed AWS architectures have authored behavior sequences. Their 24 concept-specific
comparison walkthroughs show actual named options/entities (CPU credits, storage classes, policy
types and similar), with narrated bounded excerpts while the full written concept remains available.
These are narrated comparisons, not 24 additional moving system architectures. Active edge labels
are displayed rather than discarded.
Generated topics receive concept-specific and end-to-end AI storyboards, clearly labelled
**AI-generated; verify the references**. Only supported JSON scene data is accepted; no generated
Python, HTML, shell commands, file paths or executable animation code is run.

Long lesson preparation is incremental: at most one new structured AI generation is started per
processing turn. Validated plan/lesson/storyboard results are checkpointed and reused; normal
continuation does **not** spend one of the five transient-failure attempts. Other learners receive
turns between those steps, and `/cancel` cancels the learner's unfinished preparation. The full
lesson/tasks commit only when preparation is complete. Static mode skips storyboard/narration AI
generation and uses the existing diagram path.

`/voice on` enables **offline synthetic narration**, on by default for the new video renderer;
`/voice off` keeps captions and motion. `/media static` remains an optional, captioned first-scene
walkthrough. Stock eSpeak NG `en-us` at 150 words/minute provides the fee-free baseline; it is
understandable synthesized speech, not a claim of natural human narration. Every scene is timed from
its actual WAV duration plus a short pause, and the final MP4 includes synchronized AAC audio.
Missing narration/render dependencies cause visible recoverable failures, not a silent “narrated”
video. Worker setup installs `espeak-ng` and readable system fonts only when media work is ready.

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

Authored EC2, S3, RDS, VPC, IAM and Lambda lessons contain four concepts, end-to-end flows, three stable tasks, key terms, official references, review metadata, cost cautions and cleanup instructions. Other topics use validated full AI-generated lessons, explicitly not independently reviewed. Generic exercise-flow diagrams for generated topics are illustrative, not invented service architectures.

The original video enhancement was preserved before refactoring. `skillcoach/media.py` retains the 25-second center-anchored Ken Burns zoom (1.0x to 1.25x), one-second fade-in, two-second fade-out, caption overlay, H.264 1280x720 at 24fps, and static fallback on encoding failure. Captions use a text file to avoid filter injection. Static preference keeps the full lesson.

Mermaid rendering is **local**, using the pinned npm CLI/Chromium, never `mermaid.ink` or another third-party renderer. Only Actions/local workers render media; Vercel defers it. Missing Mermaid/failed rendering remains a visible recoverable delivery failure. An unavailable ffmpeg encoder produces a labeled static fallback. Telegram upload failures stay retryable rather than silently claiming delivery. Generated media uses temporary directories.

Content reviewed on 2026-09-25 distinguishes Standard/Unlimited EC2 credits, Object Ownership/BPA, non-MD5 ETags, RDS instance/cluster/Aurora distinctions, engine-specific storage limits, PITR windows, Lambda retry modes, ZIP sizes and SnapStart compatibility, and IAM evaluation/SCP exceptions. Prices and limits are conditional; follow the references for your actual region/account/runtime. Interview stories are hypothetical unless they are your own experience.

## Development and verification

Python **3.12** is pinned consistently. Install only in your isolated checkout, not another working copy:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
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
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional primary provider; model default `openai/gpt-oss-120b` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional fallback; model default `gemini-2.5-flash`; verify current account/model availability |
| `GITHUB_TOKEN` | Optional dashboard publishing PAT; Actions maps **`secrets.GH_PAT`** to this variable |
| `DASHBOARD_REPO`, `DASHBOARD_PATH`, `DASHBOARD_URL` | Configured destination; no hard-coded personal repository or identity |

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
