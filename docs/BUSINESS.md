# Mav — the business

How Mav becomes a company without losing what it is: an open-source, private,
proactive assistant that runs on *your* machine with *your* model.

> Numbers marked *(assumption)* are planning hypotheses to test, not data.
> Replace them with real metrics as soon as they exist (see "What to measure").

---

## YC-style application

**One line.** Mav is the AI assistant that works while you don't — it
remembers you, runs routines on its own and comes to you with what matters,
on your own machine, with the model you choose.

**What it does.** A ChatGPT-style app (web + installable on your phone) on top
of an agent engine. Beyond answering, it acts: a **daily briefing**,
**routines** ("every Friday, check my subscriptions"), **keep an eye on**
(a page, a price, a topic), **memory** of what matters to you, drafts for your
approval, and push notifications only when something deserves it.

**Problem.** Chat assistants are reactive: they wait to be asked, forget you
between chats, and keep your life on someone else's servers. The people who
would benefit most from a proactive assistant — the busy, the privacy-minded,
small teams under GDPR — either don't trust handing it their life or can't
run the plumbing (schedulers, memory, notifications, model keys) themselves.

**Solution.** One command installs a complete, opinionated assistant:
engine, memory (Postgres), scheduler, notifications, a polished app, and a
setup that only asks for a model key. Everything stays local; the model is
interchangeable (Anthropic, OpenAI, OpenRouter, Ollama — fully offline).

**Why now.** (1) Models became good enough at tool use to *act*, not just
talk; (2) costs per token fell ~10× in two years, making always-on routines
affordable; (3) local models (Ollama) make a private assistant real;
(4) agent engines (opencode) and the MCP standard let one product plug into
any service.

**Insight / secret.** Proactivity is a *ranking* problem, not a generation
problem: the value is in deciding what deserves an interruption. Mav's
priority levels, quiet hours, digests and briefing are built around that —
and they compound with memory, which makes switching costly.

**Who it's for (first).**
1. Privacy-minded power users and self-hosters (Home Assistant, homelab,
   Tailscale crowd) — reachable, vocal, willing to pay for software they run.
2. Freelancers and very small businesses that want an assistant on their own
   server for confidentiality (lawyers, accountants, health) *(next)*.
3. Everyone else, through **Mav Cloud** (hosted, no server) *(later)*.

**Competition.** ChatGPT / Claude / Gemini apps (reactive, cloud-only, but
dominant); Open WebUI, LibreChat, AnythingLLM (self-hosted *chat* UIs, not
proactive); Lindy, Zapier agents (cloud automation, no privacy story);
Home Assistant (home only). Mav sits alone at *proactive × private × any
model*.

**Moat.** Memory and routines accumulate (switching cost); an open-source
community and a catalog of routines/connections (distribution); trust
(offline licence, no telemetry) that cloud incumbents can't credibly copy.

---

## Business model

Open core, with nothing ever switched off:

| Plan | Price | For |
| --- | --- | --- |
| **Free** (self-hosted) | $0 | Everything; 5 active routines, 5 watches |
| **Pro** (self-hosted) | $8/month or **$79/year** | Unlimited routines and watches, priority support, early features |
| **Cloud** (hosted) | $15/month or $149/year *(waitlist)* | Pro, hosted for you: private instance, updates, backups |
| **Team** *(later)* | ~$20/user/month | Shared spaces, roles, SSO, audit — on their server or EU cloud |

Why these limits: routines and watches are what *runs on its own* — the
proactive core. Free users get the full experience and hit the limit exactly
when Mav has proven its value (their sixth routine). The briefing, memory and
chat stay free: they create the habit.

Licence keys are signed (Ed25519) and verified offline
(`dashboard/server/mav_licence.py`): no account server, no call home — the
privacy promise holds for paying users too.

### The path to $10M ARR *(assumptions)*

| Lever | Year 1 | Year 2 | Year 3 |
| --- | --- | --- | --- |
| Active installs | 15k | 60k | 150k |
| Free → Pro conversion | 3 % | 4 % | 5 % |
| Pro subscribers × $79 | 450 → $36k | 2.4k → $190k | 7.5k → $590k |
| Cloud subscribers × $149 | — | 4k → $600k | 25k → $3.7M |
| Team seats × $240 | — | 500 → $120k | 24k → $5.8M |
| **ARR** | **~$36k** | **~$0.9M** | **~$10M** |

The self-hosted plans fund the project and build the community; **Cloud and
Team are where $10M comes from**. Self-hosting is the trust engine and the
top of the funnel for both.

### Unit economics *(assumptions)*

- Pro: near-100 % gross margin (no hosting; the user's own model key).
- Cloud: ~$2–4/month hosting per user (a small isolated instance + Postgres)
  → ~75 % gross margin at $15; model costs stay on the user's key, or are
  resold with a margin as an option.
- Acquisition: open source + content (routines gallery, "what Mav did for me
  this week") + communities (r/selfhosted, Home Assistant, Hacker News).
  Target CAC < $30 for Cloud, payback < 3 months.

---

## Go-to-market

1. **Launch** on Hacker News ("Show HN: a proactive AI assistant you run
   yourself"), r/selfhosted, r/LocalLLaMA, Home Assistant forums. The demo:
   one command, then the first morning briefing.
2. **Routines gallery** — shareable routines ("weekly meal plan", "price
   watch", "Friday money check") as the growth loop.
3. **Integrations people search for** — Gmail/Outlook, calendar, Notion, Home
   Assistant, bank exports; each one is a landing page.
4. **Cloud waitlist** → paid beta → general availability.
5. **Team** for small regulated businesses (EU, GDPR): sold on "your server,
   your data".

---

## What to measure

- Activation: % of installs that connect a model and receive a first
  briefing within 24 h.
- Habit: % of users opening a briefing 5 days out of 7 (week 4).
- Proactive depth: routines + watches per active user; % hitting the Free
  limit.
- Conversion: limit-hit → "See Pro" click → licence activated.
- Cost: median monthly model spend per user (Settings → Usage) — the lower,
  the easier the yes.
- Retention: monthly churn of Pro and Cloud.

Mav itself sends no telemetry. These are measured through opt-in surveys,
download/release stats, the store, and Cloud (where the instance is ours).

---

## Product roadmap

**Shipped (this cycle).** Password sign-in; daily briefing; usage, cost and
budget with a cheap background model; Free/Pro plans with offline licence
keys; pricing page.

**Next 3 months.**
- Mail + calendar connectors with drafts for approval (the "needs you"
  section of the briefing gets real).
- Routines gallery: share and install routines in one click.
- Secure remote access built in (tunnel), so the phone app works anywhere.
- Encrypted automatic backups (Pro).

**3–6 months.**
- **Mav Cloud** beta: one isolated instance per user, same open code.
- Family: one Mav per person + a shared space (shopping, planning).
- Native mobile app (notifications on iOS without the PWA limits).

**6–12 months.**
- **Team**: shared workspaces, roles, SSO, audit log; EU hosting.
- Marketplace for routines/helpers with revenue share.

---

## Taking payments (operations)

1. Create a store on a merchant of record (Lemon Squeezy or Paddle handle VAT
   worldwide) with two products: *Mav Pro — yearly* ($79) and *monthly* ($8).
2. Generate the signing key once and keep it secret (password manager +
   offline copy):

   ```bash
   scripts/licence-tool.py keygen --out mav-licence-private.key
   ```

   Put the printed public key in `PUBLIC_KEY` of
   `dashboard/server/mav_licence.py` and release.
3. On "order paid", issue the key and email it — by hand at first:

   ```bash
   scripts/licence-tool.py issue --key mav-licence-private.key \
     --email customer@example.com --plan pro --days 365
   ```

   then automatically from the store's webhook (a tiny serverless function
   calling the same `mav_licence.sign`).
4. Point the buttons at the store: `BUY_URL` in `docs/pricing.js` and
   `MAV_CHECKOUT_URL` (default: the pricing page) for the app's *Go Pro*.

Until then, the buttons open a GitHub issue so early supporters can still
reach you.

---

## Risks

- **Incumbents ship proactivity** (ChatGPT tasks/pulse). → Stay where they
  can't: local, any model, open, no data leaving the home.
- **Self-hosting caps the market.** → Cloud and Team; keep the install to one
  command and a model key.
- **Model costs for always-on routines.** → Usage tab, budgets, cheap
  background model, local models.
- **Open source cannibalises Pro.** → Price for goodwill ($79/year), keep the
  limits on the proactive core, make Cloud the real product.
