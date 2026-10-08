"""Mav Cloud's included plan (CloudMav): the platform gives Mav its model, so
nobody may change the model, its key or the background model.

Run: python3 -m unittest tests.test_model_managed -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_security import Server  # noqa: E402

import mav_api  # noqa: E402


class ManagedModelTest(Server):
    def test_the_model_cannot_be_changed(self):
        with mock.patch.object(mav_api, "MODEL_MANAGED", True), \
             mock.patch.object(mav_api.mav_engine, "provider_save") as save, \
             mock.patch.object(mav_api.mav_engine, "provider_test") as test:
            for path, body in (("/api/config/provider", {"preset": "openai", "key": "sk-x", "model": "gpt"}),
                               ("/api/config/provider/test", {"preset": "openai", "key": "sk-x"}),
                               ("/api/usage/small-model", {"model": "openai/gpt-mini"})):
                st, res, _ = self.req("POST", path, body)
                self.assertEqual(st, 403, path)
                self.assertIn("managed", res["error"])
            save.assert_not_called()
            test.assert_not_called()
            # The app is told, to hide the model settings.
            self.assertTrue(self.req("GET", "/api/auth/state")[1]["model_managed"])

    def test_your_own_model_stays_yours(self):
        with mock.patch.object(mav_api, "MODEL_MANAGED", False), \
             mock.patch.object(mav_api.mav_engine, "provider_save", return_value={"ok": True}) as save:
            st, _, _ = self.req("POST", "/api/config/provider", {"preset": "openai", "key": "sk-x", "model": "gpt"})
            self.assertEqual(st, 200)
            save.assert_called_once()
            self.assertFalse(self.req("GET", "/api/auth/state")[1]["model_managed"])


if __name__ == "__main__":
    unittest.main()
