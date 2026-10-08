"""Hardening from the code review: requests from other sites, page headers,
oversized bodies, what /api/download may serve, the webhook's token, safe
path joins and the watcher's public-only fetch.

Run: python3 -m unittest tests.test_security -v
"""

import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402
import mav_auth  # noqa: E402
import mav_core  # noqa: E402
import mav_media  # noqa: E402
import mav_routines  # noqa: E402
import ocwatch  # noqa: E402


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.saved = mav_api.AUTH
        mav_api.AUTH = mav_auth.Auth(cls.dir / "auth.json")
        cls.srv = mav_api.ThreadedHTTPServer(("127.0.0.1", 0), mav_api.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        mav_api.AUTH = cls.saved
        shutil.rmtree(cls.dir, ignore_errors=True)

    def req(self, method, path, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", **(headers or {})}
        data = raw if raw is not None else (json.dumps(body) if body is not None else None)
        c.request(method, path, data, h)
        r = c.getresponse()
        out = r.read()
        c.close()
        try:
            out = json.loads(out)
        except Exception:  # noqa: BLE001
            pass
        return r.status, out, r


class CrossSiteTest(Server):
    def test_other_sites_cannot_act(self):
        host = f"127.0.0.1:{self.port}"
        # A form on another site posting to Mav, or a link starting an answer.
        st, _, _ = self.req("POST", "/api/memory/forget", {}, {"Origin": "https://evil.example"})
        self.assertEqual(st, 403)
        st, _, _ = self.req("POST", "/api/job/delete", {"name": "x"}, {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        st, _, _ = self.req("GET", "/api/stream?session=s&prompt=hi", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        # The app itself, scripts and webhooks are fine.
        with mock.patch.object(mav_api.mav_routines, "set_proactivity", return_value={"ok": True}):
            self.assertEqual(self.req("POST", "/api/proactivity", {"level": "quiet"},
                                      {"Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"})[0], 200)
            self.assertEqual(self.req("POST", "/api/proactivity", {"level": "quiet"})[0], 200)
        with mock.patch("ocevents.ensure_schema"), mock.patch("ocevents.push", return_value=1):
            st, _, _ = self.req("POST", "/api/hooks/event", {"kind": "x"}, {"Sec-Fetch-Site": "cross-site"})
        self.assertNotEqual(st, 403)

    def test_pages_carry_a_content_policy(self):
        st, _, r = self.req("GET", "/")
        self.assertEqual(st, 200)
        csp = r.getheader("Content-Security-Policy") or ""
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        # No inline script left in the page for the policy to block.
        html = (ROOT / "dashboard" / "index.html").read_text()
        self.assertNotRegex(html, r"<script>(?!\s*</script>)")

    def test_oversized_bodies_are_refused_unread(self):
        with mock.patch.object(mav_api, "MAX_BODY", 1000):
            st, _, _ = self.req("POST", "/api/upload", raw=b"x" * 5000)
        self.assertEqual(st, 413)


class WebhookTest(Server):
    def test_a_token_is_needed_from_outside(self):
        mav_api.AUTH.set_password("owner-password-1")  # outsiders are signed out
        with mock.patch.object(mav_routines, "hook_token", return_value=""), \
             mock.patch("ocevents.ensure_schema"), mock.patch("ocevents.push", return_value=7):
            st, res, _ = self.req("POST", "/api/hooks/event", {"kind": "custom"})
            self.assertEqual(st, 400)
            self.assertIn("token", res["error"])
            # Signed in, the owner may post without one.
            self.assertTrue(mav_routines.hook_event("custom", {}, "", signed_in=True)["ok"])
        with mock.patch.object(mav_routines, "hook_token", return_value="s3cret-token"), \
             mock.patch("ocevents.ensure_schema"), mock.patch("ocevents.push", return_value=7):
            self.assertEqual(self.req("POST", "/api/hooks/event", {"kind": "custom", "token": "nope"})[0], 400)
            self.assertEqual(self.req("POST", "/api/hooks/event", {"kind": "custom", "token": "s3cret-token"})[0], 200)


class DownloadTest(unittest.TestCase):
    def test_bot_dir_secrets_are_never_served(self):
        bot = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bot, ignore_errors=True)
        for name in ("channels.json", "calendar.json", "jobs.json", "notes.txt"):
            (bot / name).write_text("{}")
        (bot / "backups").mkdir()
        (bot / "backups" / "mav-safety-1.tar.gz").write_bytes(b"x")
        with mock.patch.object(mav_core, "BOT_DIR", bot):
            roots = mav_media._asset_roots()
            with mock.patch.object(mav_media, "_asset_roots", return_value=roots):
                for name in ("channels.json", "calendar.json", "jobs.json", "notes.txt",
                             "backups/mav-safety-1.tar.gz"):
                    self.assertIsNone(mav_media.resolve_download(str(bot / name)), name)
                self.assertIsNone(mav_media.resolve_download("mav-safety-1.tar.gz"))

    def test_a_sibling_folder_is_not_inside(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "files").mkdir()
        (base / "files-private").mkdir()
        self.assertTrue(mav_media._within((base / "files" / "a.png"), [base / "files"]))
        self.assertFalse(mav_media._within((base / "files-private" / "a.png"), [base / "files"]))


class PathsTest(unittest.TestCase):
    def test_inside(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertEqual(mav_core.inside(root, "a/b.txt"), Path(root).resolve() / "a" / "b.txt")
        for bad in ("../x", "/etc/passwd", "", "a/../../x"):
            with self.assertRaises(ValueError, msg=bad):
                mav_core.inside(root, bad)


class WatchTest(unittest.TestCase):
    def test_public_only(self):
        for url in ("http://127.0.0.1:4096/session", "http://localhost/", "http://169.254.169.254/latest",
                    "http://10.1.2.3/", "http://192.168.1.1/", "http://[::1]/", "file:///etc/passwd", ""):
            self.assertFalse(ocwatch.public_host(url), url)
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            self.assertTrue(ocwatch.public_host("https://example.org/feed"))
        with self.assertRaises(ValueError):
            ocwatch.fetch("http://127.0.0.1:1/", public_only=True)

    def test_members_cannot_watch_the_machine(self):
        with mav_core.as_user(mav_core.DEFAULT_CHAT_ID + 99), mock.patch.object(mav_core, "pg_exec") as ex:
            self.assertFalse(mav_routines.watch_add("web", "http://127.0.0.1:4096/session"))
            ex.assert_not_called()


if __name__ == "__main__":
    unittest.main()
