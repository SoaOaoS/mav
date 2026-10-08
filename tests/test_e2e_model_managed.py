"""CloudMav in a real browser: the plan's model is not a setting.

Run: python3 -m unittest tests.test_e2e_model_managed -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_support import Stack, launch, new_context, sync_playwright, watch_errors  # noqa: E402


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class ModelManagedE2E(unittest.TestCase):
    def test_no_model_settings_in_cloudmav(self):
        # As Mav Cloud runs it: sign-in is the platform's, the model the plan's.
        with Stack(env={"MAV_MODEL_MANAGED": "1", "MAV_AUTH": "off"}) as stack, sync_playwright() as pw:
            try:
                browser = launch(pw)
            except Exception as exc:  # noqa: BLE001
                self.skipTest(f"no Chromium: {exc}")
            page = new_context(browser).new_page()
            errors = watch_errors(page)
            page.goto(stack.url)
            # The welcome flow says the model is included, with nothing to fill in.
            page.wait_for_selector("#onboarding:not([hidden])", timeout=10000)
            self.assertIn("CloudMav", page.locator("#obModelReady").inner_text())
            self.assertFalse(page.locator("#obModelForm").is_visible())
            page.click("#obSkip")
            # Settings open on General; the Model tab and the background model are gone.
            page.goto(stack.url + "#settings/model")
            page.wait_for_selector("#spanel-general.is-active", timeout=5000)
            self.assertFalse(page.locator("[data-stab='model']").is_visible())
            self.assertFalse(page.locator("#smallModel").is_visible())
            res = page.request.post(stack.url + "api/config/provider", data={"preset": "openai", "key": "x"})
            self.assertEqual(res.status, 403)
            self.assertEqual(errors, [])
            browser.close()


if __name__ == "__main__":
    unittest.main()
