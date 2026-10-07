"""The web app end to end, in Chromium against the fake engine.

Sign in, send a message and see the tool steps in order, create a routine,
reload a chat and keep its history, use the phone layout. Skipped when
Playwright is not installed; CI installs it.

Run: python3 -m unittest tests.test_e2e_app -v
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_support import PASSWORD, Stack, launch, signed_in, sync_playwright, watch_errors  # noqa: E402


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class AppE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = Stack(engine_args=("--word-delay", "0.01")).__enter__()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = launch(cls.pw)
        except Exception as exc:  # noqa: BLE001
            cls.pw.stop()
            cls.stack.__exit__(None, None, None)
            raise unittest.SkipTest(f"no Chromium: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.stack.__exit__(None, None, None)

    def page(self, **ctx):
        context = signed_in(self.browser, self.stack, **ctx)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = watch_errors(page)
        self.addCleanup(lambda: self.assertEqual(errors, [], "JavaScript errors on the page"))
        page.goto(self.stack.url)
        page.wait_for_selector("#chatInput", state="visible", timeout=10000)
        return page

    def send(self, page, text: str) -> None:
        page.fill("#chatInput", text)
        page.click("#sendBtn")

    # ------------------------------------------------------------------ tests
    def test_1_sign_in(self):
        """First visit asks for a password; afterwards it asks to sign in."""
        with Stack() as stack:
            context = self.browser.new_context()
            page = context.new_page()
            page.goto(stack.url)
            page.wait_for_selector("#authGate:not([hidden])", timeout=8000)
            page.fill("#authPassword", PASSWORD)
            page.fill("#authPassword2", PASSWORD)
            page.click("#authSubmit")
            page.wait_for_selector("#authGate", state="hidden", timeout=8000)
            context.close()
            # A new device: wrong password first, then the right one.
            context = self.browser.new_context()
            page = context.new_page()
            page.goto(stack.url)
            page.wait_for_selector("#authGate:not([hidden])", timeout=8000)
            self.assertTrue(page.locator("#authPassword2").is_hidden())
            page.fill("#authPassword", "not-the-password")
            page.click("#authSubmit")
            page.wait_for_selector("#authError:not([hidden])", timeout=5000)
            page.fill("#authPassword", PASSWORD)
            page.click("#authSubmit")
            page.wait_for_selector("#authGate", state="hidden", timeout=8000)
            context.close()

    def test_2_message_shows_tool_steps_in_order(self):
        page = self.page()
        self.send(page, "please research the best bakeries in Lyon")
        # The helper step and the page it read, then the answer itself.
        page.wait_for_function("document.querySelectorAll('.tool-step').length >= 2", timeout=15000)
        page.wait_for_function(
            "[...document.querySelectorAll('.bubble')].some(b => b.textContent.includes('You said'))",
            timeout=20000)
        numbers = page.locator(".tool-step .tool-n").all_inner_texts()
        self.assertGreaterEqual(len(numbers), 2)
        self.assertEqual(numbers, [str(i + 1) for i in range(len(numbers))])
        # A step opens to show its details.
        page.locator(".tool-step summary").first.click()
        page.wait_for_selector(".tool-step[open] .tool-body", timeout=3000)

    def test_3_create_a_routine(self):
        page = self.page()
        page.goto(self.stack.url + "#routines")
        page.click("#routineNew")
        page.fill("textarea[name=prompt]", "Tell me if I need an umbrella today.")
        page.fill("input[name=name]", "Umbrella")
        page.fill("input[name=time]", "07:30")
        page.click("#modalFoot .btn-primary")
        page.wait_for_selector("#routineList :text('Umbrella')", timeout=8000)
        jobs = json.loads((self.stack.tmp / "jobs.json").read_text())
        job = next(j for j in jobs if j["name"] == "Umbrella")
        self.assertEqual(job["time"], "07:30")
        self.assertIn("umbrella", job["prompt"])

    def test_4_reload_keeps_the_history(self):
        page = self.page()
        self.send(page, "remember the word pistachio")
        page.wait_for_function("location.hash.startsWith('#chat/')", timeout=10000)
        page.wait_for_function(
            "[...document.querySelectorAll('.bubble')].some(b => b.textContent.includes('You said'))",
            timeout=20000)
        url = page.url
        page.reload()
        page.wait_for_function(
            "[...document.querySelectorAll('.bubble')].some(b => b.textContent.includes('pistachio'))",
            timeout=10000)
        self.assertEqual(page.url, url)
        texts = " ".join(page.locator(".bubble").all_inner_texts())
        self.assertIn("pistachio", texts)
        self.assertIn("You said", texts)
        # The question and its answer each show once after the reload.
        self.assertEqual(page.locator(".msg.me").count(), 1)
        self.assertEqual(texts.count("You said"), 1)

    def test_5_phone_layout(self):
        page = self.page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        self.assertTrue(page.locator("#menuBtn").is_visible())
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        self.assertFalse(overflow, "the page scrolls sideways on a phone")
        page.click("#menuBtn")
        page.wait_for_function(
            "(() => { const r = document.querySelector('#sidebar').getBoundingClientRect();"
            " return r.left >= -1 && r.right > 100; })()", timeout=3000)
        page.click("#sidebar [data-view='routines']")
        page.wait_for_function("location.hash.startsWith('#routines')", timeout=3000)
        self.send_from_phone(page)

    def send_from_phone(self, page):
        page.goto(self.stack.url)
        page.wait_for_selector("#chatInput", state="visible", timeout=8000)
        self.send(page, "hello from my phone")
        page.wait_for_function(
            "[...document.querySelectorAll('.bubble')].some(b => b.textContent.includes('hello from my phone'))",
            timeout=15000)


if __name__ == "__main__":
    unittest.main()
