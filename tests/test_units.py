"""Unit tests for the pure-Python parts (no database, no engine, no network).

Run: python3 -m unittest discover -s tests -v
"""

import json
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_provider  # noqa: E402
import ocjobs  # noqa: E402
import ocmemory  # noqa: E402
import ocwatch  # noqa: E402


class PriceParsing(unittest.TestCase):
    def test_structured_data(self):
        page = '<script type="application/ld+json">{"price":"129.99","priceCurrency":"EUR"}</script>'
        self.assertEqual(ocwatch.find_price(page), (129.99, "EUR"))

    def test_meta_tag(self):
        self.assertEqual(ocwatch.find_price('<meta property="product:price:amount" content="49.50">')[0], 49.5)

    def test_visible_european_format(self):
        self.assertEqual(ocwatch.find_price("<b>1 299,00 €</b>"), (1299.0, "EUR"))

    def test_visible_us_format(self):
        self.assertEqual(ocwatch.find_price("<p>Now $1,049.99!</p>"), (1049.99, "USD"))

    def test_target(self):
        self.assertEqual(ocwatch.split_price_target("https://x/p | 50"), ("https://x/p", 50.0))

    def test_visible_text(self):
        html = "<head><title>t</title></head><script>x=1</script><p>Hello&nbsp; <b>world</b></p>"
        self.assertEqual(ocwatch.visible_text(html), "Hello world")


class NewsWatch(unittest.TestCase):
    def test_new_headlines_only(self):
        feeds = [
            "<rss><channel><item><title>A</title><link>http://a</link></item></channel></rss>",
            "<rss><channel><item><title>B</title><link>http://b</link></item>"
            "<item><title>A</title><link>http://a</link></item></channel></rss>",
        ]
        orig = ocwatch.fetch
        try:
            w = ocwatch.Watch.__new__(ocwatch.Watch)
            w._detail = {}
            ocwatch.fetch = lambda url, limit=0: feeds[0]
            first = w._fetch_state({"id": 1, "kind": "news", "target": "x", "last_state": None})
            ocwatch.fetch = lambda url, limit=0: feeds[1]
            w._fetch_state({"id": 1, "kind": "news", "target": "x", "last_state": first})
            self.assertEqual(w._detail[1], "• B")
        finally:
            ocwatch.fetch = orig


class Routines(unittest.TestCase):
    def test_interval(self):
        job = {"name": "x", "prompt": "p", "every_minutes": 60}
        now = datetime(2026, 1, 5, 10, 0)
        self.assertTrue(ocjobs.due(job, now, None))
        self.assertFalse(ocjobs.due(job, now, "2026-01-05 09:30"))
        self.assertTrue(ocjobs.due(job, now, "2026-01-05 09:00"))

    def test_daily_time_and_days(self):
        job = {"name": "x", "prompt": "p", "time": "08:00", "days": ["mon"]}
        self.assertTrue(ocjobs.due(job, datetime(2026, 1, 5, 8, 0), None))  # a Monday
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 6, 8, 0), None))
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 5, 8, 0), "2026-01-05 08:00"))

    def test_validation(self):
        self.assertTrue(ocjobs.validate({"name": "a", "prompt": "p", "every_minutes": 30}))
        self.assertFalse(ocjobs.validate({"name": "a", "prompt": "p"}))
        self.assertFalse(ocjobs.validate({"name": "a", "prompt": "", "time": "08:00"}))


class Provider(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / ".config/opencode"
        self.cfg.mkdir(parents=True)
        (self.cfg / "opencode.json").write_text(json.dumps({"mcp": {"x": {"type": "remote", "url": "u"}}}))
        self.env = self.tmp / "server.env"
        self.dash = self.tmp / "dash.env"
        self.dash.write_text("OPENCODE_MODEL=old/x\nOTHER=1\n")

    def test_custom_provider_keeps_key_out_of_json(self):
        res = mav_provider.apply(self.cfg, self.env, "ollama-cloud-api", "gpt-oss:120b",
                                 api_key="sk-1", env_files=[self.dash])
        self.assertTrue(res["ok"])
        cfg = json.loads((self.cfg / "opencode.json").read_text())
        self.assertEqual(cfg["model"], "ollama-cloud-api/gpt-oss:120b")
        self.assertEqual(cfg["provider"]["ollama-cloud-api"]["options"]["apiKey"], "{env:OLLAMA_API_KEY}")
        self.assertIn("x", cfg["mcp"])  # untouched
        self.assertIn("OLLAMA_API_KEY=sk-1", self.env.read_text())
        self.assertIn("OPENCODE_MODEL=ollama-cloud-api/gpt-oss:120b", self.dash.read_text())
        self.assertIn("OTHER=1", self.dash.read_text())

    def test_native_provider_has_no_block(self):
        mav_provider.apply(self.cfg, self.env, "anthropic", "claude-sonnet-4-5", api_key="k")
        cfg = json.loads((self.cfg / "opencode.json").read_text())
        self.assertNotIn("anthropic", cfg.get("provider", {}))
        cur = mav_provider.current(self.cfg, self.env)
        self.assertTrue(cur["has_key"])
        self.assertEqual(cur["ref"], "anthropic/claude-sonnet-4-5")

    def test_blank_key_keeps_existing(self):
        mav_provider.apply(self.cfg, self.env, "openai", "gpt-4o", api_key="first")
        mav_provider.apply(self.cfg, self.env, "openai", "gpt-4o-mini", api_key=None)
        self.assertIn("OPENAI_API_KEY=first", self.env.read_text())

    def test_rejects_bad_input(self):
        self.assertFalse(mav_provider.apply(self.cfg, self.env, "Bad Id!", "m")["ok"])
        self.assertFalse(mav_provider.apply(self.cfg, self.env, "openai", "")["ok"])


class MemoryRecall(unittest.TestCase):
    def test_and_query_needs_several_terms(self):
        self.assertEqual(ocmemory.ts_query_and("postgres"), "")
        q = ocmemory.ts_query_and("postgres migration config")
        self.assertIn("&", q)
        self.assertNotIn("|", q)

    def test_or_query_is_broad(self):
        self.assertIn("|", ocmemory.ts_query("postgres migration config"))

    def test_queries_are_alnum_only(self):
        for fn in (ocmemory.ts_query, ocmemory.ts_query_and):
            for term in re.split(r"[&|]", fn("l'ete 2026 : test/etrange")):
                term = term.strip()
                if term:
                    self.assertRegex(term, r"^[a-z0-9]+:\*$")

    def test_dedupe_keeps_newest_and_drops_contained(self):
        facts = [
            "User lives in Lyon, France",  # newest
            "User lives in Lyon",
            "User is vegetarian",
            "User likes hiking in the Alps",
        ]
        out = ocmemory._dedupe_facts(facts)
        self.assertEqual(
            out,
            ["User lives in Lyon, France", "User is vegetarian", "User likes hiking in the Alps"],
        )

    def test_context_block_respects_budget(self):
        class Fake(ocmemory.Memory):
            def facts(self, chat_id, limit=20):
                return [{"fact": f"Fact number {i} " + "x" * 60, "ts": i} for i in range(40)]

            def search(self, chat_id, query, top=3):
                return [{"q": "q " + "y" * 200, "a": "a " + "z" * 400, "ts": 0}] * 20

        block = Fake(Path("/nonexistent"), max_entries=5).context_block(0, "anything", top=20)
        self.assertIn("<memory>", block)
        self.assertIn("</memory>", block)
        self.assertLessEqual(len(block), ocmemory.MEMORY_BUDGET + 200)

    def test_context_block_empty_when_nothing(self):
        class Empty(ocmemory.Memory):
            def facts(self, chat_id, limit=20):
                return []

            def search(self, chat_id, query, top=3):
                return []

        self.assertEqual(Empty(Path("/nonexistent")).context_block(0, "q"), "")


class Catalog(unittest.TestCase):
    def test_catalog_is_valid(self):
        cat = json.loads((ROOT / "dashboard/mcp-catalog.json").read_text())
        ids = [i["id"] for i in cat["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        for it in cat["items"]:
            self.assertIn(it["type"], ("local", "remote"))
            if it["type"] == "local":
                self.assertIsInstance(it["command"], list)
            else:
                self.assertTrue(it["url"])
            keys = {i["key"] for i in it.get("inputs", [])}
            used = set()
            for v in json.dumps({k: it.get(k) for k in ("command", "url", "headers", "environment")}).split("{{")[1:]:
                used.add(v.split("}}")[0])
            self.assertEqual(used, keys, it["id"])


if __name__ == "__main__":
    unittest.main()
