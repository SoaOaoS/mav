"""Backup and restore (dashboard/server/mav_backup.py).

The database round trip runs when MAV_TEST_PG_DSN points to an empty test
database (CI's docker job and a local Postgres); the rest needs nothing.

Run: python3 -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_backup  # noqa: E402

TEST_DSN = os.environ.get("MAV_TEST_PG_DSN", "")
NO_DB = "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1"


def tar_with(entries: dict, manifest: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        items = dict(entries)
        items.setdefault("manifest.json", json.dumps(manifest or {"app": "mav", "format": 1}).encode())
        for name, data in items.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class BackupFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.places = self.make_places(self.tmp / "a", NO_DB)
        bot = self.places.bot_dir
        (bot / "venv" / "lib").mkdir(parents=True)
        (bot / "venv" / "lib" / "x.py").write_text("code")
        (bot / "mav_worker.py").write_text("code")
        (bot / "jobs.json").write_text('[{"name": "Umbrella"}]')
        (bot / "auth.json").write_text('{"hash": "h"}')
        (bot / "media").mkdir()
        (bot / "media" / "pic.png").write_bytes(b"\x89PNG")
        (self.places.config_dir / "agent").mkdir(parents=True)
        (self.places.config_dir / "opencode.json").write_text('{"model": "x/y"}')
        (self.places.config_dir / "agent" / "assistant.md").write_text("mine")
        (self.places.config_dir / "node_modules" / "p").mkdir(parents=True)
        (self.places.config_dir / "node_modules" / "p" / "i.js").write_text("x")
        (self.places.storage_dir / "session").mkdir(parents=True)
        (self.places.storage_dir / "session" / "s1.json").write_text("{}")
        self.places.env_server.write_text("ANTHROPIC_API_KEY=sk-1\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_places(base: Path, dsn: str) -> mav_backup.Places:
        for d in ("bot", "config", "storage"):
            (base / d).mkdir(parents=True, exist_ok=True)
        return mav_backup.Places(dsn=dsn, bot_dir=base / "bot", config_dir=base / "config",
                                 storage_dir=base / "storage", env_server=base / "server.env",
                                 version="v9.9.9", runtime="test")

    def backup(self, places=None, **kw) -> bytes:
        buf = io.BytesIO()
        mav_backup.create(places or self.places, buf, **kw)
        return buf.getvalue()

    def names(self, data: bytes) -> set:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            return set(tar.getnames())

    def test_backup_holds_data_not_code(self):
        data = self.backup()
        names = self.names(data)
        for n in ("manifest.json", "bot/jobs.json", "bot/auth.json", "bot/media/pic.png",
                  "opencode-config/opencode.json", "opencode-config/agent/assistant.md",
                  "opencode-storage/session/s1.json", "config/server.env"):
            self.assertIn(n, names)
        for n in names:
            self.assertFalse(n.endswith(".py") or "venv" in n or "node_modules" in n, n)
        man = mav_backup.inspect(data)
        self.assertEqual((man["version"], man["runtime"]), ("v9.9.9", "test"))
        self.assertIn("db_error", man)  # no database here: files only, and it says so

    def test_chats_are_optional(self):
        self.assertFalse(any(n.startswith("opencode-storage/") for n in self.names(self.backup(include_chats=False))))

    def test_restore_puts_files_back_and_keeps_a_safety_copy(self):
        data = self.backup()
        target = self.make_places(self.tmp / "b", NO_DB)
        (target.bot_dir / "jobs.json").write_text("[]")
        res = mav_backup.restore(target, data)
        self.assertTrue(res["ok"])
        self.assertEqual((target.bot_dir / "jobs.json").read_text(), '[{"name": "Umbrella"}]')
        self.assertEqual((target.config_dir / "agent" / "assistant.md").read_text(), "mine")
        self.assertEqual(target.env_server.read_text(), "ANTHROPIC_API_KEY=sk-1\n")
        self.assertEqual(oct(target.env_server.stat().st_mode & 0o777), "0o600")
        copies = mav_backup.safety_copies(target)
        self.assertEqual(len(copies), 1)
        # The safety copy holds what was there before.
        with tarfile.open(target.bot_dir / "backups" / copies[0]["name"]) as tar:
            self.assertEqual(tar.extractfile("bot/jobs.json").read(), b"[]")

    def test_only_three_safety_copies_are_kept(self):
        data = self.backup()
        target = self.make_places(self.tmp / "c", NO_DB)
        for i in range(5):
            (target.bot_dir / "backups").mkdir(exist_ok=True)
            (target.bot_dir / "backups" / f"pre-restore-2000010{i}-000000.tar.gz").write_bytes(b"x")
        mav_backup.restore(target, data)
        self.assertEqual(len(mav_backup.safety_copies(target)), mav_backup.KEEP_SAFETY)

    def test_hostile_archives_are_refused(self):
        bad = [
            {"../../etc/passwd": b"x"},
            {"/etc/passwd": b"x"},
            {"bot/../../x": b"x"},
            {"elsewhere/file": b"x"},
            {"config/other.env": b"x"},
            {"db/pg_authid.csv": b"x"},
            {"db/sub/facts.csv": b"x"},
        ]
        target = self.make_places(self.tmp / "d", NO_DB)
        for entries in bad:
            with self.assertRaises(mav_backup.BackupError, msg=entries):
                mav_backup.restore(target, tar_with(entries))
        # A symlink entry is refused too.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("bot/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        with self.assertRaises(mav_backup.BackupError):
            mav_backup.restore(target, buf.getvalue())
        self.assertFalse((target.bot_dir / "backups").exists())  # refused before touching anything

    def test_not_a_backup(self):
        for data in (b"hello", tar_with({}, {"app": "other"}), tar_with({}, {"app": "mav", "format": 99})):
            with self.assertRaises(mav_backup.BackupError):
                mav_backup.inspect(data)


@unittest.skipUnless(TEST_DSN, "set MAV_TEST_PG_DSN to an empty test database")
class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        import psycopg2  # noqa: PLC0415

        self.tmp = Path(tempfile.mkdtemp())
        self.conn = psycopg2.connect(TEST_DSN)
        self.conn.autocommit = True
        cur = self.conn.cursor()
        cur.execute("DROP TABLE IF EXISTS " + ", ".join(mav_backup.TABLES) + " CASCADE")
        cur.execute((ROOT / "scripts" / "schema.sql").read_text())
        cur.execute("CREATE TABLE IF NOT EXISTS interests (id bigserial PRIMARY KEY, chat_id bigint NOT NULL, "
                    "key text NOT NULL, label text NOT NULL)")
        cur.execute("INSERT INTO facts (chat_id, fact, ts) VALUES (1, 'Lives in Lyon', 1), (1, 'Likes, \"quotes\"\nand lines', 2)")
        cur.execute("INSERT INTO conversations (chat_id, session_id, question, answer, ts) VALUES (1, 's', 'hi', 'hello', 3)")
        self.places = BackupFilesTest.make_places(self.tmp, TEST_DSN)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip(self):
        buf = io.BytesIO()
        man = mav_backup.create(self.places, buf)
        self.assertEqual(man["tables"]["facts"], 2)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM facts")
        cur.execute("INSERT INTO facts (chat_id, fact, ts) VALUES (1, 'stale', 9)")
        res = mav_backup.restore(self.places, buf.getvalue())
        self.assertEqual(res["tables"]["facts"], 2)
        cur.execute("SELECT fact FROM facts ORDER BY ts")
        self.assertEqual([r[0] for r in cur.fetchall()], ["Lives in Lyon", 'Likes, "quotes"\nand lines'])
        # The generated full-text column is rebuilt, and new rows get fresh ids.
        cur.execute("SELECT count(*) FROM conversations WHERE tsv @@ to_tsquery('simple', 'hello')")
        self.assertEqual(cur.fetchone()[0], 1)
        cur.execute("INSERT INTO facts (chat_id, fact, ts) VALUES (1, 'new', 10) RETURNING id")
        self.assertGreater(cur.fetchone()[0], 2)

    def test_unknown_columns_roll_everything_back(self):
        data = tar_with({"db/facts.csv": b"id,chat_id,fact,ts,evil\n1,1,x,1,y\n"})
        with self.assertRaises(mav_backup.BackupError):
            mav_backup.restore(self.places, data)
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM facts")
        self.assertEqual(cur.fetchone()[0], 2)  # the truncate was rolled back


if __name__ == "__main__":
    unittest.main()
