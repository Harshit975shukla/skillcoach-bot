# Product

<!-- impeccable:product-schema 1 -->

<!-- Written on 4 Oct 2026 from the repository and the owner's request. The owner was not available
     for the product interview; facts marked (inferred) are assumptions to confirm at review. -->

## Platform

web

## Users

- The owner: a single coach-and-learner who runs SkillCoach privately to prepare for Cloud and DevOps
  roles and interviews.
- A small number of invited learners, each approved by the owner. They use Telegram, the installable
  web app (`/web`) and email reminders.
- (inferred) Practice happens in short sessions on a phone, between other work, as well as at a desk.

## Product Purpose

SkillCoach teaches Cloud and DevOps topics through a daily rhythm: a weekday 09:00 IST lesson, an 18:00 IST
quiz, a Saturday assessment and a Sunday review, plus hands-on labs, mock interviews and resume feedback.
Success means learners can explain and apply a topic in an interview or on the job, not only finish
messages.

## Positioning

A private coach built on a maintained 199-topic syllabus (23 modules) with prewritten lessons,
end-to-end flows, labs with cost and cleanup steps, interview questions and diagrams. Practice is
grounded in that curriculum and in real engineering tasks (commands, manifests, incidents), not generic
trivia.

## Operating Context

- Lessons, quizzes and replies reach learners through the web app and Telegram, with email as fallback.
- Course content lives in the public repository and is labelled "AI-assisted, not independently
  expert-reviewed"; private progress, answers and documents never go into course packages.
- (inferred) The Duolingo-style practice surface is a test version reviewed by the owner before any
  deployment.

## Capabilities and Constraints

- Invite-only; every web page and data endpoint needs a signed-in `/web` session.
- No third-party scripts; the web app runs under a strict same-origin Content Security Policy.
- Personalized AI features use Groq only. Library theory and practice need no runtime AI.
- Free hosting tiers (Vercel Hobby, Supabase Free); schema changes go through a gated release process.
- Undecided: whether practice progress later syncs to the server (it stays on the device in the test version).

## Brand Commitments

- Name: SkillCoach. Calm, direct, honest coaching voice; claims about content review status are explicit.
- The owner asked for a "Duolingo type" practice experience (short gamified lessons, streaks, a learning
  path). Duolingo's own mascot, artwork and trademarks are not used.

## Evidence on Hand

- The bundled curriculum in `skillcoach/course_data/2026-09-29/` (concepts, key terms, end-to-end steps,
  tasks, interview questions and points, storyboards).
- No testimonials, learner counts, outcome statistics or reviews exist; none may be invented.

## Product Principles

1. Understanding over completion: practice checks reasoning and transfer, and progress reflects
   remembered knowledge, not taps.
2. Mistakes are material for learning: they are explained and practiced again, never punished.
3. Honest content: provenance and review status stay visible; hypothetical scenarios are labelled.
4. Private by default: no personal data leaves the device for practice, and nothing is shared publicly.

## Accessibility & Inclusion

- Keyboard and screen-reader operable, visible focus, 44px touch targets, reduced-motion respected,
  light and dark from the device (existing web app standard).
