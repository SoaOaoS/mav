"""Sign-in: password storage, signed sessions, and the API guard over HTTP.

Run: python3 -m unittest discover -s tests -v
"""

import http.client
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402
import mav_auth  # noqa: E402


class AuthUnitTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.auth = mav_auth.Auth(Path(self.dir) / "auth.json")

    def test_open_until_a_password_exists(self):
        self.assertFalse(self.auth.configured())
        self.assertTrue(self.auth.allowed("/api/runs", ""))
        self.assertTrue(self.auth.state("")["setup_needed"])

    def test_password_is_hashed_and_private(self):
        self.auth.set_password("correct horse")
        raw = (Path(self.dir) / "auth.json").read_text()
        self.assertNotIn("correct horse", raw)
        mode = stat.S_IMODE(os.stat(Path(self.dir) / "auth.json").st_mode)
        self.assertEqual(mode, 0o600)
        self.assertTrue(self.auth.check_password("correct horse"))
        self.assertFalse(self.auth.check_password("wrong horse"))

    def test_short_password_refused(self):
        with self.assertRaises(ValueError):
            self.auth.set_password("short")

    def test_sessions(self):
        self.auth.set_password("correct horse")
        token = self.auth.issue()
        cookie = f"other=1; {mav_auth.COOKIE}={token}"
        self.assertTrue(self.auth.allowed("/api/runs", cookie))
        self.assertFalse(self.auth.allowed("/api/runs", ""))
        self.assertFalse(self.auth.allowed("/api/runs", f"{mav_auth.COOKIE}={token}x"))
        # Public paths and the app shell never need a session.
        for path in ("/", "/assets/js/app.js", "/api/auth/state", "/api/health", "/api/hooks/x"):
            self.assertTrue(self.auth.allowed(path, ""), path)

    def test_password_change_signs_everyone_out(self):
        self.auth.set_password("correct horse")
        old = self.auth.issue()
        self.auth.set_password("battery staple")
        self.assertFalse(self.auth.valid(old))
        self.assertTrue(self.auth.valid(self.auth.issue()))

    def test_expired_session(self):
        self.auth.set_password("correct horse")
        orig = mav_auth.SESSION_DAYS
        mav_auth.SESSION_DAYS = -1
        try:
            token = self.auth.issue()
        finally:
            mav_auth.SESSION_DAYS = orig
        self.assertFalse(self.auth.valid(token))

    def test_brute_force_backoff(self):
        for _ in range(5):
            self.assertEqual(self.auth.throttled("1.2.3.4"), 0)
            self.auth.failed("1.2.3.4")
        self.assertGreater(self.auth.throttled("1.2.3.4"), 0)
        self.assertEqual(self.auth.throttled("5.6.7.8"), 0)

    def test_disabled(self):
        off = mav_auth.Auth(Path(self.dir) / "auth.json", enabled=False)
        self.auth.set_password("correct horse")
        self.assertTrue(off.allowed("/api/runs", ""))


class AuthHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.saved = mav_api.AUTH
        mav_api.AUTH = mav_auth.Auth(Path(cls.dir) / "auth.json")
        cls.srv = mav_api.ThreadedHTTPServer(("127.0.0.1", 0), mav_api.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        mav_api.AUTH = cls.saved

    def req(self, method, path, body=None, cookie=""):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        data = r.read()
        set_cookie = r.getheader("Set-Cookie") or ""
        c.close()
        try:
            data = json.loads(data)
        except Exception:  # noqa: BLE001
            pass
        return r.status, data, set_cookie.split(";")[0]

    def test_full_flow(self):
        st, data, _ = self.req("GET", "/api/auth/state")
        self.assertEqual((st, data["setup_needed"]), (200, True))
        self.assertEqual(self.req("GET", "/api/runs")[0], 200)  # open before setup

        self.assertEqual(self.req("POST", "/api/auth/setup", {"password": "short"})[0], 400)
        st, _, cookie = self.req("POST", "/api/auth/setup", {"password": "correct horse"})
        self.assertEqual(st, 200)
        self.assertTrue(cookie.startswith("mav_session="))
        # A second setup is refused: nobody can take over an install.
        self.assertEqual(self.req("POST", "/api/auth/setup", {"password": "evil password"})[0], 409)

        self.assertEqual(self.req("GET", "/api/runs")[0], 401)
        self.assertEqual(self.req("POST", "/api/job/delete", {"name": "x"})[0], 401)
        self.assertEqual(self.req("GET", "/api/stream?session=x")[0], 401)
        self.assertEqual(self.req("GET", "/api/runs", cookie=cookie)[0], 200)
        self.assertEqual(self.req("GET", "/api/health")[0], 200)
        self.assertEqual(self.req("GET", "/api/auth/state", cookie=cookie)[1]["authenticated"], True)

        self.assertEqual(self.req("POST", "/api/auth/login", {"password": "nope nope"})[0], 401)
        st, _, cookie2 = self.req("POST", "/api/auth/login", {"password": "correct horse"})
        self.assertEqual(st, 200)

        # Changing the password needs the current one, and signs others out.
        self.assertEqual(self.req("POST", "/api/auth/password",
                                  {"current": "wrong one!", "password": "battery staple"},
                                  cookie=cookie)[0], 400)
        st, _, cookie3 = self.req("POST", "/api/auth/password",
                                  {"current": "correct horse", "password": "battery staple"},
                                  cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(self.req("GET", "/api/runs", cookie=cookie2)[0], 401)
        self.assertEqual(self.req("GET", "/api/runs", cookie=cookie3)[0], 200)

        st, _, cleared = self.req("POST", "/api/auth/logout", cookie=cookie3)
        self.assertEqual((st, cleared), (200, "mav_session="))

    def test_static_files_stay_in_their_folder(self):
        for path in ("/../server/mav_auth.py", "/%2e%2e/server/mav_auth.py", "/certs/server.key", "/server/mav_auth.py", "/README.md", "/.gitignore"):
            self.assertEqual(self.req("GET", path)[0], 404, path)
        self.assertEqual(self.req("GET", "/manifest.webmanifest")[0], 200)

    def test_no_wildcard_cors(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/health")
        r = c.getresponse()
        r.read()
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        c.close()


if __name__ == "__main__":
    unittest.main()
