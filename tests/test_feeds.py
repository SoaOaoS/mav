"""Keep an eye on: RSS/Atom feeds and GitHub releases, with conditions.

Run: python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1")

import ocwatch  # noqa: E402

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>
<item><title>Postgres 17 is out</title><link>https://b.org/1</link><guid>g1</guid>
  <description>&lt;p&gt;Big &lt;b&gt;release&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Weekly notes</title><link>https://b.org/2</link><guid>g2</guid></item>
<item><title>Rust tips</title><link>https://b.org/3</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Release notes from core</title>
<entry><id>tag:github.com,2008:Repository/1/2026.10.1</id><title>2026.10.1</title>
  <link rel="alternate" type="text/html" href="https://github.com/home-assistant/core/releases/tag/2026.10.1"/>
  <content type="html">Fixes for Zigbee</content></entry>
<entry><id>tag:github.com,2008:Repository/1/2026.10.0</id><title>2026.10.0</title>
  <link rel="alternate" href="https://github.com/home-assistant/core/releases/tag/2026.10.0"/></entry>
</feed>"""


class FeedParsingTest(unittest.TestCase):
    def test_rss_and_atom(self):
        rss = ocwatch.feed_items(RSS)
        self.assertEqual([i["title"] for i in rss], ["Postgres 17 is out", "Weekly notes", "Rust tips"])
        self.assertEqual(rss[0]["summary"], "Big release")
        self.assertEqual(rss[0]["link"], "https://b.org/1")
        self.assertEqual(len({i["id"] for i in rss}), 3)
        atom = ocwatch.feed_items(ATOM)
        self.assertEqual(atom[0]["title"], "2026.10.1")
        self.assertTrue(atom[0]["link"].endswith("/tag/2026.10.1"))
        self.assertEqual(atom[0]["summary"], "Fixes for Zigbee")

    def test_only_the_newest_items_count(self):
        many = "<rss><channel>" + "".join(f"<item><title>t{i}</title></item>" for i in range(80)) + "</channel></rss>"
        self.assertEqual(len(ocwatch.feed_items(many)), ocwatch.FEED_LIMIT)

    def test_conditions(self):
        self.assertEqual(ocwatch.split_condition("https://x/feed| Postgres, rust ;"), ("https://x/feed", ["postgres", "rust"]))
        self.assertEqual(ocwatch.split_condition("topic"), ("topic", []))
        item = {"title": "Postgres 17", "summary": ""}
        self.assertTrue(ocwatch.mentions(item, []))
        self.assertTrue(ocwatch.mentions(item, ["postgres"]))
        self.assertFalse(ocwatch.mentions(item, ["mysql"]))

    def test_github_targets(self):
        for t in ("home-assistant/core", "https://github.com/home-assistant/core",
                  "https://github.com/home-assistant/core.git", "https://github.com/home-assistant/core/releases"):
            self.assertEqual(ocwatch.github_feed(t),
                             ("https://github.com/home-assistant/core/releases.atom", "home-assistant/core"), t)
        self.assertIsNone(ocwatch.github_feed("not a repo"))


class FeedWatchTest(unittest.TestCase):
    """The watcher itself, with the network replaced by fixed feeds."""

    def setUp(self):
        self.saved = ocwatch.fetch, ocwatch.Watch._connect
        ocwatch.Watch._connect = lambda self: None
        self.feed = RSS
        ocwatch.fetch = lambda url, limit=0: self.feed
        self.w = ocwatch.Watch(chat_id=1)

    def tearDown(self):
        ocwatch.fetch, ocwatch.Watch._connect = self.saved

    def test_three_new_items_make_one_grouped_alert(self):
        # The first pass only records (the watcher never alerts on it).
        first = self.w._fetch_state({"id": 1, "kind": "rss", "target": "https://b.org/feed", "last_state": None})
        self.feed = RSS.replace("<channel><title>Blog</title>", "<channel><title>Blog</title>" + "".join(
            f"<item><title>Fresh {i}</title><guid>n{i}</guid></item>" for i in range(3)))
        state = self.w._fetch_state({"id": 1, "kind": "rss", "target": "https://b.org/feed", "last_state": first})
        detail = self.w._detail[1]
        self.assertEqual(detail.count("•"), 3)
        for i in range(3):
            self.assertIn(f"Fresh {i}", detail)
        # Next pass, nothing new: no alert.
        self.w._fetch_state({"id": 1, "kind": "rss", "target": "https://b.org/feed", "last_state": state})
        self.assertNotIn(1, self.w._detail)

    def test_condition_filters_but_still_remembers(self):
        empty = "<rss><channel></channel></rss>"
        self.feed = empty
        self.assertIsNone(self.w._fetch_state({"id": 2, "kind": "rss", "target": "https://b.org/feed|postgres", "last_state": "x"}))
        self.feed = RSS
        state = self.w._fetch_state({"id": 2, "kind": "rss", "target": "https://b.org/feed|postgres", "last_state": "0"})
        self.assertEqual(self.w._detail[2], "• Postgres 17 is out")  # the two others don't mention it
        self.w._fetch_state({"id": 2, "kind": "rss", "target": "https://b.org/feed|postgres", "last_state": state})
        self.assertNotIn(2, self.w._detail)

    def test_github_releases(self):
        seen = []
        ocwatch.fetch = lambda url, limit=0: seen.append(url) or ATOM
        self.w._fetch_state({"id": 3, "kind": "github", "target": "home-assistant/core", "last_state": "0"})
        self.assertEqual(seen, ["https://github.com/home-assistant/core/releases.atom"])
        self.assertIn("2026.10.1", self.w._detail[3])


class WatchTargetTest(unittest.TestCase):
    def test_the_api_normalises_and_refuses(self):
        import mav_api  # noqa: PLC0415

        t = mav_api.watch_target
        self.assertEqual(t("github", "https://github.com/a/b/releases"), "a/b")
        self.assertEqual(t("github", "a/b| beta ,  rc "), "a/b|beta , rc")
        self.assertEqual(t("rss", "https://x.org/feed|"), "https://x.org/feed")
        self.assertEqual(t("price", "https://shop/p|49.9"), "https://shop/p|49.9")
        self.assertEqual(t("news", "Lyon strike|metro"), "Lyon strike|metro")
        self.assertIsNone(t("rss", "file:///etc/passwd"))
        self.assertIsNone(t("rss", "javascript:alert(1)"))
        self.assertIsNone(t("github", "nope"))
        self.assertIsNone(t("web", "|x"))


if __name__ == "__main__":
    unittest.main()
