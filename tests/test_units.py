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

# Bot modules first: mav_api inserts the *installed* BOT_DIR on sys.path, so
# importing it first could shadow these with a different copy on the machine.
import mav_provider  # noqa: E402
import ocactions  # noqa: E402
import occonditions  # noqa: E402
import ocdrafts  # noqa: E402
import ocevents  # noqa: E402
import ocinterests  # noqa: E402
import ocjobs  # noqa: E402
import ocmail  # noqa: E402
import ocmemory  # noqa: E402
import ocpriority  # noqa: E402
import ocpursuit  # noqa: E402
import ocroutine_nl  # noqa: E402
import ocroutine_templates  # noqa: E402
import ocselfinit  # noqa: E402
import ocwatch  # noqa: E402
import mav_api  # noqa: E402


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

    def test_a_missed_minute_is_caught_up_once(self):
        job = {"name": "x", "prompt": "p", "time": "08:00"}
        late = datetime(2026, 1, 5, 8, 3, 20)  # the worker was busy or restarting at 08:00
        self.assertTrue(ocjobs.due(job, late, "2026-01-04 08:00"))
        self.assertEqual(ocjobs.run_slot(job, late), datetime(2026, 1, 5, 8, 0))
        self.assertFalse(ocjobs.due(job, late, "2026-01-05 08:00"))  # already ran for 08:00
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 5, 8, 5), None))  # too late
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 5, 7, 59), None))  # not yet

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

    def test_the_cloud_model_behind_the_proxy(self):
        """Mav Cloud's CloudMav: the plan's model through the edge's proxy,
        given with or without its provider prefix."""
        for model in ("anthropic/claude-haiku-5-5", "claude-haiku-5-5"):
            res = mav_provider.apply(self.cfg, self.env, "anthropic", model,
                                     base_url="https://app.example/llm/anthropic/v1", api_key="tok")
            self.assertTrue(res["ok"], res)
            cfg = json.loads((self.cfg / "opencode.json").read_text())
            self.assertEqual(cfg["model"], "anthropic/claude-haiku-5-5")
            block = cfg["provider"]["anthropic"]
            self.assertEqual(block["options"]["baseURL"], "https://app.example/llm/anthropic/v1")
            self.assertIn("claude-haiku-5-5", block["models"])
        self.assertIn("ANTHROPIC_API_KEY=tok", self.env.read_text())

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


class PlainSummary(unittest.TestCase):
    def test_drops_directives_and_images(self):
        answer = (
            "## Marchés\nCAC 40 [[chart:^FCHI:1mo]] en baisse.\n"
            "[[file:rapport.md]]\n![graphe](/tmp/x.png)\nFin."
        )
        out = ocjobs.plain_summary(answer, limit=0)
        self.assertNotIn("[[", out)
        self.assertNotIn("](", out)
        self.assertIn("CAC 40", out)
        self.assertIn("Fin.", out)

    def test_truncates(self):
        out = ocjobs.plain_summary("a" * 500, limit=220)
        self.assertLessEqual(len(out), 220)
        self.assertTrue(out.endswith("…"))

    def test_empty(self):
        self.assertEqual(ocjobs.plain_summary("", limit=220), "")


class ChartData(unittest.TestCase):
    def test_rejects_bad_symbol(self):
        for bad in ("", "SPY; rm -rf", "a b", "x" * 40):
            with self.assertRaises(ValueError):
                mav_api.chart_data(bad)

    def test_shape_and_cache(self):
        calls = []

        def fake(sym, rng):
            calls.append((sym, rng))
            return [10.0, 11.0, 12.0], {"shortName": "Test", "currency": "USD"}

        orig = mav_api._yahoo_closes
        mav_api._chart_cache.clear()
        try:
            mav_api._yahoo_closes = fake
            out = mav_api.chart_data("SPY", "1mo")
            self.assertEqual(out["symbol"], "SPY")
            self.assertEqual(out["price"], 12.0)
            self.assertEqual(out["name"], "Test")
            self.assertAlmostEqual(out["range_pct"], 20.0)
            self.assertAlmostEqual(out["change_pct"], (12 - 11) / 11 * 100)
            self.assertEqual(len(out["series"]), 3)
            mav_api.chart_data("SPY", "1mo")
            self.assertEqual(len(calls), 1)  # second hit served from cache
            mav_api.chart_data("SPY", "5d")
            self.assertEqual(len(calls), 2)
        finally:
            mav_api._yahoo_closes = orig
            mav_api._chart_cache.clear()

    def test_bad_range_falls_back(self):
        orig = mav_api._yahoo_closes
        mav_api._chart_cache.clear()
        seen = {}
        try:
            mav_api._yahoo_closes = lambda s, r: (seen.setdefault("r", r), [1.0, 2.0], {})[1:]
            mav_api.chart_data("SPY", "bogus")
            self.assertEqual(seen["r"], "1mo")
        finally:
            mav_api._yahoo_closes = orig
            mav_api._chart_cache.clear()


class Downloads(unittest.TestCase):
    # /tmp/opencode is one of the allowed asset roots in a normal install.
    def setUp(self):
        root = Path("/tmp/opencode")
        if root not in mav_api.ASSET_ROOTS:
            mav_api.ASSET_ROOTS.append(root)
        root.mkdir(parents=True, exist_ok=True)

    def test_any_type_is_downloadable(self):
        # Any extension is served now (the dashboard can hand back any file).
        p = Path("/tmp/opencode/mav-test-binary.exe")
        p.write_text("MZ")
        try:
            res = mav_api.download_response(str(p))
            self.assertIsNotNone(res)
            self.assertEqual(res[2], "mav-test-binary.exe")
        finally:
            p.unlink(missing_ok=True)

    def test_sensitive_files_blocked(self):
        for name in ("prod.env", ".env", "server.key", "secret-api-key.txt",
                     "mail.conf", "push_subs.json", ".netrc"):
            p = Path("/tmp/opencode") / name
            p.write_text("SECRET")
            try:
                self.assertIsNone(
                    mav_api.download_response(str(p)), f"{name} should be blocked"
                )
                self.assertTrue(mav_api.is_sensitive(p), name)
            finally:
                p.unlink(missing_ok=True)

    def test_dotenv_in_a_folder_blocked(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as d:
            p = Path(d) / ".env.local"
            p.write_text("TOKEN=x")
            self.assertIsNone(mav_api.download_response(str(p)))

    def test_serves_allowed_file(self):
        p = Path("/tmp/opencode/mav-test-rapport.md")
        p.write_text("# Salut")
        try:
            data, mime, name = mav_api.download_response(str(p))
            self.assertEqual(data, b"# Salut")
            self.assertTrue(mime.startswith("text/markdown"))
            self.assertEqual(name, "mav-test-rapport.md")
        finally:
            p.unlink(missing_ok=True)

    def test_bare_name_is_resolved(self):
        p = Path("/tmp/opencode/mav-test-bare.csv")
        p.write_text("a,b\n1,2\n")
        try:
            data, _mime, name = mav_api.download_response("mav-test-bare.csv")
            self.assertEqual(name, "mav-test-bare.csv")
            self.assertIn(b"a,b", data)
        finally:
            p.unlink(missing_ok=True)

    def test_outside_root_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "secret.md"
            p.write_text("nope")
            self.assertIsNone(mav_api.download_response(str(p)))
        self.assertIsNone(mav_api.resolve_download("/etc/passwd"))


class RoutineNL(unittest.TestCase):
    def test_english(self):
        d = ocroutine_nl.detect("every monday at 8:30 send me the report")
        self.assertEqual(d["days"], ["mon"])
        self.assertEqual(d["time"], "08:30")
        self.assertEqual(d["mode"], "weekly")

    def test_french(self):
        d = ocroutine_nl.detect("tous les matins à 7h résume mon agenda")
        self.assertEqual(d["lang"], "fr")
        self.assertEqual(d["time"], "07:00")
        self.assertEqual(d["mode"], "daily")

    def test_french_weekly(self):
        d = ocroutine_nl.detect("chaque vendredi envoie le rapport")
        self.assertEqual(d["days"], ["fri"])
        self.assertEqual(d["mode"], "weekly")

    def test_spanish(self):
        d = ocroutine_nl.detect("cada día a las 9 dame el tiempo")
        self.assertEqual(d["lang"], "es")
        self.assertEqual(d["time"], "09:00")

    def test_interval(self):
        d = ocroutine_nl.detect("toutes les 3 heures vérifie le serveur")
        self.assertEqual(d["mode"], "interval")
        self.assertEqual(d["every_minutes"], 180)

    def test_weekdays(self):
        d = ocroutine_nl.detect("on weekdays remind me to stretch")
        self.assertEqual(d["days"], ["mon", "tue", "wed", "thu", "fri"])

    def test_nothing_recurring(self):
        self.assertIsNone(ocroutine_nl.detect("what is the capital of France?"))
        self.assertIsNone(ocroutine_nl.detect("/remember I live in Lyon"))

    def test_what_is_stripped(self):
        d = ocroutine_nl.detect("every morning at 7 give me the weather")
        self.assertNotIn("7", d["what"])
        self.assertIn("weather", d["what"])


class FlexibleSchedules(unittest.TestCase):
    def test_monthly_days(self):
        job = {"name": "x", "prompt": "p", "time": "09:00", "days_of_month": [1, 15]}
        self.assertTrue(ocjobs.due(job, datetime(2026, 1, 1, 9, 0), None))
        self.assertTrue(ocjobs.due(job, datetime(2026, 1, 15, 9, 0), None))
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 2, 9, 0), None))

    def test_last_day_of_month(self):
        job = {"name": "x", "prompt": "p", "time": "18:00", "last_day_of_month": True}
        self.assertTrue(ocjobs.due(job, datetime(2026, 1, 31, 18, 0), None))
        self.assertFalse(ocjobs.due(job, datetime(2026, 2, 27, 18, 0), None))
        self.assertTrue(ocjobs.due(job, datetime(2026, 2, 28, 18, 0), None))

    def test_event_job_never_due_by_clock(self):
        job = {"name": "x", "prompt": "p", "on_event": {"kind": "github"}}
        self.assertTrue(ocjobs.validate(job))
        self.assertFalse(ocjobs.due(job, datetime(2026, 1, 1, 9, 0), None))

    def test_snooze_blocks(self):
        now = datetime(2026, 1, 1, 9, 0)
        job = {"name": "x", "prompt": "p", "time": "09:00",
               "snooze_until": int(now.timestamp()) + 3600}
        self.assertTrue(ocjobs.snoozed(job, now))
        self.assertFalse(ocjobs.due(job, now, None))

    def test_validate_monthly(self):
        self.assertTrue(ocjobs.validate({"name": "x", "prompt": "p", "time": "09:00", "days_of_month": [3]}))
        self.assertFalse(ocjobs.validate({"name": "x", "prompt": "p", "time": "09:00", "days_of_month": ["nope"]}))


class Conditions(unittest.TestCase):
    def test_text_contains(self):
        cond = {"type": "text_contains", "value": "pluie"}
        self.assertTrue(occonditions.evaluate(cond, source="averses et pluie"))
        self.assertFalse(occonditions.evaluate(cond, source="grand soleil"))

    def test_negate(self):
        cond = {"type": "text_contains", "value": "pluie", "negate": True}
        self.assertFalse(occonditions.evaluate(cond, source="pluie"))
        self.assertTrue(occonditions.evaluate(cond, source="soleil"))

    def test_number(self):
        cond = {"type": "number", "value": 3, "op": ">"}
        self.assertTrue(occonditions.evaluate(cond, source="5 nouveaux mails"))
        self.assertFalse(occonditions.evaluate(cond, source="2 mails"))

    def test_weekday(self):
        self.assertTrue(occonditions.evaluate({"type": "weekday", "value": "weekend"}, weekday="sat"))
        self.assertFalse(occonditions.evaluate({"type": "weekday", "value": "weekend"}, weekday="mon"))

    def test_unknown_allows(self):
        self.assertTrue(occonditions.evaluate({"type": "nonsense"}))


class Events(unittest.TestCase):
    def test_matches_kind(self):
        job = {"on_event": {"kind": "github"}}
        self.assertTrue(ocevents.matches(job, {"kind": "github", "payload": {}}))
        self.assertFalse(ocevents.matches(job, {"kind": "iot", "payload": {}}))

    def test_matches_contains(self):
        job = {"on_event": {"kind": "github", "contains": "opened"}}
        self.assertTrue(ocevents.matches(job, {"kind": "github", "payload": {"action": "opened"}}))
        self.assertFalse(ocevents.matches(job, {"kind": "github", "payload": {"action": "closed"}}))

    def test_no_subscription(self):
        self.assertFalse(ocevents.matches({"prompt": "p"}, {"kind": "any"}))

    def test_any_kind(self):
        self.assertTrue(ocevents.matches({"on_event": {"kind": "any"}}, {"kind": "form"}))


class Priority(unittest.TestCase):
    def test_critical(self):
        self.assertEqual(ocpriority.classify("Payment failed")["level"], "critical")

    def test_important(self):
        self.assertEqual(ocpriority.classify("Réunion demain à 9h")["level"], "important")

    def test_useful_default(self):
        self.assertEqual(ocpriority.classify("Bilan du mois")["level"], "useful")
        self.assertEqual(ocpriority.classify("un truc random")["level"], "useful")

    def test_should_push_by_level(self):
        self.assertFalse(ocpriority.should_push("useful", "quiet"))
        self.assertTrue(ocpriority.should_push("critical", "quiet"))
        self.assertTrue(ocpriority.should_push("important", "normal"))
        self.assertFalse(ocpriority.should_push("useful", "normal"))
        self.assertTrue(ocpriority.should_push("fyi", "chatty"))


class DraftsAndActions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_drafts_crud(self):
        d = ocdrafts.Drafts(self.tmp / "drafts.json")
        d._pg = None  # force the file backend
        d.backend = "file"
        did = d.add(0, "reply", "Re: facture", "Bonjour, voici…")
        self.assertIsNotNone(did)
        self.assertEqual(len(d.list("pending")), 1)
        d.set_status(did, "sent")
        self.assertEqual(len(d.list("pending")), 0)
        self.assertEqual(len(d.list("sent")), 1)
        d.delete(did)
        self.assertEqual(len(d.list("all")), 0)

    def test_draft_recipient_and_edit(self):
        d = ocdrafts.Drafts(self.tmp / "drafts2.json")
        d._pg = None
        d.backend = "file"
        did = d.add(0, "reply", "Re: devis", "Bonjour", to="a@b.fr", subject="Re: devis")
        got = d.get(did)
        self.assertEqual(got["email_to"], "a@b.fr")
        self.assertEqual(got["email_subject"], "Re: devis")
        d.update(did, body="Bonjour, corrigé", to="c@d.fr")
        got = d.get(did)
        self.assertEqual(got["body"], "Bonjour, corrigé")
        self.assertEqual(got["email_to"], "c@d.fr")
        self.assertEqual(got["email_subject"], "Re: devis")  # untouched

    def test_mail_config_roundtrip(self):
        import mav_mail

        conf = self.tmp / "mail.conf"
        self.assertFalse(mav_mail.status(conf)["configured"])
        mav_mail.save("imap.x.tld", "smtp.x.tld", "me@x.tld", "secret", conf)
        st = mav_mail.status(conf)
        self.assertTrue(st["configured"])
        self.assertTrue(st["has_password"])
        self.assertNotIn("secret", json.dumps(st))  # never leaks the password
        mav_mail.forget(conf)
        self.assertFalse(mav_mail.status(conf)["configured"])

    def test_mail_send_requires_config(self):
        import mav_mail

        conf = self.tmp / "empty.conf"
        r = mav_mail.send("a@b.fr", "Hi", "Body", path=conf)
        self.assertFalse(r["ok"])

    def test_mail_reply_sets_thread_headers(self):
        import smtplib
        import mav_mail
        import email as _email

        conf = self.tmp / "reply.conf"
        mav_mail.save("imap.x.tld", "smtp.x.tld", "me@x.tld", "pw", conf)
        captured = {}

        class FakeSMTP:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, *a):
                pass

            def send_message(self, msg):
                captured["msg"] = msg

        orig = smtplib.SMTP_SSL
        smtplib.SMTP_SSL = FakeSMTP
        try:
            r = mav_mail.send(
                "a@b.fr", "Re: devis", "Bonjour",
                in_reply_to="<orig@mail.gmail.com>", path=conf,
            )
        finally:
            smtplib.SMTP_SSL = orig
        self.assertTrue(r["ok"])
        self.assertTrue(r["threaded"])
        parsed = _email.message_from_string(captured["msg"].as_string())
        self.assertEqual(parsed["In-Reply-To"], "<orig@mail.gmail.com>")
        self.assertIn("<orig@mail.gmail.com>", parsed["References"])

    def test_reply_subject(self):

        self.assertEqual(ocmail.reply_subject("Facture"), "Re: Facture")
        self.assertEqual(ocmail.reply_subject("Re: Facture"), "Re: Facture")
        self.assertEqual(ocmail.reply_subject("RE: x"), "RE: x")

    def test_mail_addr_extraction(self):

        self.assertEqual(ocmail._addr("Ethan <soa@x.fr>"), "soa@x.fr")
        self.assertEqual(ocmail._addr("plain@x.fr"), "plain@x.fr")
        self.assertEqual(ocmail._addr(""), "")

    def test_actions_lifecycle(self):
        a = ocactions.Actions(self.tmp / "actions.json")
        a._pg = None
        a.backend = "file"
        aid = a.add(0, "Research", "task", "./#chat/x")
        a.update(aid, "running")
        self.assertEqual(a.list("running")[0]["id"], aid)
        a.update(aid, "done", result="Fini")
        self.assertEqual(a.get(aid)["status"], "done")
        self.assertEqual(a.get(aid)["result"], "Fini")


class ProactivityAPI(unittest.TestCase):
    def test_schedule_monthly(self):
        sched = mav_api._schedule_from_payload(
            {"schedule_mode": "monthly", "time": "09:00", "days_of_month": "1,15"}
        )
        self.assertEqual(sched["days_of_month"], [1, 15])

    def test_schedule_monthly_needs_a_day(self):
        sched = mav_api._schedule_from_payload({"schedule_mode": "monthly", "time": "09:00"})
        self.assertIn("_error", sched)

    def test_schedule_event(self):
        sched = mav_api._schedule_from_payload(
            {"schedule_mode": "event", "event_kind": "github", "event_contains": "opened"}
        )
        self.assertEqual(sched["on_event"], {"kind": "github", "contains": "opened"})

    def test_condition_from_payload(self):
        cond = mav_api._condition_from_payload(
            {"condition_type": "number", "condition_value": "3", "condition_op": ">"}
        )
        self.assertEqual(cond, {"type": "number", "value": "3", "op": ">"})
        self.assertIsNone(mav_api._condition_from_payload({"condition_type": "none"}))

    def test_template_to_job(self):
        r = mav_api.template_to_job("morning-brief")
        self.assertTrue(r["ok"])
        self.assertEqual(r["job"]["name"], "Morning brief")  # English by default
        self.assertIn("time", r["job"])
        fr = mav_api.template_to_job("morning-brief", lang="fr")
        self.assertEqual(fr["job"]["name"], "Brief du matin")
        self.assertIn("météo", fr["job"]["prompt"])

    def test_every_template_has_an_english_wording(self):
        for t in ocroutine_templates.TEMPLATES:
            en = ocroutine_templates.localized(t, "en")
            self.assertIn(t["id"], ocroutine_templates.EN, t["id"])
            self.assertTrue(en["label"] and en["description"] and en["prompt"])
            self.assertEqual(en["when"], t["when"])

    def test_detect_endpoint_shape(self):
        r = mav_api.detect_routine("tous les lundis à 8h envoie le rapport")
        self.assertIsNotNone(r["draft"])
        self.assertEqual(r["draft"]["days"], ["mon"])


class Templates(unittest.TestCase):
    def test_catalog_shape(self):
        jobs = ocroutine_templates.as_jobs()
        self.assertGreaterEqual(len(jobs), 5)
        ids = [t["id"] for t in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        for t in jobs:
            self.assertTrue(t["label"])
            self.assertTrue(t["prompt"])
            self.assertIn("when", t)

    def test_all_templates_have_valid_when(self):
        for t in ocroutine_templates.TEMPLATES:
            when = t.get("when") or {}
            self.assertTrue(
                "last_day_of_month" in when
                or "days_of_month" in when
                or "time" in when
                or "every_minutes" in when,
                t["id"],
            )


class InterestDetection(unittest.TestCase):
    def test_like_detected(self):
        obs = ocinterests.detect_observations("J'adore le PSG et je vais au match samedi")
        self.assertTrue(obs)
        self.assertEqual(obs[0]["polarity"], "like")
        self.assertEqual(obs[0]["entity"], "PSG")
        self.assertEqual(obs[0]["category"], "sport")
        self.assertEqual(obs[0]["key"], "psg")

    def test_dislike_detected(self):
        obs = ocinterests.detect_observations("je déteste l'OM, franchement")
        self.assertTrue(obs)
        self.assertEqual(obs[0]["polarity"], "dislike")

    def test_english_like(self):
        obs = ocinterests.detect_observations("I love the Lakers, big fan")
        self.assertTrue(obs)
        self.assertEqual(obs[0]["polarity"], "like")
        self.assertEqual(obs[0]["category"], "sport")

    def test_no_interest_returns_empty(self):
        self.assertEqual(ocinterests.detect_observations("Quel temps fait-il ?"), [])

    def test_clause_split_two_polarities(self):
        obs = ocinterests.detect_observations("j'aime le Real mais je déteste le Barça")
        pols = {o["polarity"] for o in obs}
        self.assertIn("like", pols)
        self.assertIn("dislike", pols)


class InterestScoring(unittest.TestCase):
    def test_decay_halves_over_half_life(self):
        now = 1_000_000_000
        one_hl = now - int(ocinterests.HALF_LIFE_DAYS * 86400)
        self.assertAlmostEqual(ocinterests.decay(1.0, one_hl, now=now), 0.5, places=3)

    def test_blend_is_asymptotic(self):
        s = 0.0
        for _ in range(50):
            s = ocinterests.blend_score(s, 1.0, kind="explicit")
        self.assertLess(s, 1.0)
        self.assertGreater(s, 0.9)

    def test_confidence_conflict_caps(self):
        self.assertGreater(ocinterests.confidence_of(2, 1), 0.4)
        self.assertLessEqual(ocinterests.confidence_of(2, 1, conflicted=True), 0.25)

    def test_pick_cadence(self):
        self.assertEqual(ocinterests.pick_cadence(0.9, 0.9), "weekly")
        self.assertEqual(ocinterests.pick_cadence(0.6, 0.5), "biweekly")
        self.assertEqual(ocinterests.pick_cadence(0.2, 0.1), "quarterly")


class InterestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ocinterests.Interests(self.tmp / "interests.json", chat_id=7)
        self.store._pg = None  # force the JSON backend, no Postgres in tests
        self.store.backend = "file"

    def test_add_and_list(self):
        self.store.add("Cyber", category="tech", cadence="weekly")
        items = self.store.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["label"], "Cyber")
        self.assertEqual(items[0]["polarity"], "like")

    def test_observe_strengthens(self):
        self.store.learn_from_text("j'adore la cyber et le pentest")
        first = self.store.get("cyber")
        self.store.learn_from_text("vraiment, j'aime la cyber")
        second = self.store.get("cyber")
        self.assertGreater(second["score"], first["score"])
        self.assertGreaterEqual(len(second["evidence"]), 2)

    def test_contradiction_flags_conflicted(self):
        self.store.learn_from_text("j'aime le PSG")
        self.assertEqual(self.store.get("psg")["polarity"], "like")
        self.store.learn_from_text("en fait je déteste le PSG")
        rec = self.store.get("psg")
        self.assertTrue(rec["conflicted"])
        ok, why = ocinterests.should_pursue(rec)
        self.assertFalse(ok)
        self.assertEqual(why, "conflicted evidence")

    def test_dislike_never_pursued(self):
        self.store.add("OM", polarity="dislike")
        self.assertFalse(ocinterests.should_pursue(self.store.get("om"))[0])

    def test_feedback_downvote_mutes(self):
        self.store.add("Jazz", category="music")
        self.store.feedback("jazz", False)
        rec = self.store.get("jazz")
        self.assertTrue(rec["muted"])
        self.assertEqual(rec["cadence"], "off")

    def test_touch_engaged_raises_score(self):
        self.store.add("Linux", category="tech")
        before = self.store.get("linux")["score"]
        self.store.touch("linux", engaged=True)
        self.assertGreater(self.store.get("linux")["score"], before)


class Pursuit(unittest.TestCase):
    def test_headline_matches_entity(self):
        interest = {"key": "psg", "label": "PSG", "entity": "PSG", "polarity": "like"}
        items = [
            {"title": "Transfert record au Real Madrid", "link": "u1", "id": "a"},
            {"title": "Le PSG s'impose en Ligue des champions", "link": "u2", "id": "b"},
        ]
        hit = ocpursuit.headline_for(interest, items)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["ref"], "b")

    def test_no_match_returns_none(self):
        interest = {"key": "psg", "label": "PSG", "entity": "PSG"}
        items = [{"title": "La météo de demain", "link": "u", "id": "x"}]
        self.assertIsNone(ocpursuit.headline_for(interest, items))

    def test_seen_ref_skipped(self):
        interest = {"key": "psg", "label": "PSG", "entity": "PSG"}
        items = [{"title": "PSG champion", "link": "u", "id": "b"}]
        self.assertIsNone(ocpursuit.headline_for(interest, items, seen_ref="b"))

    def test_matches_single_entity(self):
        interest = {"key": "btc", "label": "Bitcoin", "entity": "BTC"}
        self.assertGreaterEqual(ocpursuit.matches(interest, "BTC hits a new high"), 0.5)


class SelfInit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.jobs = self.tmp / "jobs.json"
        self.store = ocinterests.Interests(self.tmp / "interests.json", chat_id=7)
        self.store._pg = None
        self.store.backend = "file"
        self.store.add("Cyber", category="tech", cadence="weekly", source="manual")

    def test_watchable_rules(self):
        self.assertTrue(ocselfinit.watchable(self.store.get("cyber")))
        self.store.add("OM", polarity="dislike")
        self.assertFalse(ocselfinit.watchable(self.store.get("om")))
        self.store.update("cyber", muted=True)
        self.assertFalse(ocselfinit.watchable(self.store.get("cyber")))

    def test_check_minutes_by_cadence(self):
        cyber = self.store.get("cyber")
        cyber["cadence"] = "weekly"
        self.assertEqual(ocselfinit.check_minutes(cyber), ocselfinit.CHECK_MINUTES["weekly"])
        cyber["pinned"] = True
        self.assertEqual(ocselfinit.check_minutes(cyber), ocselfinit.PINNED_CHECK_MINUTES)

    def test_plan_creates_watchdog(self):
        diff = ocselfinit.plan_jobs(self.store.list(), [])
        self.assertEqual(len(diff["create"]), 1)
        job = diff["create"][0]
        self.assertEqual(job["source"], "interest")
        self.assertEqual(job["interest_key"], "cyber")
        self.assertEqual(job["every_minutes"], ocselfinit.CHECK_MINUTES["weekly"])

    def test_reconcile_suggest_writes_nothing(self):
        import json as _json

        self.jobs.write_text("[]")
        ocselfinit.reconcile(self.store, self.jobs, autonomy="suggest")
        self.assertEqual(_json.loads(self.jobs.read_text()), [])

    def test_reconcile_auto_applies(self):
        import json as _json

        self.jobs.write_text("[]")
        res = ocselfinit.reconcile(self.store, self.jobs, autonomy="auto")
        self.assertTrue(res["applied"])
        jobs = _json.loads(self.jobs.read_text())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["interest_key"], "cyber")

    def test_never_shadows_handmade(self):
        hand = {"name": ocselfinit.routine_name(self.store.get("cyber")),
                "prompt": "mine", "every_minutes": 60}
        diff = ocselfinit.plan_jobs(self.store.list(), [hand])
        self.assertEqual(diff["create"], [])

    def test_vetoed_auto_kept(self):
        existing = ocselfinit.routine_for(self.store.get("cyber"))
        existing["enabled"] = False
        diff = ocselfinit.plan_jobs(self.store.list(), [existing])
        self.assertEqual(diff["create"], [])
        self.assertEqual(len(diff["vetoed"]), 1)

    def test_retire_when_interest_cools(self):
        existing = ocselfinit.routine_for(self.store.get("cyber"))
        diff = ocselfinit.plan_jobs([], [existing])
        self.assertEqual(len(diff["retire"]), 1)


class RunRegistry(unittest.TestCase):
    """The run buffer decouples generation from the HTTP request."""

    def _make(self, events):
        run = mav_api.Run("s1", "hi", "assistant", [])
        # Replace the worker with a deterministic event emitter.
        run._work = lambda: [run._emit(e, d) for (e, d) in events]
        return run

    def test_buffer_accumulates_text_and_tools(self):
        run = self._make([
            ("start", {"agent": "assistant", "recalled": 0}),
            ("delta", {"delta": "Hello "}),
            ("delta", {"delta": "world"}),
            ("tool", {"id": "c1", "name": "bash", "status": "running"}),
            ("tool", {"id": "c1", "name": "bash", "status": "completed"}),
            ("tool", {"id": "c2", "name": "task", "status": "running", "detail": "writer"}),
            ("reset", {"text": "Hello"}),
            ("delta", {"delta": " world"}),
            ("done", {"text": "Hello world"}),
        ])
        run.start()
        run._thread.join(timeout=3)
        snap = run.snapshot()
        self.assertEqual(snap["text"], "Hello world")
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["tools"], [
            {"id": "c1", "name": "bash", "status": "completed", "detail": ""},
            {"id": "c2", "name": "task", "status": "running", "detail": "writer"},
        ])
        self.assertEqual(snap["seq"], 9)

    def test_follow_replays_from_cursor(self):
        run = self._make([
            ("delta", {"delta": "a"}),
            ("delta", {"delta": "b"}),
            ("done", {"text": "ab"}),
        ])
        run.start()
        run._thread.join(timeout=3)
        replay = "".join(run.follow(from_seq=2))
        self.assertIn("b", replay)
        self.assertNotIn('"delta": "a"', replay)
        self.assertIn("done", replay)

    def test_interrupt_keeps_partial_text(self):
        run = self._make([
            ("delta", {"delta": "partial answer"}),
            ("done", {"text": "partial answer", "interrupted": True}),
        ])
        run.start()
        run._thread.join(timeout=3)
        snap = run.snapshot()
        self.assertTrue(snap["interrupted"])
        self.assertEqual(snap["text"], "partial answer")  # nothing erased

    def test_error_sets_status(self):
        run = self._make([("error", {"message": "boom"})])
        run.start()
        run._thread.join(timeout=3)
        snap = run.snapshot()
        self.assertEqual(snap["status"], "error")
        self.assertEqual(snap["error"], "boom")

    def test_runs_view_lists_active(self):
        mav_api.RUNS.clear()
        run = self._make([("done", {"text": "x"})])
        mav_api.RUNS["s1"] = run
        run.start()
        run._thread.join(timeout=3)
        view = mav_api.runs_view()
        self.assertTrue(any(v["session"] == "s1" for v in view))
        mav_api.RUNS.clear()

    def test_parse_sse_roundtrip(self):
        block = mav_api._sse("delta", {"delta": "café"})
        ev, d = mav_api._parse_sse(block)
        self.assertEqual(ev, "delta")
        self.assertEqual(d["delta"], "café")


if __name__ == "__main__":
    unittest.main()
