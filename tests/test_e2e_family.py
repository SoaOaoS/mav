"""Family accounts in the browser: the owner adds a person, who signs in with
their name and gets their own Mav — without the owner's chats or settings.

Run: python3 -m unittest tests.test_e2e_family -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_support import PASSWORD, Stack, launch, new_context, signed_in, sync_playwright, wait_or_explain, watch_errors  # noqa: E402

ALEX_PW = "alex-password-1"


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class FamilyE2E(unittest.TestCase):
    def setUp(self):
        self.stack = Stack(engine_args=("--word-delay", "0"))
        self.stack.__enter__()
        self.addCleanup(self.stack.__exit__, None, None, None)
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        try:
            self.browser = launch(self.pw)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no Chromium: {exc}")
        self.addCleanup(self.browser.close)

    def open(self, context):
        page = context.new_page()
        errors = watch_errors(page)
        self.addCleanup(lambda: self.assertEqual(errors, [], "JavaScript errors on the page"))
        return page

    def test_owner_adds_a_person_who_gets_their_own_mav(self):
        owner = signed_in(self.browser, self.stack)
        self.addCleanup(owner.close)
        owner.request.post(self.stack.url + "api/session/new", data={"title": "Owner secret plans"})
        page = self.open(owner)
        page.goto(self.stack.url + "#settings/general")
        page.wait_for_selector("#familyRow:not([hidden])", timeout=10000)
        page.click("#familyAdd")
        page.wait_for_selector("#famName", timeout=3000)
        page.fill("#famName", "Alex")
        page.fill("#famPw", ALEX_PW)
        page.click("#modalFoot .btn-primary")
        wait_or_explain(page, self.stack, "#familyList :text('Alex')")

        # Alex, on another device: the sign-in now asks for a name.
        alex = new_context(self.browser)
        self.addCleanup(alex.close)
        page = self.open(alex)
        page.goto(self.stack.url)
        page.wait_for_selector("#authName:not([hidden])", timeout=10000)
        page.fill("#authName", "Alex")
        page.fill("#authPassword", ALEX_PW)
        page.click("#authSubmit")
        wait_or_explain(page, self.stack, "#authGate", "hidden")
        # The welcome flow runs for Alex too, without the model step's form.
        page.wait_for_selector("#onboarding:not([hidden])", timeout=10000)
        self.assertTrue(page.locator("#obModelReady").is_visible())
        page.click("#obSkip")
        page.wait_for_selector("#chatInput", state="visible", timeout=10000)

        self.assertEqual(page.evaluate("document.body.dataset.role"), "member")
        self.assertNotIn("Owner secret plans", page.locator("#convList").inner_text())
        page.goto(self.stack.url + "#settings/model")
        page.wait_for_selector("#spanel-general.is-active", timeout=5000)
        for sel in ("[data-stab='model']", "[data-stab='helpers']", "#backupDownload", "#familyRow",
                    "[data-view='debates']"):
            self.assertFalse(page.locator(sel).is_visible(), sel)
        self.assertIn("Alex", page.locator("#accountText").inner_text())

        # Alex's first chat is Alex's alone.
        page.goto(self.stack.url)
        page.fill("#chatInput", "hello from Alex")
        page.click("#sendBtn")
        page.wait_for_function("location.hash.startsWith('#chat/')", timeout=10000)
        owner_list = owner.request.get(self.stack.url + "api/sessions").json()["sessions"]
        self.assertEqual([s["title"] for s in owner_list], ["Owner secret plans"])

    def test_the_owner_still_signs_in_without_a_name(self):
        owner = signed_in(self.browser, self.stack)
        owner.request.post(self.stack.url + "api/family/add", data={"name": "Alex", "password": ALEX_PW})
        owner.close()
        context = new_context(self.browser)
        self.addCleanup(context.close)
        page = self.open(context)
        page.goto(self.stack.url)
        page.wait_for_selector("#authName:not([hidden])", timeout=10000)
        page.fill("#authPassword", PASSWORD)
        page.click("#authSubmit")
        wait_or_explain(page, self.stack, "#authGate", "hidden")
        # The page reloads signed in, then knows who it is for.
        page.wait_for_function("document.body && document.body.dataset.role === 'owner'", timeout=10000)
        self.assertTrue(page.locator("[data-stab='model']").count())


if __name__ == "__main__":
    unittest.main()
