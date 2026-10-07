"""Docker mode: no systemd — restarts go through a flag file the engine and
worker containers watch (docker/entrypoint.sh), updates are `compose pull`.

Run: python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402


class DockerModeTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.saved = (mav_api.IN_DOCKER, mav_api.RUNTIME, mav_api.RESTART_FLAG, mav_api.ENGINE_STARTED)
        mav_api.IN_DOCKER, mav_api.RUNTIME = True, "docker"
        mav_api.RESTART_FLAG = tmp / "run" / "engine.restart"
        mav_api.ENGINE_STARTED = tmp / "run" / "engine.started"

    def tearDown(self):
        (mav_api.IN_DOCKER, mav_api.RUNTIME, mav_api.RESTART_FLAG, mav_api.ENGINE_STARTED) = self.saved

    def test_restart_touches_the_flag(self):
        mav_api.mark_pending("Model")
        r = mav_api.restart_engine()
        self.assertTrue(r["ok"])
        self.assertTrue(mav_api.RESTART_FLAG.is_file())
        self.assertEqual(mav_api.pending_changes(), [])

    def test_engine_start_time_comes_from_the_container(self):
        self.assertIsNone(mav_api.engine_started_at())
        mav_api.ENGINE_STARTED.parent.mkdir(parents=True)
        mav_api.ENGINE_STARTED.write_text("1791354847\n")
        self.assertEqual(mav_api.engine_started_at(), 1791354847.0)

    def test_update_explains_compose(self):
        self.assertFalse(mav_api.update_running())
        r = mav_api.start_update()
        self.assertFalse(r["ok"])
        self.assertTrue(r["docker"])
        self.assertIn("docker compose pull", r["error"])

    def test_server_unit_needs_no_systemctl(self):
        self.assertIn("Docker", mav_api.server_unit())


class ComposeFilesTest(unittest.TestCase):
    """The files a Docker user touches stay consistent with each other."""

    def test_compose_runs_the_three_roles_and_postgres(self):
        text = (ROOT / "docker-compose.yml").read_text()
        for svc in ("postgres:", "engine:", "web:", "worker:"):
            self.assertIn(f"\n  {svc}", text)
        for role in ('["engine"]', '["web"]', '["worker"]'):
            self.assertIn(role, text)
        self.assertIn("ghcr.io/soaoaos/mav:", text)
        self.assertIn("mav-data:/data", text)

    def test_env_example_covers_what_compose_reads(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        example = (ROOT / ".env.example").read_text()
        import re
        for var in sorted(set(re.findall(r"\$\{([A-Z_]+)(?::-[^}]*)?\}", compose))):
            self.assertIn(var, example, f"{var} is read by docker-compose.yml but not in .env.example")

    def test_entrypoint_knows_every_role(self):
        text = (ROOT / "docker" / "entrypoint.sh").read_text()
        for role in ("engine)", "worker)", "web)"):
            self.assertIn(role, text)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("docker/entrypoint.sh", dockerfile)
        self.assertIn("opencode-ai", dockerfile)


if __name__ == "__main__":
    unittest.main()
