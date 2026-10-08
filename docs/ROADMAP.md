# Mav — implementation roadmap

What to build next, in order, and how to know each step is done. The order
favours what makes people **install Mav and keep it**: easier install, a faster
first "wow", a snappier assistant. Then come the features they will ask for,
and the work that keeps the codebase healthy.

[`PLAN.md`](PLAN.md) is the long feature backlog (in French). This file is the
plan: what we do now, in which order, and what "done" means.

Effort: **S** ≈ a few days · **M** ≈ 1–2 weeks · **L** ≈ a bigger project.

---

## Phase 1 — Remove adoption blockers (weeks 1–2) · ✅ done

The product is feature-complete. What stops new users today is getting it
running, and seeing its value in the first minutes.

### 1.1 Docker Compose install · M · ✅ done

> **Shipped:** `Dockerfile`, `docker-compose.yml`, `.env.example` and `docker/entrypoint.sh`. The image is built and pushed to GHCR with each release, and CI runs the whole stack. Restarts from the web app go through a flag file the engine and worker containers watch. The update button explains `docker compose pull`.

**Why.** Self-hosters expect `docker compose up`. Today the installer targets
Debian/Ubuntu and Arch with systemd. Docker only runs Postgres.

**Scope**
- A `Dockerfile` for the web app and the worker (one image, two commands) and
  one for the opencode engine.
- `docker-compose.yml` at the repo root, with four services: `engine`,
  `worker`, `web` and `postgres`. Named volumes for data, memory and settings.
- `.env.example` for the model provider, the API key, the port and the
  password.
- Health checks, and `restart: unless-stopped`.
- The release workflow publishes multi-arch images (`amd64`, `arm64`) to GHCR,
  tagged `vX.Y.Z` and `latest`.
- In the app, the update button and the restart button work under Docker:
  they detect it and explain `docker compose pull && up -d` instead of
  calling systemd.

**Done when**
- `git clone … && cp .env.example .env && docker compose up -d` gives a
  working Mav at `http://localhost:8787`. Data survives `down`/`up`.
- CI builds the images and runs the test suite against the Compose stack.
- README: "Install with Docker" comes first, the one-line installer second.

### 1.2 Mav can send you files in the chat · S · ✅ done

> **Shipped:** helpers can write in `mav-files/` only (`permission.edit`), and their answers carry `[[file:name]]` download cards. Shared files are also archived in the media index.

**Why.** Users want Mav to hand them documents: a CSV budget, a Markdown
plan, a letter. The app already renders `[[file:name]]` as a download card,
and `/api/download` serves files from allowed folders. The helpers just can't
write files, and don't know about the card.

**Scope**
- A dedicated output folder (`BOT_DIR/mav-files`), added to the download roots.
- Let Assistant, Writer, Planner and Money write files there only: the
  `edit`/`write` permission, scoped to that path.
- Add a short "Sharing files" section to `agents/assistant.md` and the
  helpers: write the file to the folder, then put `[[file:<name>]]` on its own
  line. Regenerate `agents/shipped.sha256`.
- Archive each new file in the media index, so it can be found again later.

**Done when**
- "Make me a CSV of my subscriptions" gives a download card, and the file
  opens.
- A test proves that a path outside the allowed folders is refused, so a
  helper can't write or expose anything elsewhere.

### 1.3 First-run onboarding · M · ✅ done

> **Shipped:** a 3-step welcome (model, about you, routines) that ends on *Brief me now*. Routine templates are now in English, with French kept. Browser test: `tests/test_e2e_onboarding.py`.

**Why.** A fresh install opens on an empty chat. People should feel Mav's
value within 5 minutes.

**Scope**
- A 3-step welcome flow on first login:
  1. **Connect a model**: pick a provider, then test it. This already exists in
     Settings; reuse it here.
  2. **About you**: city, language, a few interests. These become memory
     facts and settings for the briefing.
  3. **Pick 2–3 routines** from the templates, with the morning briefing ticked
     by default.
- It ends on "Brief me now", so the first briefing arrives right away.
- The flow can be skipped, and reopened from Settings.

**Done when**
- From a fresh install, a new user gets a first briefing and has routines in
  under 5 minutes, without opening Settings.
- A Playwright test walks through the flow against the fake engine.

### 1.4 Public live demo · S · ✅ done

> **Shipped:** <https://soaoaos.github.io/mav/demo/>, a copy built by `scripts/build-demo.sh` and checked by CI.

**Why.** Let people try Mav before they install it.

**Scope**
- Polish the existing demo mode (the app without a server). It needs sample
  chats, routines and memory that match the screenshots, plus a "Demo"
  banner with an install link.
- Publish it on GitHub Pages at `/mav/demo/`, and link it from the README and
  the website.

**Done when**
- The demo link opens a browsable Mav with realistic data, on desktop and on
  mobile.

---

## Phase 2 — Faster and stickier (weeks 3–6) · ✅ done

### 2.1 Speed: measure, then trim · M · ✅ done

> **Shipped:**
> - **Measured:** each answer shows its time to first word, total time, steps and prompt size (with the cached share), and *Settings → Usage → Speed* shows the medians.
> - **Trimmed:** each helper only receives the tools it uses. The prompt sent per turn, measured against the real engine with `dashboard/tools/fake_openai.py`, went from 25.3 KB to 13.6 KB for the Assistant (−47 %) and from 23.3 KB to 7.4 KB for the four helpers (−68 to −69 %). Tool definitions were 85 % of it.
> - **Cached:** memory is added after the system prompt and the tools, so that start of the prompt stays stable for provider caching.
>
> Time to first word on a local model scales with the prompt size. The Speed card is how to check the 40 % target on real hardware.

**Why.** Most of the waiting is the model reading a long prompt (instructions
and tool definitions) and taking extra steps. This is very visible on local
models.

**Scope**
- **Measure.** For each answer, record the time to first token, the total
  time, the tokens sent and the number of steps. Show them in Usage and in
  the tool inspector.
- **Trim.** Shorten the helpers' instructions. Give each helper only the
  tools it needs, and only the MCP servers that helper uses. Reply directly
  to simple questions, without delegating.
- **Cache.** Keep the start of the prompt stable so that provider prompt
  caching applies.

**Done when**
- The median time to first token on a simple question drops by at least 40%
  on a local model, measured before and after on the same machine. The
  numbers go in the PR.

### 2.2 More ways to reach you · S · ✅ done

> **Shipped:** `bot/occhannels.py`: ntfy, Gotify, Discord and Slack in Settings → General, each with a test button. Routines can pick their channels. Tests: `tests/test_channels.py`.

**Why.** Homelab users already run ntfy, Gotify or Discord.

**Scope**
- Notification channels next to Web Push: **ntfy**, **Gotify**, and a
  **Discord / Slack webhook**. Configured in Settings → General, with a
  "Send test" button.
- Each routine and each alert uses the user's chosen channels. The
  proactivity level still applies.

**Done when**
- A routine report reaches ntfy and Discord, and the tests cover each
  channel's payload.

### 2.3 Calendar · M · ✅ done

> **Shipped:**
> - `bot/occalendar.py`: CalDAV (discovery, with the server expanding recurring events) and private iCal links (Google, Outlook…), which replace the planned Google-through-MCP and need no extra connection.
> - Today's events are in the briefing.
> - A new routine trigger, "N minutes before an event", with an optional word filter. Each one fires once, even across restarts.
> - Tests (`tests/test_calendar.py`) run against a fake CalDAV server.
>
> This work also found and fixed two existing bugs: monthly routines created in the app were saved as daily ones, and event routines could not be created from the app.

**Why.** The briefing and the weekly review are much better when Mav knows
your day. Calendar data is also the first trigger that isn't based on a
clock time.

**Scope**
- CalDAV (Nextcloud, iCloud, Fastmail…), plus Google Calendar through MCP.
- The briefing lists today's events. A new routine trigger, "N minutes
  before an event", adds reminders with context.

**Done when**
- The briefing shows today's events from a CalDAV test server, and a
  "15 min before" routine fires on time.

### 2.4 RSS and more watchers · S · ✅ done

> **Shipped:** feeds (RSS/Atom) and GitHub releases in *Keep an eye on*, with an optional "only if it mentions…". New items are grouped into one alert. Tests: `tests/test_feeds.py`.

**Scope**
- "Keep an eye on" gains **RSS/Atom feeds** (new items only, summarised) and
  **GitHub releases**.
- Each watcher can have a condition ("only if it mentions X").

**Done when**
- A feed with 3 new items gives one grouped alert, not three.

### 2.5 Family accounts · L · ✅ done

> **Shipped:**
> - **Accounts.** The owner adds people in Settings → General → Family. Each person signs in with their name and password. Every account has its own sessions, and changing one person's password signs out only that person.
> - **Isolation.** Chats, memory (facts and past exchanges), routines, watch items, notifications, push devices, proactivity and the welcome flow are kept per person.
>   - Someone else's chat is "not found".
>   - Each person's routines run with their own memory and notify their own devices.
> - **What stays the owner's** (members never reach it; the API checks an allow-list): the model, connections, helpers, email, interests, calendars, channels, usage, backup and updates.
> - **Removing a person** also erases their data.
> - **Tests.** `tests/test_family.py` proves two accounts never see each other's chats, memory or routines, over HTTP and Postgres. `tests/test_e2e_family.py` runs the same check in the browser.
> - **Known limit:** files the assistant writes live in one shared workspace.

**Why.** One server, several people: each with their own chats, memory and
routines.

**Scope**
- Users table, per-user sessions and data isolation in Postgres and the
  engine's sessions.
- An admin creates accounts.
- Shared "household" routines are optional.

**Done when**
- Two accounts on one instance never see each other's chats, memory or
  routines, and a test proves it.

---

## Phase 3 — Codebase health (ongoing, alongside) · ✅ done

### 3.1 Split the big files · M · ✅ done

> **Shipped:**
> - **Server:** `mav_api.py` (5,212 lines) became eight modules, from 411 to 1,025 lines each: core, engine, routines, store, chat, stream, media, and the HTTP handler. The split was done by a tool, so no logic was rewritten: every name has one owner, references across modules are qualified, and `mav_api` forwards reads and writes to the owner. The 219 existing tests pass unchanged.
> - **Web app:** `app.js` (6,842 lines) became 12 classic scripts, from 255 to 1,049 lines each, that share one scope, with no bundler.

`dashboard/server/mav_api.py` (~4,800 lines) and `dashboard/assets/js/app.js`
(~6,000 lines) do too much. Split them by area, with no change in behaviour:

- **Server**: `auth`, `chat` (sessions, stream, runs), `routines`, `watch`,
  `memory`, `settings`/`providers`, `mcp`, `media`, `push`, `usage`. Plus a
  small router.
- **Web app**: one ES module per view (chat, routines, memory, settings) plus
  `api`, `state`, `markdown` and `ui`, without a bundler.

**Done when** the existing tests pass unchanged and no file is over ~1,200
lines.

### 3.2 End-to-end tests in CI · S · ✅ done

> **Shipped:** `tests/test_e2e_app.py` and `tests/test_e2e_onboarding.py` run in Chromium on every pull request, with a shared set-up in `tests/e2e_support.py`. They found and fixed a reload on first visit that wiped the sign-in form.

A Playwright suite against the fake engine on every pull request:
- sign in;
- send a message and see the tool steps;
- create a routine;
- reload a chat and keep its history;
- open the mobile layout.

### 3.3 Raspberry Pi / ARM · S · ✅ done

> **Shipped:**
> - CI runs the whole Docker stack and the installer checks on a native arm64 runner, as well as on x86.
> - At rest, the stack measured 365 MB of memory on arm64.
> - The docs have a Raspberry Pi section: which system, an SSD, and which model on which Pi.

- Test the installer and the Docker images on `arm64`, the Raspberry Pi 5
  included.
- Document which models run well locally on that hardware.

### 3.4 Backup and restore in the app · S · ✅ done

> **Shipped:** `dashboard/server/mav_backup.py`, under Settings → General → Backup. It covers the database (through psycopg2, so Docker and the installer work the same), files and chats. A restore asks for the password again, checks every entry and keeps a safety copy. Tests: `tests/test_backup.py`, with a real Postgres in CI.

The `mav backup` command already exists. Add an in-app screen to download a
backup and restore one, with a confirmation step.

---

## Phase 4 — Optional: a hosted Mav

Only if Mav goes commercial. A managed instance per user for people who want
Mav without running a server:
- one Compose stack per tenant, behind a reverse proxy;
- automatic backups;
- billing.

Phase 1.1 (Docker) is the foundation for this.

> **Status:** not started on purpose. Phases 1–3 are done; this phase only
> makes sense once there is demand for a paid, hosted Mav. The ground work
> is in place: one image, one data volume, backup and restore, and accounts.

---

## Order at a glance

| Week | Work |
| --- | --- |
| 1 | 1.1 Docker Compose · 1.2 file sharing |
| 2 | 1.3 onboarding · 1.4 public demo · launch (r/selfhosted, Show HN) |
| 3 | 2.1 speed (measure, then trim) · 3.2 end-to-end tests |
| 4 | 2.2 ntfy/Gotify/Discord · 2.4 RSS watchers |
| 5–6 | 2.3 calendar · 3.1 split the big files |
| later | 2.5 family accounts · 3.3 ARM · 3.4 backup UI · Phase 4 if commercial |

After the launch, let feedback reorder Phase 2: build first what the first
users ask for most.

## How each item ships

- **One pull request per item**, with a Conventional Commit title (`feat:`,
  `fix:`…), so the release workflow picks the right version bump.
- **Each pull request includes:**
  - tests: unit tests, plus an end-to-end test once 3.2 exists;
  - docs: README or `dashboard/README.md`;
  - for anything visible, a screenshot.
- **Before it merges**, CI must pass: shellcheck, syntax checks and the tests.
