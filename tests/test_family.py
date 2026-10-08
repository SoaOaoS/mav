"""Family accounts: the owner adds members, and two accounts on one Mav never
see each other's chats, memory or routines.

The accounts and the API guard run everywhere; memory and watch items need a
database (MAV_TEST_PG_DSN pointing to an empty test database, as in CI).

Run: python3 -m unittest tests.test_family -v
"""

import http.client
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server"), str(Path(__file__).resolve().parent)]

import mav_auth  # noqa: E402
from e2e_support import Stack  # noqa: E402

TEST_DSN = os.environ.get("MAV_TEST_PG_DSN", "")
OWNER_PW, ALICE_PW = "owner-password-1", "alice-password-1"


class FamilyAuthTest(unittest.TestCase):
    def setUp(self):
        self.auth = mav_auth.Auth(Path(tempfile.mkdtemp()) / "auth.json", owner_id=7)
        self.auth.set_password(OWNER_PW)

    def test_members_sign_in_with_their_name(self):
        alice = self.auth.add_member("Alice", ALICE_PW)
        self.assertNotEqual(alice["id"], 7)
        self.assertEqual(self.auth.login("", OWNER_PW), 7)
        self.assertEqual(self.auth.login("alice", ALICE_PW), alice["id"])  # any case
        self.assertIsNone(self.auth.login("", ALICE_PW))  # no name = the owner
        self.assertIsNone(self.auth.login("Alice", OWNER_PW))
        self.assertIsNone(self.auth.login("Bob", ALICE_PW))
        token = self.auth.issue(alice["id"])
        self.assertEqual(self.auth.user_of(token), alice["id"])
        self.assertEqual(self.auth.user_of(self.auth.issue()), 7)
        self.assertTrue(self.auth.state("")["named"])

    def test_names_are_unique_and_checked(self):
        self.auth.add_member("Alice", ALICE_PW)
        for bad in ("alice", "", "   ", "x" * 40, "<script>"):
            with self.assertRaises(ValueError, msg=bad):
                self.auth.add_member(bad, ALICE_PW)
        with self.assertRaises(ValueError):
            self.auth.add_member("Bob", "short")

    def test_a_password_change_signs_out_only_that_person(self):
        alice = self.auth.add_member("Alice", ALICE_PW)
        owner_token, alice_token = self.auth.issue(), self.auth.issue(alice["id"])
        self.auth.set_password("a-new-password", alice["id"])
        self.assertIsNone(self.auth.user_of(alice_token))
        self.assertEqual(self.auth.user_of(owner_token), 7)
        self.assertEqual(self.auth.login("Alice", "a-new-password"), alice["id"])

    def test_a_removed_member_is_signed_out_and_ids_are_not_reused(self):
        alice = self.auth.add_member("Alice", ALICE_PW)
        token = self.auth.issue(alice["id"])
        self.assertTrue(self.auth.remove_member(alice["id"]))
        self.assertIsNone(self.auth.user_of(token))
        self.assertFalse(self.auth.remove_member(7))  # never the owner
        bob = self.auth.add_member("Bob", ALICE_PW)
        self.assertGreater(bob["id"], alice["id"])

    def test_a_forged_member_claim_is_refused(self):
        alice = self.auth.add_member("Alice", ALICE_PW)
        payload, _, sig = self.auth.issue(alice["id"]).partition(".")
        claims = json.loads(mav_auth._unb64(payload))
        claims["u"] = 7  # pretend to be the owner with Alice's signature
        forged = mav_auth._b64(json.dumps(claims).encode()) + "." + sig
        self.assertIsNone(self.auth.user_of(forged))


class Client:
    def __init__(self, stack: Stack, cookie: str = ""):
        self.port = int(stack.url.rstrip("/").rsplit(":", 1)[1])
        self.cookie = cookie

    def req(self, method: str, path: str, body=None) -> tuple[int, object]:
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        data = r.read()
        set_cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
        if set_cookie.startswith("mav_session=") and set_cookie != "mav_session=":
            self.cookie = set_cookie
        c.close()
        try:
            return r.status, json.loads(data)
        except Exception:  # noqa: BLE001
            return r.status, data

    def get(self, path: str):
        return self.req("GET", path)

    def post(self, path: str, body=None):
        return self.req("POST", path, body or {})


class FamilyIsolationTest(unittest.TestCase):
    """Two accounts on one instance, over HTTP, against the fake engine."""

    @classmethod
    def setUpClass(cls):
        env = {}
        if TEST_DSN:
            import psycopg2  # noqa: PLC0415

            conn = psycopg2.connect(TEST_DSN)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("DROP TABLE IF EXISTS conversations, facts, preferences, watch_items, "
                        "notifications, notify_digest CASCADE")
            cur.execute((ROOT / "scripts" / "schema.sql").read_text())
            conn.close()
            env["PG_DSN"] = TEST_DSN
        cls.stack = Stack(engine_args=("--word-delay", "0"), env=env).__enter__()
        cls.owner = Client(cls.stack)
        assert cls.owner.post("/api/auth/setup", {"password": OWNER_PW})[0] == 200
        st, res = cls.owner.post("/api/family/add", {"name": "Alice", "password": ALICE_PW})
        assert st == 200, res
        cls.alice_id = res["member"]["id"]
        cls.alice = Client(cls.stack)
        st, res = cls.alice.post("/api/auth/login", {"name": "Alice", "password": ALICE_PW})
        assert st == 200, res

    @classmethod
    def tearDownClass(cls):
        cls.stack.__exit__(None, None, None)

    def test_1_who_is_signed_in(self):
        self.assertEqual(self.alice.get("/api/auth/state")[1]["user"],
                         {"id": self.alice_id, "name": "Alice", "role": "member", "created": unittest.mock.ANY})
        self.assertEqual(self.owner.get("/api/auth/state")[1]["user"]["role"], "owner")
        self.assertTrue(self.owner.get("/api/auth/state")[1]["named"])
        # Without a name, Alice's password is not the owner's.
        self.assertEqual(Client(self.stack).post("/api/auth/login", {"password": ALICE_PW})[0], 401)

    def test_2_members_cannot_touch_the_owners_settings(self):
        for path in ("/api/config/provider", "/api/family", "/api/backup", "/api/usage",
                     "/api/connections", "/api/interests", "/api/drafts", "/api/config/agents"):
            self.assertEqual(self.alice.get(path)[0], 403, path)
        for path in ("/api/config/provider", "/api/family/add", "/api/update", "/api/config/restart",
                     "/api/backup/restore", "/api/channels/save", "/api/calendar/save", "/api/mail/save"):
            self.assertEqual(self.alice.post(path, {"name": "Eve", "password": "eve-password"})[0], 403, path)
        # What they get is empty, not the owner's.
        self.assertEqual(self.alice.get("/api/channels")[1]["channels"], [])
        self.assertEqual(self.alice.get("/api/calendar")[1]["sources"], [])
        self.assertEqual(len(self.owner.get("/api/family")[1]["accounts"]), 2)

    def test_3_chats_are_private(self):
        mine = self.owner.post("/api/session/new", {"title": "Owner plans"})[1]["id"]
        hers = self.alice.post("/api/session/new", {"title": "Alice plans"})[1]["id"]
        owner_list = [s["id"] for s in self.owner.get("/api/sessions")[1]["sessions"]]
        alice_list = [s["id"] for s in self.alice.get("/api/sessions")[1]["sessions"]]
        self.assertIn(mine, owner_list)
        self.assertNotIn(hers, owner_list)
        self.assertEqual(alice_list, [hers])
        # Someone else's chat is "not found", whatever the call.
        self.assertEqual(self.alice.get(f"/api/session?id={mine}")[0], 404)
        self.assertEqual(self.alice.get(f"/api/session/export?id={mine}")[0], 404)
        self.assertEqual(self.alice.get(f"/api/stream?session={mine}&prompt=hi")[0], 404)
        for path in ("/api/session/rename", "/api/session/delete", "/api/session/summary", "/api/run/stop"):
            self.assertEqual(self.alice.post(path, {"id": mine, "title": "x"})[0], 404, path)
        self.assertEqual(self.alice.post("/api/ask", {"prompt": "hi", "session": mine})[0], 404)
        self.assertEqual(self.owner.get(f"/api/session?id={hers}")[0], 404)
        self.assertEqual(self.owner.get(f"/api/session?id={mine}")[0], 200)

        # Alice talks in her chat; the answer and its run are hers only.
        st, body = self.alice.get(f"/api/stream?session={hers}&prompt=remember+the+word+pistachio")
        self.assertEqual(st, 200)
        self.assertIn("event: done", body.decode() if isinstance(body, bytes) else str(body))
        msgs = self.alice.get(f"/api/session?id={hers}")[1]["messages"]
        self.assertIn("pistachio", " ".join(m["text"] for m in msgs))
        self.assertEqual([r["session"] for r in self.owner.get("/api/runs")[1]["runs"]], [])

    def test_4_routines_are_private(self):
        st, res = self.owner.post("/api/job/save", {"name": "Coffee", "prompt": "Coffee news", "time": "08:00"})
        self.assertEqual(st, 200, res)
        st, res = self.alice.post("/api/job/save", {"name": "Tea time", "prompt": "Tea facts", "time": "16:00",
                                                    "channels": ["discord1"]})
        self.assertEqual(st, 200, res)
        jobs = json.loads((self.stack.tmp / "jobs.json").read_text())
        tea = next(j for j in jobs if j["name"] == "Tea time")
        self.assertEqual(tea["owner"], self.alice_id)
        self.assertNotIn("channels", tea)  # the owner's channels are not hers to use
        self.assertNotIn("owner", next(j for j in jobs if j["name"] == "Coffee"))

        self.assertEqual([j["name"] for j in self.alice.get("/api/jobs")[1]["jobs"]], ["Tea time"])
        self.assertNotIn("Tea time", [j["name"] for j in self.owner.get("/api/jobs")[1]["jobs"]])
        # Neither can change, run or take over the other's routine.
        self.assertEqual(self.owner.post("/api/job/delete", {"name": "Tea time"})[0], 404)
        self.assertEqual(self.alice.post("/api/job/toggle", {"name": "Coffee", "enabled": False})[0], 404)
        self.assertEqual(self.alice.post("/api/job/run", {"name": "Coffee"})[0], 400)
        st, _ = self.alice.post("/api/job/save", {"name": "Coffee", "prompt": "mine now", "time": "09:00",
                                                  "original": "Coffee"})
        self.assertEqual(st, 400)
        # Events and calendars are the owner's.
        st, _ = self.alice.post("/api/job/save", {"name": "On mail", "prompt": "x", "on_event": {"kind": "mail"}})
        self.assertEqual(st, 400)
        self.assertEqual(json.loads((self.stack.tmp / "jobs.json").read_text())[0]["prompt"], "Coffee news")

        # Her daily briefing is her own routine, next to the owner's.
        self.assertTrue(self.owner.post("/api/briefing", {"enabled": True, "time": "07:00"})[1]["ok"])
        res = self.alice.post("/api/briefing", {"enabled": True, "time": "07:30"})[1]
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.owner.get("/api/briefing")[1]["time"], "07:00")
        self.assertEqual(self.alice.get("/api/briefing")[1]["time"], "07:30")

    @unittest.skipUnless(TEST_DSN, "set MAV_TEST_PG_DSN to an empty test database")
    def test_5_memory_and_watch_items_are_private(self):
        self.assertTrue(self.owner.post("/api/memory/fact/add", {"fact": "Owner drinks coffee"})[1]["ok"])
        self.assertTrue(self.alice.post("/api/memory/fact/add", {"fact": "Alice drinks tea"})[1]["ok"])
        owner_facts = self.owner.get("/api/memory")[1]["facts"]
        alice_facts = self.alice.get("/api/memory")[1]["facts"]
        self.assertEqual([f["fact"] for f in owner_facts], ["Owner drinks coffee"])
        self.assertEqual([f["fact"] for f in alice_facts], ["Alice drinks tea"])
        # Deleting, forgetting or searching never reaches the other's memory.
        self.alice.post("/api/memory/fact/delete", {"id": owner_facts[0]["id"]})
        self.alice.post("/api/memory/forget", {"facts": True})
        self.assertEqual(len(self.owner.get("/api/memory")[1]["facts"]), 1)
        self.assertEqual(self.alice.get("/api/memory")[1]["facts"], [])
        self.assertEqual(self.alice.get("/api/search?q=coffee")[1]["facts"], [])

        # A chat exchange is remembered for whoever had it.
        sid = self.alice.post("/api/session/new", {})[1]["id"]
        self.alice.get(f"/api/stream?session={sid}&prompt=my+cat+is+called+Miso")
        for _ in range(50):
            convs = self.alice.get("/api/memory")[1]["conversations"]
            if convs:
                break
            time.sleep(0.1)
        self.assertTrue(any("Miso" in c["question"] for c in convs))
        self.assertFalse(any("Miso" in c["question"] for c in self.owner.get("/api/memory")[1]["conversations"]))

        self.assertTrue(self.alice.post("/api/watch/add", {"kind": "rss", "target": "https://example.org/feed"})[1]["ok"])
        self.assertEqual(self.owner.get("/api/watch")[1]["items"], [])
        item = self.alice.get("/api/watch")[1]["items"][0]
        self.owner.post("/api/watch/remove", {"id": item["id"]})
        self.assertEqual(len(self.alice.get("/api/watch")[1]["items"]), 1)

        self.alice.post("/api/proactivity", {"level": "chatty"})
        self.assertEqual(self.owner.get("/api/proactivity")[1]["level"], "normal")
        self.assertEqual(self.alice.get("/api/proactivity")[1]["level"], "chatty")

    def test_6_own_password_and_removal(self):
        bob = Client(self.stack)
        st, res = self.owner.post("/api/family/add", {"name": "Bob", "password": "bob-password-1"})
        self.assertEqual(st, 200, res)
        bob_id = res["member"]["id"]
        self.assertEqual(bob.post("/api/auth/login", {"name": "bob", "password": "bob-password-1"})[0], 200)
        self.assertTrue(bob.post("/api/job/save", {"name": "Bob run", "prompt": "x", "time": "06:00"})[1]["ok"])
        # Bob changes his own password; the owner's still works.
        self.assertEqual(bob.post("/api/auth/password", {"current": "wrong-password", "password": "x" * 10})[0], 400)
        self.assertEqual(bob.post("/api/auth/password", {"current": "bob-password-1",
                                                         "password": "bob-password-2"})[0], 200)
        self.assertEqual(Client(self.stack).post("/api/auth/login", {"password": OWNER_PW})[0], 200)
        # The owner removes Bob: signed out, and his routines are gone.
        self.assertEqual(self.owner.post("/api/family/remove", {"id": bob_id})[0], 200)
        self.assertEqual(bob.get("/api/jobs")[0], 401)
        names = [j["name"] for j in json.loads((self.stack.tmp / "jobs.json").read_text())]
        self.assertNotIn("Bob run", names)
        self.assertEqual(self.owner.post("/api/family/remove", {"id": 0})[0], 404)  # never the owner


if __name__ == "__main__":
    unittest.main()
