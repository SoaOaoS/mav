"""Notification channels: ntfy, Gotify, Discord, Slack (bot/occhannels.py).

Run: python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot")]
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1")

import occhannels  # noqa: E402
import ocnotify  # noqa: E402

DISCORD = "https://discord.com/api/webhooks/123456/abc-DEF_9"
SLACK = "https://hooks.slack.com/services/T000/B000/XXXX"


class Catcher(BaseHTTPRequestHandler):
    hits: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Catcher.hits.append((self.path, dict(self.headers), json.loads(body)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class ChannelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Catcher)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.saved = occhannels.CHANNELS_FILE
        occhannels.CHANNELS_FILE = Path(tempfile.mkdtemp()) / "channels.json"
        Catcher.hits = []

    def tearDown(self):
        occhannels.CHANNELS_FILE = self.saved

    # -------------------------------------------------------------- payloads
    def test_each_channel_gets_its_own_format(self):
        url = "https://mav.example.org/#chat/1"
        ep, h, m = occhannels.payload({"type": "ntfy", "server": "https://ntfy.sh", "topic": "t", "token": "tk"},
                                      "Title", "Body", url, "critical")
        self.assertEqual(ep, "https://ntfy.sh/")
        self.assertEqual((m["topic"], m["priority"], m["click"]), ("t", 5, url))
        self.assertEqual(h["Authorization"], "Bearer tk")
        ep, h, m = occhannels.payload({"type": "gotify", "server": "http://g.local", "token": "k"},
                                      "T", "B", url, "fyi")
        self.assertEqual(ep, "http://g.local/message")
        self.assertEqual(h["X-Gotify-Key"], "k")
        self.assertEqual(m["extras"]["client::notification"]["click"]["url"], url)
        self.assertEqual(m["priority"], 2)
        ep, _, m = occhannels.payload({"type": "discord", "webhook": DISCORD}, "T", "B", url)
        self.assertEqual(ep, DISCORD)
        self.assertEqual(m["embeds"][0]["url"], url)
        self.assertEqual(m["allowed_mentions"], {"parse": []})  # never @everyone
        _, _, m = occhannels.payload({"type": "slack", "webhook": SLACK}, "T", "B", url)
        self.assertIn("<https://mav.example.org/#chat/1|Open in Mav>", m["text"])

    def test_links_become_absolute_only_with_a_public_address(self):
        self.assertEqual(occhannels.absolute("./#chat/9", "https://m.org"), "https://m.org/#chat/9")
        self.assertEqual(occhannels.absolute("./?notif=3", "https://m.org/"), "https://m.org/?notif=3")
        self.assertEqual(occhannels.absolute("./#chat/9", ""), "")
        self.assertEqual(occhannels.absolute("https://x.y/z", ""), "https://x.y/z")

    # -------------------------------------------------------------- storage
    def test_validation_refuses_lookalike_webhooks(self):
        bad = [
            {"type": "discord", "webhook": "https://evil.example/api/webhooks/1/x"},
            {"type": "discord", "webhook": "http://discord.com/api/webhooks/1/x"},
            {"type": "slack", "webhook": "https://hooks.slack.com.evil.io/services/x"},
            {"type": "ntfy", "server": "file:///etc/passwd", "topic": "t"},
            {"type": "ntfy", "server": "https://u:p@ntfy.sh", "topic": "t"},
            {"type": "ntfy", "server": "https://ntfy.sh", "topic": "../x"},
            {"type": "gotify", "server": "https://g.org", "token": ""},
            {"type": "telegram"},
        ]
        for c in bad:
            self.assertIsNotNone(occhannels.validate(c), c)
        self.assertIsNone(occhannels.validate({"type": "discord", "webhook": DISCORD}))
        self.assertIsNone(occhannels.validate({"type": "slack", "webhook": SLACK}))

    def test_secrets_are_masked_and_kept_on_edit(self):
        r = occhannels.upsert({"type": "gotify", "name": "Home", "server": self.base, "token": "s3cret-token"})
        self.assertTrue(r["ok"], r)
        view = occhannels.public_view()["channels"][0]
        self.assertNotIn("s3cret", json.dumps(occhannels.public_view()))
        self.assertTrue(view["token"].startswith(occhannels.MASK))
        # Saving the form back as it came (masked) keeps the real token.
        occhannels.upsert({**view, "name": "Home server"})
        stored = occhannels.load()["channels"][0]
        self.assertEqual((stored["name"], stored["token"]), ("Home server", "s3cret-token"))
        self.assertEqual(oct(occhannels.CHANNELS_FILE.stat().st_mode & 0o777), "0o600")

    def test_remove(self):
        cid = occhannels.upsert({"type": "slack", "webhook": SLACK})["id"]
        self.assertTrue(occhannels.remove(cid)["ok"])
        self.assertFalse(occhannels.remove(cid)["ok"])
        self.assertEqual(occhannels.load()["channels"], [])

    # -------------------------------------------------------------- delivery
    def test_deliver_reaches_enabled_channels_only(self):
        a = occhannels.upsert({"type": "ntfy", "server": self.base, "topic": "alerts"})["id"]
        b = occhannels.upsert({"type": "gotify", "server": self.base, "token": "k"})["id"]
        occhannels.upsert({"type": "ntfy", "server": self.base, "topic": "off", "enabled": False})
        occhannels.set_public_url("https://mav.example.org")
        reached = occhannels.deliver("Hi", "There", "./#chat/1", "important")
        self.assertEqual(sorted(reached), sorted([a, b]))
        paths = sorted(h[0] for h in Catcher.hits)
        self.assertEqual(paths, ["/", "/message"])
        ntfy = next(h for h in Catcher.hits if h[0] == "/")[2]
        self.assertEqual((ntfy["topic"], ntfy["click"], ntfy["priority"]), ("alerts", "https://mav.example.org/#chat/1", 4))
        Catcher.hits = []
        self.assertEqual(occhannels.deliver("Hi", "x", only=[b]), [b])
        self.assertEqual([h[0] for h in Catcher.hits], ["/message"])

    def test_a_dead_channel_is_reported_not_raised(self):
        cid = occhannels.upsert({"type": "ntfy", "server": "http://127.0.0.1:1", "topic": "t"})["id"]
        self.assertEqual(occhannels.deliver("Hi", "x"), [])
        res = occhannels.test(cid)
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"])

    def test_notify_fans_out_and_honours_the_routine_choice(self):
        cid = occhannels.upsert({"type": "ntfy", "server": self.base, "topic": "t"})["id"]
        res = ocnotify.notify("Report", "Body", force=True)
        self.assertEqual(res["channels"], [cid])
        Catcher.hits = []
        res = ocnotify.notify("Report", "Body", force=True, channels=["push"])
        self.assertEqual(res["channels"], [])
        self.assertEqual(Catcher.hits, [])
        res = ocnotify.notify("Report", "Body", force=True, channels=["none"])
        self.assertEqual((res["push"], res["channels"]), (0, []))


if __name__ == "__main__":
    unittest.main()
