"""Each version of Mav has only its own parts (dashboard/server/mav_edition.py):
self-hosted has everything; MyMav (Mav Cloud, your key) has no family,
password, backup, updates, advanced or webhook; CloudMav has neither those
nor the model settings, costs and debates.

Run: python3 -m unittest tests.test_editions -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_security import Server  # noqa: E402

import mav_api  # noqa: E402
import mav_edition  # noqa: E402

E = mav_edition


def as_edition(name: str):
    feats = E.table()[name]
    return mock.patch.multiple(E, EDITION=name, FEATURES=feats)


class TableTest(unittest.TestCase):
    def test_who_has_what(self):
        t = E.table()
        self.assertTrue(all(t["self"].values()), "self-hosted has everything")
        for part in ("family", "password", "backup", "updates", "advanced", "webhook", "code_setting"):
            self.assertFalse(t["mymav"][part], part)
            self.assertFalse(t["cloudmav"][part], part)
        for part in ("model", "usage", "debates"):
            self.assertTrue(t["mymav"][part], part)
            self.assertFalse(t["cloudmav"][part], part)

    def test_the_edition_comes_from_the_environment(self):
        cases = [({}, "self"), ({"MAV_EDITION": "mymav"}, "mymav"), ({"MAV_EDITION": "CloudMav"}, "cloudmav"),
                 ({"MAV_MODEL_MANAGED": "1"}, "cloudmav"), ({"MAV_EDITION": "nonsense"}, "self")]
        for env, want in cases:
            with mock.patch.dict(os.environ, env, clear=False):
                for k in ("MAV_EDITION", "MAV_MODEL_MANAGED"):
                    if k not in env:
                        os.environ.pop(k, None)
                self.assertEqual(E._edition(), want, env)

    def test_routes(self):
        off = E.table()["cloudmav"]
        self.assertEqual(E.off_feature("POST", "/api/family/add", off), "family")
        self.assertEqual(E.off_feature("GET", "/api/backup", off), "backup")
        self.assertEqual(E.off_feature("POST", "/api/hooks/event", off), "webhook")
        self.assertEqual(E.off_feature("POST", "/api/config/provider", off), "model")
        self.assertIsNone(E.off_feature("GET", "/api/config/provider", off))  # reading is harmless
        self.assertIsNone(E.off_feature("POST", "/api/config/restart", off))  # connections need it
        self.assertIsNone(E.off_feature("POST", "/api/config/mcp", off))
        self.assertIsNone(E.off_feature("POST", "/api/familyx", off))
        self.assertIsNone(E.off_feature("POST", "/api/family/add", E.table()["self"]))


class ApiTest(Server):
    def test_the_cloud_refuses_what_it_does_not_have(self):
        with as_edition("mymav"):
            for method, path, body in (("POST", "/api/family/add", {"name": "Léa", "password": "x" * 10}),
                                       ("GET", "/api/backup", None),
                                       ("POST", "/api/update", {}),
                                       ("POST", "/api/webhook/new", {}),
                                       ("POST", "/api/config/code", {"enabled": True})):
                st, res, _ = self.req(method, path, body)
                self.assertEqual(st, 404, path)
                self.assertIn("version of Mav", res["error"])
            state = self.req("GET", "/api/auth/state")[1]
            self.assertEqual(state["edition"], "mymav")
            self.assertFalse(state["features"]["family"])
            self.assertTrue(state["features"]["model"])

    def test_cloudmav_has_no_model_settings_nor_costs(self):
        with as_edition("cloudmav"), mock.patch.object(mav_api.mav_engine, "provider_save") as save:
            st, _, _ = self.req("POST", "/api/config/provider", {"provider": "openai", "model": "x"})
            self.assertIn(st, (403, 404))
            st, _, _ = self.req("POST", "/api/usage/budget", {"monthly": 5})
            self.assertEqual(st, 404)
            save.assert_not_called()

    def test_self_hosted_keeps_everything(self):
        with as_edition("self"), mock.patch.object(mav_api.mav_engine, "code_state",
                                                   return_value={"enabled": False}):
            st, _, _ = self.req("GET", "/api/config/code")
            self.assertEqual(st, 200)
            self.assertTrue(all(self.req("GET", "/api/auth/state")[1]["features"].values()))


class CloudExtrasTest(unittest.TestCase):
    def test_home_only_connections_and_providers_are_hidden(self):
        eng = mav_api.mav_engine
        with mock.patch.object(eng, "read_mcp", return_value={"mcp": {}}):
            with as_edition("self"):
                ids = {i["id"] for i in eng.mcp_catalog()["items"]}
                presets = {p["id"] for p in eng.provider_snapshot()["presets"]}
            self.assertIn("files", ids)
            self.assertIn("ollama", presets)
            with as_edition("mymav"):
                ids = {i["id"] for i in eng.mcp_catalog()["items"]}
                presets = {p["id"] for p in eng.provider_snapshot()["presets"]}
                self.assertFalse(eng.provider_save({"provider": "ollama", "model": "llama3"})["ok"])
                self.assertFalse(eng.install_from_catalog("files", {"path": "/data"})["ok"])
            self.assertNotIn("files", ids)
            self.assertNotIn("browser", ids)
            self.assertIn("fetch", ids)
            self.assertNotIn("ollama", presets)
            self.assertIn("openrouter", presets)


if __name__ == "__main__":
    unittest.main()
