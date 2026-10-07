"""The first-run welcome, end to end in a real browser (fake engine).

Skipped when Playwright (and a Chromium) is not installed. Locally:
    pip install playwright && playwright install chromium
    python3 -m unittest tests.test_e2e_onboarding -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_support import PASSWORD, Stack, launch, sync_playwright  # noqa: E402


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class OnboardingE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No model yet: the welcome flow is where it gets connected.
        cls.stack = Stack(model="").__enter__()
        cls.url = cls.stack.url

    @classmethod
    def tearDownClass(cls):
        cls.stack.__exit__(None, None, None)

    def test_welcome_flow(self):
        with sync_playwright() as pw:
            try:
                b = launch(pw)
            except Exception as exc:  # noqa: BLE001
                self.skipTest(f"no Chromium: {exc}")
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(self.url)
            pg.request.post(self.url + "api/auth/setup", data={"password": PASSWORD})
            pg.goto(self.url)
            pg.wait_for_selector("#onboarding:not([hidden])", timeout=8000)

            # 1. model: Ollama needs no key
            pg.click('[data-obprov="ollama"]')
            pg.fill("#obModel", "llama3.1")
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="2"]:not([hidden])', timeout=8000)
            # 2. about you
            pg.fill("#obCity", "Toulouse")
            pg.select_option("#obLang", "en")
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="3"]:not([hidden])', timeout=8000)
            # 3. routines: briefing (on by default) + the first template
            pg.locator("#obRoutines input[type=checkbox]").first.check()
            pg.click("#obNext")
            pg.wait_for_selector('.ob-step[data-ob="4"]:not([hidden])', timeout=8000)
            self.assertIn("2 routines", pg.inner_text("#obSummary"))
            # 4. first briefing opens its chat
            pg.click("#obNext")
            pg.wait_for_function("location.hash.startsWith('#chat/')", timeout=8000)
            self.assertTrue(pg.locator("#onboarding").is_hidden())

            # Done once: a reload does not show it again.
            pg.reload()
            pg.wait_for_timeout(1500)
            self.assertTrue(pg.locator("#onboarding").is_hidden())
            # The overlay's styles never leak onto the chat's own greeting.
            pg.click(".new-chat")
            pg.wait_for_selector("div.welcome h1", timeout=5000)
            pos = pg.evaluate("getComputedStyle(document.querySelector('div.welcome')).position")
            self.assertNotEqual(pos, "fixed")
            self.assertEqual(errors, [])
            b.close()
