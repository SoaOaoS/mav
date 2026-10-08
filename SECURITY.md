# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's
[private vulnerability reporting](https://github.com/SoaOaoS/mav/security/advisories/new)
instead: it starts a private advisory only you and the maintainer can see.

You can expect an acknowledgement within a few days, an assessment of the
impact, and a fix or a mitigation plan. Credit is given in the advisory unless
you prefer to stay anonymous.

## Scope

Mav runs on your own machine and holds your data (memory, routines, mail
drafts) behind a password-protected web app. The most valuable reports are:

- authentication or session bypass of the web app (`dashboard/server/mav_auth.py`);
- reading or writing files outside the intended directories through the
  dashboard API (`/api/download`, `/api/asset`, `/api/upload`);
- command or prompt injection that escapes the agent's sandbox;
- secret leaks in the installer, the update path or the logs.

## What we already do

- **CodeQL** static analysis and **OpenSSF Scorecard** run on every push to
  `main` (see `.github/workflows/`); findings show in
  [Security → Code scanning](https://github.com/SoaOaoS/mav/security/code-scanning).
- **Secret scanning** and push protection are enabled on the repository.
- **Sessions.** Every `/api/*` route needs a valid session, except sign-in,
  health and webhooks. Sessions are HMAC-signed cookies: HttpOnly,
  SameSite=Lax, and `Secure` over HTTPS. Passwords are stored as salted
  PBKDF2-SHA256 hashes, and repeated wrong guesses are slowed down.
- **Requests from other sites.** A browser request sent from another site is
  refused (`Sec-Fetch-Site` and `Origin` are checked), so a link or a form
  elsewhere cannot start an answer or change anything.
- **Pages.** Every page carries a strict Content-Security-Policy: no inline
  script, no `eval`, and the app cannot be framed. `/api/download` and
  `/api/asset` serve only the folders meant for files, never Mav's own data
  folder (routines, sign-in, channel and calendar secrets, backups).
  Request bodies are capped.
- **The engine.** The agent engine has its own generated password
  (`OPENCODE_SERVER_PASSWORD`). Only Mav's services can talk to it, not the
  assistant's own web fetch.
- **Webhooks.** A webhook needs its token (Settings → General → Webhook).
- **Family accounts.** Members reach only an allow-list of routes, and
  someone else's chat is "not found". A member's watch items may only fetch
  the public internet. The model API key never reaches the browser.

### Trust model

Family accounts keep each person's chats, memory and routines apart in the
app. Members share one assistant engine, which runs on your machine with
your user's rights, and one workspace for the files it writes. A member who
deliberately instructs the assistant's tools to read files on the machine is
outside what accounts can contain: give accounts to people you would trust
with that machine.

## Supported versions

Only the latest release is supported. Run `mav update` to get it.
