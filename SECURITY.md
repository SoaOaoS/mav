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
- The web app never exposes the model API key to the browser, and every
  `/api/*` route (except auth, health and hooks) requires a valid session.

## Supported versions

Only the latest release is supported. Run `mav update` to get it.
