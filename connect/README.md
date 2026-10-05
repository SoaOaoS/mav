# Mav Connect (the service)

The cloud side of Mav Connect: encrypted backups today, more services next.
It runs on Cloudflare Workers + R2 — **no server to run or patch**.

Why it can't be bypassed: the licence key is verified *here*, server-side,
with the Ed25519 public key. A modified Mav without a real, unexpired
Connect key gets `401`. Backups arrive already encrypted by Mav (AES-256-GCM,
the key never leaves the user's machine): this service stores unreadable
bytes only.

## Deploy (once, ~5 minutes)

1. A Cloudflare account (free plan is enough to start) and Node.js.
2. Create the bucket and deploy:

   ```bash
   cd connect
   npx wrangler login
   npx wrangler r2 bucket create mav-connect-backups
   npx wrangler deploy
   ```

   It prints the URL, e.g. `https://mav-connect.<you>.workers.dev`
   (or route it to `connect.your-domain.com` in the Cloudflare dashboard).
3. Put that URL in `DEFAULT_CONNECT_URL` in `bot/occonnect.py` and release
   Mav — every install then talks to your service. (`MAV_CONNECT_URL`
   overrides it per machine, e.g. for testing.)

`LICENCE_PUBKEY` in `wrangler.toml` must match `PUBLIC_KEY` in
`dashboard/server/mav_licence.py`. To cut off a licence (refund, abuse), add
its id to `REVOKED` and `npx wrangler deploy` again.

## Cost

R2: 10 GB free, then ~$0.015 per GB-month, no egress fees. Workers: 100k
requests/day free. A Connect user with ~1 GB of backups costs about
**$0.02/month**.

## API

| Method | Path | |
| --- | --- | --- |
| GET | `/v1/status` | plan, `used_bytes`, `quota_bytes`, backups (newest first) |
| PUT | `/v1/backups` | upload one encrypted backup (≤ 95 MB); keeps the newest `KEEP`, within quota |
| GET | `/v1/backups/<id>` | download one |
| DELETE | `/v1/backups/<id>` | delete one |

All calls: `Authorization: Bearer <licence key>`. Tests:
`node --test tests/connect_worker.test.mjs`.
