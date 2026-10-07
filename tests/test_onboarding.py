"""First-run welcome: when it shows, and what each step saves.

Run: python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1")

import mav_api  # noqa: E402


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.saved = (mav_api.ONBOARDING_FILE, mav_api.JOBS_FILE, mav_api.memory_action, mav_api.add_interest)
        mav_api.ONBOARDING_FILE = tmp / "onboarding.json"
        mav_api.JOBS_FILE = tmp / "jobs.json"
        self.facts, self.interests = [], []
        mav_api.memory_action = lambda action, p: (self.facts.append(p["fact"]), {"ok": True})[1]
        mav_api.add_interest = lambda p: (self.interests.append(p["label"]), {"ok": True})[1]

    def tearDown(self):
        (mav_api.ONBOARDING_FILE, mav_api.JOBS_FILE, mav_api.memory_action, mav_api.add_interest) = self.saved

    def test_a_fresh_install_is_welcomed_once(self):
        self.assertFalse(mav_api.get_onboarding()["done"])
        mav_api.set_onboarding(True)
        self.assertTrue(mav_api.get_onboarding()["done"])

    def test_an_existing_install_is_never_asked(self):
        mav_api.write_json(mav_api.JOBS_FILE, [{"name": "Inbox", "prompt": "x", "time": "08:00"}])
        self.assertTrue(mav_api.get_onboarding()["done"])

    def test_the_briefing_alone_does_not_count_as_history(self):
        mav_api.write_json(mav_api.JOBS_FILE, [{"name": "Daily briefing", "kind": "briefing", "prompt": "x"}])
        self.assertFalse(mav_api.get_onboarding()["done"])

    def test_profile_becomes_facts_and_interests(self):
        r = mav_api.onboarding_profile({
            "name": "Alex", "city": "Toulouse", "language": "fr",
            "interests": "running, tech news ,, Formula 1",
        })
        self.assertEqual(r["facts"], 3)
        self.assertEqual(r["interests"], 3)
        self.assertIn("Their name is Alex.", self.facts)
        self.assertTrue(any("Toulouse" in f for f in self.facts))
        self.assertIn("Prefers answers in French.", self.facts)
        self.assertEqual(self.interests, ["running", "tech news", "Formula 1"])

    def test_empty_profile_saves_nothing(self):
        r = mav_api.onboarding_profile({"language": "xx"})
        self.assertEqual((r["facts"], r["interests"]), (0, 0))

    @unittest.skipIf(mav_api.ocroutine_templates is None, "templates unavailable")
    def test_routines_from_templates_and_the_briefing(self):
        ids = [t["id"] for t in mav_api.ocroutine_templates.TEMPLATES][1:3]
        r = mav_api.onboarding_routines({"templates": ids, "briefing": {"enabled": True, "time": "06:45"}})
        self.assertEqual(len(r["created"]), 2, r)
        jobs = mav_api.read_json(mav_api.JOBS_FILE, [])
        names = {j["name"] for j in jobs}
        for n in r["created"]:
            self.assertIn(n, names)
            self.assertRegex(n, mav_api.JOB_NAME_RE)
        brief = [j for j in jobs if j.get("kind") == "briefing"]
        self.assertEqual(brief[0]["time"], "06:45")
        # Running it twice does not duplicate anything.
        again = mav_api.onboarding_routines({"templates": ids})
        self.assertEqual(again["created"], [])

    def test_job_names_from_accented_labels_are_valid(self):
        for label in ("Récap du soir", "Bilan du mois", "☀️ Brief", "été"):
            self.assertRegex(mav_api._job_name(label), mav_api.JOB_NAME_RE)


if __name__ == "__main__":
    unittest.main()
