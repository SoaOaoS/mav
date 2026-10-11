# Mav — roadmap

Where Mav goes next, in order, and how we know each step is done.

Mav already does a lot: chat, helpers, memory, routines, watching, a daily
briefing, notifications, calendars, files, a code sandbox, backups, a hosted
version (MyMav, CloudMav). What stands between Mav and people paying for it
is not one more feature. It is three things, in this order:

1. **It always works.** No lost chat, no silent "offline", no broken tool.
2. **It proves itself in five minutes.** The first session ends with Mav
   already working for you, and something useful arrives the next morning.
3. **It reaches your life without effort.** Mail and calendar in one click,
   answers where you already are.

Everything below serves one of these. Anything that does not is not built.

Effort: **S** ≈ a few days · **M** ≈ 1–2 weeks · **L** ≈ a bigger project.

---

## 0 — Reliability · now

| | What | Effort | Done when |
|---|---|---|---|
| 0.1 | The agent engine is pinned and taken up on purpose (`Dockerfile`, `install.sh`). | S | ✅ A new engine version is a reviewed change, never a surprise. |
| 0.2 | Backups hold the engine's chat database (`opencode.db`), so Mav Cloud's saved state does too. | S | ✅ Chats survive a restart, a deploy and a restore. |
| 0.3 | An end-to-end check against the real hosted stack, every hour: sign in, chat, run a tool, restart, chats still there, a routine fires. | M | 14 days in a row without a failure. |
| 0.4 | The state is saved at the end of each answer, not only on a timer. | S | Stopping a container mid-session loses nothing that was answered. |
| 0.5 | No silent failure: every error says what happened and what to do; a waking Mav says so. | S | No "offline" without an explanation in the app. |

## 1 — The first five minutes · next

| | What | Effort | Done when |
|---|---|---|---|
| 1.1 | Onboarding that sets Mav up: three questions, then Mav creates the daily briefing and two routines that fit, and shows a first result right away. | M | 60 % of new accounts have an active routine after 24 h. |
| 1.2 | Notifications and the installed app are part of onboarding, not a setting to find. | S | 70 % of new accounts allow notifications. |
| 1.3 | "What Mav did for you": a short journal on the home screen (reports, alerts, drafts, routines run). | S | The value of the last 24 h is visible in one glance. |
| 1.4 | Ready-made packs by profile (freelancer, parent, student) in Ideas. | S | Each pack works on first run, with no setting to adjust. |

## 2 — One-click connections

| | What | Effort | Done when |
|---|---|---|---|
| 2.1 | Google (Gmail, Calendar) and Microsoft (Outlook, Calendar) through OAuth, instead of IMAP app passwords and CalDAV. Start Google's app verification early: reading Gmail needs a security assessment. | L | Half of active users have connected an account. |
| 2.2 | Answers where people already are: a Telegram bot first, WhatsApp later. Routines report there; replies go back to Mav. | M | A routine can be followed up without opening the app. |
| 2.3 | Forward an e-mail to Mav to hand it a task. | S | A forwarded mail becomes a chat with Mav's answer. |
| 2.4 | Web browsing in the hosted versions, inside the sandbox. | M | The Researcher can read pages that need a browser, in the cloud too. |
| 2.5 | A catalog of 60+ ready connections (search, knowledge, tasks, team tools, developer tools, data, money, home), each with a step-by-step guide, a cost label and sign-in where the service offers it. No mail for now: it waits for 2.1. | M | ✅ Any listed service is connected in under five minutes without reading outside docs. |

## 3 — Actions people dare to delegate

| | What | Effort | Done when |
|---|---|---|---|
| 3.1 | One "To approve" queue for every sensitive action (send, delete, pay), approvable from the notification, with "always allow this". | M | No sensitive action without an approval or a standing rule. |
| 3.2 | A full history of what Mav did, with undo where it can. | S | Every action is listed with its result. |

## 4 — Answer quality

| | What | Effort | Done when |
|---|---|---|---|
| 4.1 | A set of 50 real tasks per profile, replayed on every release with a score. | M | A prompt, tool or engine change cannot regress silently. |
| 4.2 | CloudMav picks the model by task: the fast one by default, a stronger one for hard tasks, within the plan's budget. | M | Better answers on hard tasks at the same cost per user. |

## 5 — Selling the hosted versions

| | What | Effort | Done when |
|---|---|---|---|
| 5.1 | A 14-day trial without a card, then the subscription. | S | Signing up needs only an e-mail. |
| 5.2 | Founder price and referral (a month for both). | S | Codes and credits applied by Stripe, no manual work. |
| 5.3 | Privacy-friendly product metrics: activation, 4-week retention, trial conversion. No third-party tracker. | S | The three numbers are on one page. |
| 5.4 | Lifecycle e-mails: day 1, day 3, trial end. | S | Sent from the platform, in the person's language. |

## Not now

- New features for the self-hosted version alone: it is the open showcase,
  the hosted versions are the product.
- Family and team accounts in the cloud: when customers ask for them.
- A mail connection through MCP: mail arrives with Google and Microsoft
  sign-in (2.1).

## How each item ships

One pull request per item, with its tests. The item is done when its
"Done when" is true in production, not when the code is merged.
