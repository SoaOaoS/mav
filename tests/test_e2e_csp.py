"""The web app under its own Content-Security-Policy: nothing it does is
blocked (no inline script, no eval, no stray origin).

The other browser tests bypass the policy (Playwright's wait_for_function
evaluates strings); this one keeps it and only uses selectors.

Run: python3 -m unittest tests.test_e2e_csp -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_support import Stack, launch, signed_in, sync_playwright, watch_errors  # noqa: E402


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class CspE2E(unittest.TestCase):
    def test_the_app_runs_under_its_policy(self):
        with Stack(engine_args=("--word-delay", "0")) as stack:
            pw = sync_playwright().start()
            self.addCleanup(pw.stop)
            try:
                browser = launch(pw)
            except Exception as exc:  # noqa: BLE001
                self.skipTest(f"no Chromium: {exc}")
            self.addCleanup(browser.close)
            context = signed_in(browser, stack, bypass_csp=False)
            page = context.new_page()
            errors = watch_errors(page)
            blocked: list = []
            page.on("console", lambda m: "Content Security Policy" in m.text and blocked.append(m.text))
            page.goto(stack.url)
            page.wait_for_selector("#chatInput", state="visible", timeout=10000)
            page.fill("#chatInput", "hello under a strict policy")
            page.click("#sendBtn")
            page.wait_for_selector(".msg.mav .bubble:has-text('You said')", timeout=15000)
            for view in ("#routines", "#memory", "#settings/general", "#settings/model"):
                page.goto(stack.url + view)
                page.wait_for_selector(".view.is-active", timeout=5000)
            page.wait_for_timeout(500)
            # Google Fonts may be unreachable here; that is a network error,
            # never a policy one.
            self.assertEqual(blocked, [])
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
