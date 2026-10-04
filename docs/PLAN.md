# Mav — plan: an everyday assistant that is proactive and runs on your own machine

**Positioning.** Mav is a general-purpose personal assistant, like ChatGPT but
agentic and proactive: it remembers you, runs routines on its own, keeps an eye
on things and comes to you with what matters. It runs on your machine, with the
model you choose. It can help with specialist tasks through tools
(connections), but nothing in the product is built around a niche use case.

## Audit (before)

| Area | Problem |
| --- | --- |
| Memory | The bot wrote exchanges to `memory.json`; the dashboard read Postgres tables nothing ever wrote to. Dashboard chats were never remembered. |
| Model | Changing provider/model meant re-running the terminal wizard. |
| Installer | ~35 free-text questions, no validation, chat id to find by hand, noisy output. |
| Focus | Telegram bot, Proxmox/infra page, market charts, stock watcher, dev-centric agents: a power-user toolbox rather than an everyday assistant. |
| Chat | Agent hidden in a dropdown, not tied to the chat, not shown on answers; titles = first 48 characters. |
| Jobs | "Run" in the dashboard created an empty session and never ran the job; no way to create one from the UI. |

## What was done

### 1. Removed (code, UI, installer, env vars, docs)
- Telegram bot → replaced by `mav-worker` (routines + keep an eye on + push).
- Proxmox / Infra page and `/api/proxmox`, `PROXMOX_*`, the Proxmox watch kind.
- Specialist watch kinds (GitHub, service health, Moodle, mail) and the stock
  watcher; `/api/quotes`, `/api/chart`, `[[chart:…]]`, lightweight-charts.
- `dev`, `reviewer`, `ops` agents and `examples/biotech_brief.py`.

### 2. ChatGPT-like
- Chat is the main screen; sidebar = New chat, chats grouped by day
  (auto-titled), and Routines · Memory · Settings.
- New-chat screen = greeting, centred composer, 4 everyday suggestions, and the
  proactive *For you* inbox.
- Plain language: Assistant, Helpers, Connections, Custom instructions,
  Restart assistant; technical details in Settings → General → Advanced.
- Who you talk to is shown on the composer, the header and each answer, and
  remembered per chat.
- Helpers: Assistant (default orchestrator), Researcher, Writer, Planner, Money.
- Dark mode, ⌘K palette, keyboard shortcuts, copy/regenerate, PWA.

### 3. Agentic and proactive
- **Routines**: simple form (what / when: every day, some days, every few
  hours / which helper), `/routine`, and detection of "every morning…" in chat
  with a *Create routine* confirm card. Each routine has its own chat; results
  go to push + the inbox.
- **Keep an eye on**: a page, a price (optionally below a target), a news topic.
- **Memory** like ChatGPT's, on Postgres: facts + past exchanges, recalled in
  new chats and routines, Memory page, `/remember`.

### 4. Installer
- Asks only for the provider, the key (checked live), the model (from the
  provider's list, or "set it up later"), and optionally an email.
- Arrow-key menus, numbered steps, spinner, `/var/log/mav-install.log`,
  *Advanced settings?* for the rest. Existing installs: Update / Change the
  model / Reconfigure / Uninstall, with migration from the Telegram version.
- Provider logic shared with the web app (`dashboard/server/mav_provider.py`).

## Next
- Optional login for the web app (today: home network or VPN only).
- Automatic fact extraction from chats (today: the Assistant suggests
  `/remember`; facts are added explicitly).
- Embedding-based recall (pgvector) on top of full-text search.
- Natural-language routine detection in more languages (today: English).
