/*
 * Mav Connect — encrypted cloud backup service (Cloudflare Worker + R2).
 *
 * Every request carries a Mav licence key (Authorization: Bearer MAV1.…).
 * The key is verified HERE, server-side, with the Ed25519 public key: a
 * patched Mav cannot use the service without a real, unexpired key. Backups
 * arrive already encrypted by Mav (AES-256-GCM, key never sent): this
 * service only ever stores unreadable bytes.
 *
 *   GET    /v1/status          plan, quota, backups list
 *   PUT    /v1/backups         upload one encrypted backup (body = bytes)
 *   GET    /v1/backups/:id     download one
 *   DELETE /v1/backups/:id     delete one
 *
 * Config (wrangler.toml): LICENCE_PUBKEY (Ed25519, raw, base64url),
 * QUOTA_BYTES, KEEP (backups kept per licence), REVOKED (comma-separated
 * licence ids), and the R2 bucket binding BACKUPS.
 */

const PREFIX = "MAV1";
const PLANS_WITH_BACKUP = new Set(["connect", "business", "pro"]);
const MAX_UPLOAD = 95 * 1024 * 1024; // Workers accept bodies up to 100 MB

const b64uDecode = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};
const b64uEncode = (bytes) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

/** Verify a licence key; returns its payload or throws with a reason. */
export async function verifyLicence(key, publicKeyB64, now = Date.now() / 1000, revoked = "") {
  const parts = String(key || "").trim().split(".");
  if (parts.length !== 3 || parts[0] !== PREFIX) throw new Error("not a Mav licence key");
  const sig = b64uDecode(parts[2]);
  if (b64uEncode(sig) !== parts[2]) throw new Error("invalid signature");
  const pub = await crypto.subtle.importKey("raw", b64uDecode(publicKeyB64), { name: "Ed25519" }, false, ["verify"]);
  const ok = await crypto.subtle.verify({ name: "Ed25519" }, pub, sig, new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!ok) throw new Error("invalid signature");
  const payload = JSON.parse(new TextDecoder().decode(b64uDecode(parts[1])));
  if (payload.exp && payload.exp < now) throw new Error("licence expired");
  if (!PLANS_WITH_BACKUP.has(payload.plan)) throw new Error("this plan does not include cloud backup");
  const id = String(payload.id || "");
  if (!/^[A-Za-z0-9_-]{4,64}$/.test(id)) throw new Error("licence has no valid id");
  if (String(revoked || "").split(",").map((x) => x.trim()).includes(id)) throw new Error("licence revoked");
  return payload;
}

async function listBackups(bucket, id) {
  const out = [];
  let cursor;
  do {
    const page = await bucket.list({ prefix: `${id}/`, cursor });
    for (const o of page.objects) out.push({ id: o.key.slice(id.length + 1), size: o.size, at: o.uploaded });
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  out.sort((a, b) => (a.id < b.id ? 1 : -1)); // newest first (ids are timestamps)
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/health") return json(200, { ok: true, service: "mav-connect" });

    let licence;
    try {
      const auth = request.headers.get("authorization") || "";
      licence = await verifyLicence(auth.replace(/^Bearer\s+/i, ""), env.LICENCE_PUBKEY, Date.now() / 1000, env.REVOKED);
    } catch (e) {
      return json(401, { error: String(e.message || e) });
    }
    const id = licence.id;
    const quota = Number(env.QUOTA_BYTES || 2 * 1024 ** 3);
    const keep = Number(env.KEEP || 14);
    const bucket = env.BACKUPS;

    if (url.pathname === "/v1/status" && request.method === "GET") {
      const backups = await listBackups(bucket, id);
      const used = backups.reduce((n, b) => n + b.size, 0);
      return json(200, { plan: licence.plan, email: licence.email || "", used_bytes: used, quota_bytes: quota, keep, backups });
    }

    if (url.pathname === "/v1/backups" && request.method === "PUT") {
      const size = Number(request.headers.get("content-length") || 0);
      if (!size) return json(411, { error: "content-length required" });
      if (size > MAX_UPLOAD) return json(413, { error: "backup too large" });
      const before = await listBackups(bucket, id);
      // Rotation first: the oldest go when over the count, then while over quota.
      const doomed = before.slice(keep - 1);
      let used = before.slice(0, keep - 1).reduce((n, b) => n + b.size, 0);
      const kept = before.slice(0, keep - 1);
      while (kept.length && used + size > quota) {
        const b = kept.pop();
        doomed.push(b);
        used -= b.size;
      }
      if (used + size > quota) return json(413, { error: "over quota" });
      const name = `${new Date().toISOString().replace(/[:.]/g, "-")}.mavbak`;
      await bucket.put(`${id}/${name}`, request.body, { httpMetadata: { contentType: "application/octet-stream" } });
      for (const b of doomed) await bucket.delete(`${id}/${b.id}`);
      return json(201, { ok: true, id: name, size, removed: doomed.map((b) => b.id) });
    }

    const m = url.pathname.match(/^\/v1\/backups\/([A-Za-z0-9_.-]+\.mavbak)$/);
    if (m && request.method === "GET") {
      const obj = await bucket.get(`${id}/${m[1]}`);
      if (!obj) return json(404, { error: "not found" });
      return new Response(obj.body, { headers: { "content-type": "application/octet-stream" } });
    }
    if (m && request.method === "DELETE") {
      await bucket.delete(`${id}/${m[1]}`);
      return json(200, { ok: true });
    }
    return json(404, { error: "not found" });
  },
};
