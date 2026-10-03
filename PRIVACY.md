# SkillCoach privacy policy (DRAFT, not yet published)

> **Draft status.** This text is not linked from the bot or the web app yet. It becomes the policy only
> once a monitored contact for privacy requests is filled in below and the owner publishes it (for
> example as the bot's privacy policy in @BotFather). Until then Telegram's
> [Standard Privacy Policy for Bots and Mini Apps](https://telegram.org/privacy-tpa) applies to the bot.
>
> **Contact for privacy requests: NOT YET DESIGNATED.** Reminder emails say replies are not read, so they
> are not a contact.

SkillCoach is a private Cloud and DevOps coaching service run by one person (the owner) for a small,
invitation-only group. It is reached through the Telegram bot @skillOpsDev_bot and the web app at
`https://skillcoach-bot-seven.vercel.app/web`. It is not a business, has no ads and sells no data.

## What is stored

Everything below is kept in one private PostgreSQL database (Supabase), in a schema that is not
exposed through any public API.

- **Account and access:** your learner record (an internal ID, your Telegram user ID if you joined
  through Telegram, the name you gave, your sign-in email if you use the web app, and your access status).
- **Learning:** the setup answers you give (goal, experience, topics), your plans, lessons, tasks,
  quiz and assessment answers and scores, interview practice answers and feedback, lesson ratings, and
  any resume or job description text you submit.
- **Conversation:** the messages SkillCoach sends you and the requests you send it, kept as the record
  the web inbox shows. Telegram update numbers are kept to avoid processing a message twice.
- **Technical records:** sign-in records (only keyed hashes of codes and addresses), web sessions,
  notification subscriptions for the devices where you turned notifications on, rendered lesson
  videos, usage counts per day, and an audit log of access decisions.

## Who processes it

- **Groq** runs the AI that writes personalized coaching: plans, quizzes, feedback and answers. A
  request can contain your setup answers, plan, recent results, the text you are asking about, and
  resume or job description text when you use those features. Groq's documentation says it does not
  keep inference data by default, but may log it for up to 30 days to investigate reliability or abuse
  unless its Zero Data Retention setting is on ([Groq: your data](https://console.groq.com/docs/your-data)).
- **Google's Gemini API** is the fallback in the version of SkillCoach running today: when Groq is
  unavailable, the same kinds of requests can go to Gemini. On Google's unpaid quota, Google may use
  submitted content to improve its products, and human reviewers may read it
  ([Gemini API terms](https://ai.google.dev/gemini-api/terms)). A prepared update removes this fallback
  so that coaching requests go to Groq only; this sentence changes when that update is released.
- **Telegram** carries bot messages. **Supabase** hosts the database. **Vercel** hosts the web app and
  bot webhook. **GitHub** runs the scheduled workers; no learner data is committed to the public code
  repository, and worker logs do not record message content.
- **Gmail (Google)** sends sign-in codes and lesson reminder emails from the owner's account.
- **Browser push services** (Google, Mozilla, Apple, Microsoft) deliver the notifications you turn on.
  The notification text is encrypted and generic, such as "Today's lesson is ready", but these services
  also handle your device's subscription address and delivery information.
- **What the owner can see:** in the admin pages, access status, activity counts, delivery health and
  rating totals for everyone; with your consent from guided setup, also your approved plan topics,
  learning reasons, task completion and aggregate results. The admin pages do not show your resume, job
  description or private answers. As the operator, though, the owner also has full access to the
  database and to its backups, which contain everything listed above.
- **The public progress dashboard** shows only non-identifying summaries of the owner's own learning.
  No other learner's data is published.

## Consent

Before personalized coaching starts, guided setup shows what is shared and with whom, and asks you to
choose **Agree**. You can stop at that point with /cancel. That consent text says your data goes to "the
configured AI providers" without naming them; it should name them when this policy is published.

## How long it is kept

Some records expire on their own:

- Web sign-in codes and unconfirmed join requests: deleted after about two days.
- Web sessions: valid for 14 days.
- Notification subscriptions: removed when you sign out, lose access, or your address changes.
- Document upload previews: cleared after you confirm or cancel, or when they expire.
- Rendered lesson videos: removed after 30 days without being shown, or earlier when storage is full.

Everything else (your learner record, learning history, conversation record, usage counts and audit
log) is kept while the service runs. There is no automatic deletion of learning history and no
self-service deletion. The owner also keeps private, hash-checked backups of the database on their own
computer, made before software releases.

## Your requests

You can ask for a copy of your data, a correction, or deletion, and you can withdraw your consent, by
writing to the contact above (to be designated). These requests are handled by hand by the owner;
there is no button for them. Telegram's terms for bots require a response within the time applicable
law allows and no later than 30 days. Simply stopping use of the service does not withdraw consent or
delete anything, and scheduled lessons and reminders keep coming. /pause stops future scheduled
coaching until you resume it; it does not delete or erase data.

## Version

Draft of 3 October 2026. It describes the version of SkillCoach running on that date, and notes where a
prepared but unreleased update changes something.
