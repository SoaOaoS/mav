// Mav Connect worker: licence checked server-side, rotation, quota.
// Run: node --test tests/connect_worker.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { verifyLicence } from "../connect/worker.js";

const enc = (bytes) =>
  Buffer.from(bytes).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function signer() {
  const k = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const pub = enc(new Uint8Array(await crypto.subtle.exportKey("raw", k.publicKey)));
  const sign = async (payload) => {
    const body = enc(new TextEncoder().encode(JSON.stringify(payload)));
    const sig = await crypto.subtle.sign({ name: "Ed25519" }, k.privateKey, new TextEncoder().encode(`MAV1.${body}`));
    return `MAV1.${body}.${enc(new Uint8Array(sig))}`;
  };
  return { pub, sign };
}

// Minimal in-memory R2.
function bucket() {
  const store = new Map();
  return {
    store,
    async list({ prefix }) {
      const objects = [...store.entries()]
        .filter(([k]) => k.startsWith(prefix))
        .map(([key, v]) => ({ key, size: v.length, uploaded: new Date() }));
      return { objects, truncated: false };
    },
    async put(key, body) {
      store.set(key, new Uint8Array(await new Response(body).arrayBuffer()));
    },
    async get(key) {
      const v = store.get(key);
      return v ? { body: v } : null;
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

const req = (method, path, key, body) =>
  new Request(`https://connect.test${path}`, {
    method,
    headers: { authorization: `Bearer ${key}`, ...(body ? { "content-length": String(body.length) } : {}) },
    body,
  });

test("licence is verified server-side", async () => {
  const { pub, sign } = await signer();
  const good = await sign({ plan: "connect", id: "abc123", email: "a@b.c" });
  assert.equal((await verifyLicence(good, pub)).id, "abc123");
  await assert.rejects(verifyLicence(good.slice(0, -3) + "AAA", pub), /signature/);
  await assert.rejects(verifyLicence(await sign({ plan: "free", id: "abc123" }), pub), /plan/);
  await assert.rejects(verifyLicence(await sign({ plan: "connect", id: "abc123", exp: 1 }), pub), /expired/);
  await assert.rejects(verifyLicence(good, pub, Date.now() / 1000, "x,abc123"), /revoked/);
  const other = await signer();
  await assert.rejects(verifyLicence(await other.sign({ plan: "connect", id: "abc123" }), pub), /signature/);
});

test("upload, list, download, rotation and quota", async () => {
  const { pub, sign } = await signer();
  const env = { LICENCE_PUBKEY: pub, BACKUPS: bucket(), KEEP: "3", QUOTA_BYTES: "1000" };
  const key = await sign({ plan: "connect", id: "lic1" });

  assert.equal((await worker.fetch(req("GET", "/v1/status", "nope"), env)).status, 401);

  const ids = [];
  for (let i = 0; i < 4; i++) {
    const r = await worker.fetch(req("PUT", "/v1/backups", key, new Uint8Array(100).fill(i)), env);
    assert.equal(r.status, 201);
    ids.push((await r.json()).id);
    await new Promise((r) => setTimeout(r, 5)); // distinct timestamps
  }
  const st = await (await worker.fetch(req("GET", "/v1/status", key), env)).json();
  assert.equal(st.backups.length, 3); // KEEP
  assert.equal(st.used_bytes, 300);
  assert.equal(st.backups[0].id, ids[3]); // newest first
  assert.ok(!st.backups.find((b) => b.id === ids[0])); // oldest rotated out

  const dl = await worker.fetch(req("GET", `/v1/backups/${ids[3]}`, key), env);
  assert.deepEqual(new Uint8Array(await dl.arrayBuffer()), new Uint8Array(100).fill(3));

  // Another licence never sees these.
  const other = await sign({ plan: "connect", id: "lic2" });
  assert.equal((await worker.fetch(req("GET", `/v1/backups/${ids[3]}`, other), env)).status, 404);

  // Quota: a too-big upload is refused even after rotation.
  assert.equal((await worker.fetch(req("PUT", "/v1/backups", key, new Uint8Array(1200)), env)).status, 413);
  // A big-but-fitting one evicts older backups to make room.
  assert.equal((await worker.fetch(req("PUT", "/v1/backups", key, new Uint8Array(900)), env)).status, 201);
  const st2 = await (await worker.fetch(req("GET", "/v1/status", key), env)).json();
  assert.ok(st2.used_bytes <= 1000);

  assert.equal((await worker.fetch(req("DELETE", `/v1/backups/${st2.backups[0].id}`, key), env)).status, 200);
});
