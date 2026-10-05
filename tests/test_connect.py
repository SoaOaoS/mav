"""Mav Connect backup client: encryption, archive, restore, and a full round
trip against a fake Connect service. With MAV_TEST_PG_DSN set, the database
part is exercised too.

Run: python3 -m unittest discover -s tests -v
"""

import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import occonnect  # noqa: E402


class CryptoTest(unittest.TestCase):
    def test_roundtrip_and_wrong_key(self):
        key = occonnect.new_recovery_key()
        self.assertRegex(key, r"^[A-Z2-7]{4}(-[A-Z2-7]{4}){5}$")
        blob = occonnect.encrypt(b"hello memory", key)
        self.assertTrue(blob.startswith(occonnect.MAGIC))
        self.assertNotIn(b"hello memory", blob)
        self.assertEqual(occonnect.decrypt(blob, key), b"hello memory")
        self.assertEqual(occonnect.decrypt(blob, key.lower().replace("-", " ")), b"hello memory")
        with self.assertRaises(ValueError):
            occonnect.decrypt(blob, occonnect.new_recovery_key())
        with self.assertRaises(ValueError):
            occonnect.decrypt(b"garbage", key)


def make_install(root: Path) -> tuple[Path, Path]:
    bot, home = root / "bot", root / "home"
    (bot / "venv").mkdir(parents=True)
    (bot / "jobs.json").write_text('[{"name": "Morning"}]')
    (bot / "auth.json").write_text("{}")
    (bot / "licence.json").write_text('{"key": "MAV1.secret"}')
    (bot / "connect.json").write_text('{"recovery_key": "SECRET"}')
    (bot / "mav_worker.py").write_text("code")
    (bot / "venv" / "big.bin").write_text("x")
    cfg = home / ".config" / "opencode"
    (cfg / "agent").mkdir(parents=True)
    (cfg / "AGENTS.md").write_text("Be brief.")
    (cfg / "agent" / "writer.md").write_text("helper")
    data = home / ".local" / "share" / "opencode" / "storage" / "session"
    data.mkdir(parents=True)
    (data / "ses_1.json").write_text('{"title": "dash: Trip"}')
    return bot, home


class ArchiveTest(unittest.TestCase):
    def test_archive_content_and_restore(self):
        src = Path(tempfile.mkdtemp())
        bot, home = make_install(src)
        b = occonnect.Backup(bot, dsn="", home=home)
        archive, manifest = b.build_archive()
        names = set(tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz").getnames())
        self.assertIn("files/bot/jobs.json", names)
        self.assertIn("files/opencode-config/AGENTS.md", names)
        self.assertIn("files/opencode-data/session/ses_1.json", names)
        for secret in ("files/bot/licence.json", "files/bot/connect.json",
                       "files/bot/mav_worker.py", "files/bot/venv/big.bin"):
            self.assertNotIn(secret, names)
        self.assertEqual(manifest["dirs"]["opencode-config"], 2)

        dst = Path(tempfile.mkdtemp())
        nb, nh = dst / "bot", dst / "home"
        res = occonnect.Backup(nb, dsn="", home=nh).restore_archive(archive)
        self.assertTrue(res["restart"])
        self.assertEqual((nb / "jobs.json").read_text(), '[{"name": "Morning"}]')
        self.assertEqual((nh / ".config/opencode/AGENTS.md").read_text(), "Be brief.")
        self.assertTrue((nh / ".local/share/opencode/storage/session/ses_1.json").exists())

    def test_restore_never_writes_outside(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            occonnect._add_bytes(tar, "files/bot/../../evil.txt", b"x")
            occonnect._add_bytes(tar, "files/elsewhere/x.txt", b"x")
        dst = Path(tempfile.mkdtemp())
        occonnect.Backup(dst / "bot", home=dst / "home").restore_archive(buf.getvalue())
        self.assertFalse((dst / "evil.txt").exists())
        self.assertFalse(any(dst.rglob("x.txt")))


class FakeConnect(BaseHTTPRequestHandler):
    """The Connect API, in memory, accepting one licence key."""
    store: dict = {}
    KEY = "MAV1.good.key"

    def log_message(self, *a):
        pass

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {self.KEY}":
            self._json(401, {"error": "invalid"})
            return False
        return True

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._auth():
            return
        if self.path == "/v1/status":
            return self._json(200, {"used_bytes": sum(map(len, self.store.values())),
                                    "quota_bytes": 10**9, "backups": [
                                        {"id": k, "size": len(v)} for k, v in sorted(self.store.items(), reverse=True)]})
        name = self.path.rsplit("/", 1)[-1]
        data = self.store.get(name)
        if data is None:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        if not self._auth():
            return
        n = int(self.headers.get("Content-Length") or 0)
        name = f"2026-01-0{len(self.store) + 1}T03-00-00-000Z.mavbak"
        self.store[name] = self.rfile.read(n)
        self._json(201, {"ok": True, "id": name, "size": n})


class RoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeConnect)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.saved = os.environ.get("MAV_CONNECT_URL")
        os.environ["MAV_CONNECT_URL"] = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        if cls.saved is None:
            os.environ.pop("MAV_CONNECT_URL", None)
        else:
            os.environ["MAV_CONNECT_URL"] = cls.saved

    def test_backup_and_restore_on_a_new_machine(self):
        FakeConnect.store.clear()
        src = Path(tempfile.mkdtemp())
        bot, home = make_install(src)
        (bot / "licence.json").write_text(json.dumps({"key": FakeConnect.KEY}))
        dsn = os.environ.get("MAV_TEST_PG_DSN", "")
        b = occonnect.Backup(bot, dsn=dsn, home=home)
        self.assertTrue(b.due())
        last = b.backup_now()
        self.assertFalse(b.due())
        stored = FakeConnect.store[last["id"]]
        self.assertNotIn(b"Be brief.", stored)  # ciphertext only leaves the machine

        # A fresh machine with the same licence and the recovery key.
        dst = Path(tempfile.mkdtemp())
        nb, nh = dst / "bot", dst / "home"
        nb.mkdir()
        (nb / "licence.json").write_text(json.dumps({"key": FakeConnect.KEY}))
        fresh = occonnect.Backup(nb, dsn=dsn, home=nh)
        backups = fresh.status()["backups"]
        with self.assertRaises(ValueError):
            fresh.restore(backups[0]["id"], occonnect.new_recovery_key())
        res = fresh.restore(backups[0]["id"], b.recovery_key())
        self.assertGreater(res["files"], 3)
        self.assertEqual((nh / ".config/opencode/AGENTS.md").read_text(), "Be brief.")
        self.assertEqual(fresh.recovery_key(), b.recovery_key())  # adopted

    def test_wrong_licence_is_refused(self):
        bot, home = make_install(Path(tempfile.mkdtemp()))
        (bot / "licence.json").write_text(json.dumps({"key": "MAV1.patched.copy"}))
        with self.assertRaises(occonnect.ConnectError):
            occonnect.Backup(bot, home=home).backup_now()

    def test_not_configured(self):
        saved = os.environ.pop("MAV_CONNECT_URL")
        try:
            b = occonnect.Backup(Path(tempfile.mkdtemp()))
            self.assertFalse(b.due())
            with self.assertRaises(occonnect.ConnectError):
                b.status()
        finally:
            os.environ["MAV_CONNECT_URL"] = saved


@unittest.skipUnless(os.environ.get("MAV_TEST_PG_DSN"), "needs MAV_TEST_PG_DSN (a scratch Mav database)")
class DatabaseTest(unittest.TestCase):
    """Database rows survive a backup → wipe → restore, ids keep counting."""

    def test_rows_and_sequences(self):
        import psycopg2

        dsn = os.environ["MAV_TEST_PG_DSN"]
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("truncate facts")
        cur.execute("insert into facts (chat_id, fact, ts) values (0, 'User lives in Lyon', 1), (0, 'User likes jazz', 2)")
        b = occonnect.Backup(Path(tempfile.mkdtemp()), dsn=dsn, home=Path(tempfile.mkdtemp()))
        archive, manifest = b.build_archive()
        self.assertIn("facts", manifest["tables"])
        cur.execute("truncate facts")
        b.restore_archive(archive)
        cur.execute("select fact from facts order by ts")
        self.assertEqual([r[0] for r in cur.fetchall()], ["User lives in Lyon", "User likes jazz"])
        cur.execute("insert into facts (chat_id, fact, ts) values (0, 'new', 3) returning id")
        new_id = cur.fetchone()[0]
        cur.execute("select max(id) from facts where fact <> 'new'")
        self.assertGreater(new_id, cur.fetchone()[0])
        conn.close()


if __name__ == "__main__":
    unittest.main()
