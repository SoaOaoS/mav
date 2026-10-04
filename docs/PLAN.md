# Mav — usability & efficiency plan

Goal: make Mav faster to install, configurable entirely from the dashboard, and
obvious to use day to day (which agent am I talking to, what is this chat
about, what does Mav remember).

## Findings (audit)

| Area | Problem |
| --- | --- |
| Memory | The bot stored exchanges in `~/bot/memory.json`; the dashboard read the Postgres `conversations` / `facts` tables, which **nothing ever wrote to**. Dashboard chats were never remembered at all. |
| Provider | Changing model/provider meant re-running the terminal wizard. The provider logic lived as inline Python inside `install.sh`. |
| Wizard | ~35 sequential free-text prompts, no validation (bad Telegram token / API key only discovered after the install), chat id had to be found by hand, noisy output. |
| Agents | Agent chosen in a small dropdown, not tied to the conversation, not shown on the answers. |
| Conversations | Titles were the first 48 characters of the first message. |
| Automations | "Run" on the dashboard created an empty session and never ran the job. Jobs could not be created from the UI. |
| Bot | `/rag` crashed (`time` not imported); messages still in French. |

## Plan

### 1. Memory on Postgres (bug fix)
- `ocmemory.py` rewritten: Postgres-backed (`conversations`, `facts`), JSON file
  kept only as a fallback when Postgres is unreachable.
- One-time migration of an existing `memory.json` into Postgres.
- Retrieval: Postgres full-text search + recency decay, durable **facts** always
  injected first.
- Dashboard conversations are stored too (same tables, `source = 'dashboard'`).
- New bot command `/remember <fact>`; dashboard Memories page can add / delete
  facts and forget exchanges.

### 2. Provider & model from the UI
- New module `dashboard/server/mav_provider.py`: single source of truth for
  provider presets and for writing `opencode.json` + engine env. Used by the
  installer *and* by the dashboard.
- API: `GET /api/config/provider`, `POST /api/config/provider/test` (live
  connection test + model list), `POST /api/config/provider` (save, apply,
  restart engine and bot).
- Settings → **Model** tab: provider cards, key field, "Test connection",
  model picker filled from the provider, one-click "Save & apply".

### 3. Installer wizard (Claude Code-style)
- Arrow-key menus with descriptions, numbered steps (`Step 2 of 4`), masked
  secrets, inline validation.
- Telegram token validated live (`getMe`); **chat id detected automatically**
  by asking the user to send a message to the bot.
- Provider key tested live, model picked from the provider's own list; or
  "configure later from the dashboard".
- Express by default: only the essentials are asked; everything else has smart
  defaults behind an "Advanced settings?" prompt.
- Install steps run behind a spinner with a log file (`/var/log/mav-install.log`)
  instead of a wall of apt/pip output.

### 4. Chat UX
- Agent identity everywhere: coloured avatar + name in the header, on every
  answer, and in the conversation list; agent remembered **per conversation**;
  a divider when you switch agent mid-chat; agent descriptions in the picker.
- **Auto-generated titles**: after the first exchange a short 2–5 word title is
  generated in the background (keyword fallback if the model is unavailable).
- Conversations grouped by day, filterable, with relative times.
- Multi-line composer (Enter = send, Shift+Enter = new line, auto-grow).
- Message actions: copy, regenerate; copy button on code blocks.
- Slash commands in the composer: `/new`, `/agent <name>`, `/remember <fact>`,
  `/export`, `/help`.
- Shortcuts: `⌘/Ctrl K` palette, `/` focus composer, `Esc` stop/close.
- Dark mode (auto + manual toggle).

### 5. Pages
- **Home**: real activity feed (notifications + job runs), "start with an agent"
  shortcuts, onboarding banner when no model is configured.
- **Automations**: create / edit / delete jobs, working "Run now" (result shows
  up in Job results), last-run info.
- **Memories**: Facts / Exchanges / Preferences tabs, add & delete.
- **Watch**: all kinds available (incl. stock) with a hint per kind.
- **Settings**: Model · Agents · Instructions (AGENTS.md) · MCP · Engine.

### 6. Telegram bot
- English messages, agent name shown in the progress line, `/agent` with
  inline buttons, `/remember`, `/rag` crash fixed.

## Out of scope / next
- Authentication on the dashboard (still meant for a VPN / private host).
- Embedding-based memory (pgvector) — the schema leaves room for it.
- Streaming tool steps in the dashboard (currently final text only).
