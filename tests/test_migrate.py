"""scripts/migrate-to-docker.sh, run against a fake installer install with
fake `docker`, `systemctl` and `id` commands (no Docker, no root needed).

Run: python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "docker $*" >>"$FAKE_LOG"
case "$*" in
  "compose version") exit 0 ;;
  "inspect -f "*) echo mav_pgdata ;;
  "volume inspect mav_mav-data") exit 1 ;;
  "exec mav-postgres pg_dump"*) echo "-- PostgreSQL database dump" ;;
  "compose run "*) tar -xpf - -C "$FAKE_DATA" ;;
esac
exit 0
"""


@unittest.skipUnless(shutil.which("bash") and shutil.which("tar"), "bash and tar needed")
class MigrateToDockerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = self.tmp
        # A clone of the repository (the script edits .env next to it).
        self.repo = t / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        shutil.copy(ROOT / "scripts" / "migrate-to-docker.sh", self.repo / "scripts")
        shutil.copy(ROOT / "docker-compose.yml", self.repo)
        shutil.copy(ROOT / ".env.example", self.repo)
        # The installer install.
        self.home = t / "home" / "alex"
        oc = self.home / ".config" / "opencode"
        (oc / "agent").mkdir(parents=True)
        (oc / "opencode.json").write_text(
            '{"model": "ollama/llama3.1", "provider": {"ollama": {"options": {"baseURL": "http://127.0.0.1:11434/v1"}}},'
            f' "instructions": ["{self.home}/notes.md"], "mcp": {{"fs": {{"command": ["x", "{self.home}"]}}}}}}'
        )
        (oc / "agent" / "assistant.md").write_text("mine\n")
        (self.home / ".local" / "share" / "opencode" / "storage").mkdir(parents=True)
        (self.home / ".local" / "share" / "opencode" / "storage" / "s1.json").write_text("{}")
        (self.home / "workspace" / "mav-files").mkdir(parents=True)
        (self.home / "workspace" / "mav-files" / "budget.csv").write_text("a,b\n")
        bot = self.home / "bot"
        (bot / "venv" / "bin").mkdir(parents=True)
        (bot / "__pycache__").mkdir()
        for name, text in [("jobs.json", "[]"), ("auth.json", "{}"), ("vapid_private.pem", "k"),
                           ("mav_worker.py", "code"), ("requirements.txt", "x"), ("__pycache__/a.pyc", "x")]:
            (bot / name).write_text(text)
        (bot / "media").mkdir()
        (bot / "media" / "index.json").write_text("[]")
        etc = t / "etc"
        (etc / "mav").mkdir(parents=True)
        self.env_dash = etc / "mav-dashboard.env"
        self.env_dash.write_text(
            f"MAV_STATIC=/opt/mav\nBOT_DIR={bot}\nOPENCODE_URL=http://127.0.0.1:4096\n"
            "OPENCODE_MODEL=ollama/llama3.1\nMAV_API_PORT=8443\nMAV_TLS_PORT=8444\n"
            f"MAV_USER_HOME={self.home}\nMAV_INSTALL_USER=alex\nMAV_DASH_UNIT=mav-dashboard\n"
            "PG_DSN=host=127.0.0.1 port=5433 user=mav password=Secret123abc dbname=mav connect_timeout=5\n"
        )
        (etc / "mav.env").write_text(
            f"BOT_DIR={bot}\nNOTIFY_QUIET=22-7\nJOBS_FILE={bot}/jobs.json\nMAV_CHAT_ID=1\n"
        )
        (etc / "mav-server.env").write_text("OLLAMA_BASE_URL=http://localhost:11434/v1\nANTHROPIC_API_KEY=sk-1\n")
        (etc / "mav" / "cli.env").write_text(
            "MAV_SERVER_UNIT=mav-server\nMAV_WORKER_UNIT=mav-worker\nMAV_DASH_UNIT=mav-dashboard\nMAV_PG_CONTAINER=mav-postgres\n"
        )
        self.old_compose = etc / "mav" / "docker-compose.yml"
        self.old_compose.write_text("services: {}\n")
        # Fake commands.
        fake = t / "bin"
        fake.mkdir()
        (fake / "docker").write_text(FAKE_DOCKER)
        (fake / "systemctl").write_text('#!/usr/bin/env bash\necho "systemctl $*" >>"$FAKE_LOG"\n')
        (fake / "id").write_text('#!/usr/bin/env bash\necho 0\n')
        (fake / "hostname").write_text('#!/usr/bin/env bash\necho 192.0.2.10\n')
        for f in fake.iterdir():
            f.chmod(0o755)
        self.data = t / "data"
        self.data.mkdir()
        self.log = t / "calls.log"
        self.env = {
            **os.environ,
            "PATH": f"{fake}:{os.environ['PATH']}",
            "FAKE_LOG": str(self.log), "FAKE_DATA": str(self.data),
            "MAV_ENV_DASH": str(self.env_dash), "MAV_ENV_BOT": str(etc / "mav.env"),
            "MAV_ENV_SERVER": str(etc / "mav-server.env"), "MAV_CLI_ENV": str(etc / "mav" / "cli.env"),
            "MAV_COMPOSE_FILE": str(self.old_compose), "MAV_BACKUP_DIR": str(t / "backups"),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args):
        return subprocess.run(["bash", str(self.repo / "scripts" / "migrate-to-docker.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def test_moves_everything_into_the_volume(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.data
        # Engine config and chat history, with paths rewritten for Docker.
        conf = (d / "home/.config/opencode/opencode.json").read_text()
        self.assertIn("http://host.docker.internal:11434/v1", conf)
        self.assertIn('"/data/home/notes.md"', conf)
        self.assertIn('"/data/home"]', conf)
        self.assertNotIn(str(self.home), conf)
        self.assertEqual((d / "home/.config/opencode/agent/assistant.md").read_text(), "mine\n")
        self.assertTrue((d / "home/.local/share/opencode/storage/s1.json").is_file())
        self.assertTrue((d / "home/workspace/mav-files/budget.csv").is_file())
        # The worker's data, not its code.
        for f in ("jobs.json", "auth.json", "vapid_private.pem", "media/index.json"):
            self.assertTrue((d / "bot" / f).is_file(), f)
        for f in ("mav_worker.py", "requirements.txt", "venv", "__pycache__"):
            self.assertFalse((d / "bot" / f).exists(), f)
        # Keys as they are (local services rewritten); settings without host paths.
        server = (d / "config/server.env").read_text()
        self.assertIn("ANTHROPIC_API_KEY=sk-1", server)
        self.assertIn("OLLAMA_BASE_URL=http://host.docker.internal:11434/v1", server)
        mav = (d / "config/mav.env").read_text()
        self.assertIn("OPENCODE_MODEL=ollama/llama3.1", mav)
        self.assertIn("NOTIFY_QUIET=22-7", mav)
        self.assertIn("MAV_CHAT_ID=1", mav)
        for key in ("BOT_DIR", "PG_DSN", "OPENCODE_URL", "MAV_API_PORT", "MAV_USER_HOME", "JOBS_FILE", "MAV_DASH_UNIT"):
            self.assertNotIn(key + "=", mav)

    def test_reuses_the_database_and_switches_over_in_order(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env = (self.repo / ".env").read_text()
        self.assertIn("POSTGRES_PASSWORD=Secret123abc", env)
        self.assertIn("MAV_PORT=8443", env)
        self.assertEqual(oct((self.repo / ".env").stat().st_mode & 0o777), "0o600")
        backups = list((self.tmp / "backups").glob("pre-docker-*.sql.gz"))
        self.assertEqual(len(backups), 1)
        # The old compose file is parked, so `mav uninstall` cannot stop the new stack.
        self.assertFalse(self.old_compose.exists())
        self.assertTrue(Path(str(self.old_compose) + ".pre-docker").exists())
        calls = self.log.read_text().splitlines()
        idx = lambda prefix: next(i for i, c in enumerate(calls) if c.startswith(prefix))  # noqa: E731
        for unit in ("mav-server", "mav-worker", "mav-dashboard"):
            self.assertIn(f"systemctl disable --now {unit}", calls)
        self.assertLess(idx("docker exec mav-postgres pg_dump"), idx("systemctl disable"))
        self.assertLess(idx("systemctl disable"), idx(f"docker compose -f {self.old_compose} down"))
        self.assertLess(idx(f"docker compose -f {self.old_compose} down"), idx("docker compose run"))
        self.assertLess(idx("docker compose run"), idx("docker compose up -d --wait"))

    def test_dry_run_changes_nothing(self):
        r = self.run_script("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.repo / ".env").exists())
        self.assertTrue(self.old_compose.exists())
        calls = self.log.read_text()
        self.assertNotIn("systemctl", calls)
        self.assertNotIn("compose run", calls)
        self.assertNotIn("compose up", calls)
        self.assertEqual(list(self.data.iterdir()), [])
        stage = r.stdout.split("are in ")[1].split()[0]
        shutil.rmtree(stage, ignore_errors=True)

    def test_refuses_when_docker_already_has_data(self):
        docker = Path(self.env["PATH"].split(":")[0]) / "docker"
        docker.write_text(FAKE_DOCKER.replace('"volume inspect mav_mav-data") exit 1', '"volume inspect mav_mav-data") exit 0'))
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already has data", r.stderr)
        self.assertNotIn("systemctl", self.log.read_text())

    def test_refuses_a_non_default_database(self):
        self.env_dash.write_text(self.env_dash.read_text().replace("user=mav", "user=bob"))
        r = self.run_script("--yes")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("docs.html#migrate", r.stderr)


if __name__ == "__main__":
    unittest.main()
