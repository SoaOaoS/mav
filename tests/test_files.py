"""Files Mav hands you: written to mav-files/, served as download cards.

Run: python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

import mav_api  # noqa: E402


class FilesDirTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.files = tmp / "mav-files"
        self.files.mkdir()
        self.media = tmp / "media"
        self.saved = (mav_api.FILES_DIR, mav_api.MEDIA_DIR, mav_api.MEDIA_INDEX, mav_api._asset_roots)
        mav_api.FILES_DIR = self.files
        mav_api.MEDIA_DIR = self.media
        mav_api.MEDIA_INDEX = self.media / "index.json"
        # Only the test folders are allowed roots (no /tmp/opencode etc.).
        mav_api._asset_roots = lambda: [self.files, self.media]
        self.outside = tmp / "secret.txt"
        self.outside.write_text("not for you")

    def tearDown(self):
        (mav_api.FILES_DIR, mav_api.MEDIA_DIR, mav_api.MEDIA_INDEX, mav_api._asset_roots) = self.saved

    def test_default_location_follows_the_engine_workspace(self):
        env = {k: os.environ.get(k) for k in ("MAV_FILES", "MAV_USER_HOME", "BOT_HOME")}
        try:
            for k in env:
                os.environ.pop(k, None)
            os.environ["MAV_USER_HOME"] = "/home/someone"
            self.assertEqual(mav_api._files_dir(), Path("/home/someone/workspace/mav-files"))
            os.environ["MAV_FILES"] = "/data/files"
            self.assertEqual(mav_api._files_dir(), Path("/data/files"))
        finally:
            for k, v in env.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_a_shared_file_is_downloadable_by_its_name(self):
        (self.files / "budget-2026.csv").write_text("item,eur\nrent,800\n")
        data, mime, name = mav_api.download_response("budget-2026.csv")
        self.assertEqual(name, "budget-2026.csv")
        self.assertIn(b"rent,800", data)
        self.assertTrue(mime.startswith("text/csv"))

    def test_nothing_outside_the_allowed_folders(self):
        self.assertIsNone(mav_api.download_response(str(self.outside)))
        self.assertIsNone(mav_api.download_response("../secret.txt"))
        self.assertIsNone(mav_api.download_response("/etc/passwd"))

    def test_sensitive_files_are_never_served(self):
        (self.files / ".env").write_text("KEY=1")
        (self.files / "id_rsa").write_text("-----BEGIN")
        self.assertIsNone(mav_api.download_response(".env"))
        self.assertIsNone(mav_api.download_response("id_rsa"))

    def test_shared_files_are_archived_and_outlive_the_folder(self):
        f = self.files / "trip-lisbon.md"
        f.write_text("# Lisbon\n")
        self.assertEqual(mav_api.sync_files_dir(), 1)
        self.assertEqual(mav_api.sync_files_dir(), 0)  # once only
        f.unlink()
        data, _, _ = mav_api.download_response("trip-lisbon.md")
        self.assertEqual(data, b"# Lisbon\n")

    def test_sensitive_files_are_not_archived(self):
        (self.files / ".env").write_text("KEY=1")
        self.assertEqual(mav_api.sync_files_dir(), 0)


def edit_rules(text: str) -> dict:
    """The `permission.edit` block of an agent's frontmatter, in order."""
    front = text.split("---")[1].splitlines()
    rules, inside = {}, False
    for line in front:
        if line == "  edit:":
            inside = True
        elif inside and line.startswith("    "):
            key, _, val = line.strip().rpartition(":")
            rules[key.strip().strip('"')] = val.strip()
        elif inside:
            break
    return rules


class HelperPermissionsTest(unittest.TestCase):
    """Every shipped helper may write in mav-files/ and nowhere else."""

    def test_edit_is_scoped_to_mav_files(self):
        for f in sorted((ROOT / "agents").glob("*.md")):
            edit = edit_rules(f.read_text())
            self.assertTrue(edit, f.name)
            self.assertEqual(edit.get("*"), "deny", f.name)
            self.assertEqual(edit.get("mav-files/*"), "allow", f.name)
            self.assertEqual(edit.get("*/mav-files/*"), "allow", f.name)
            self.assertEqual(list(edit)[0], "*", f"{f.name}: the catch-all must come first (last match wins)")

    def test_the_assistant_knows_how_to_share(self):
        text = (ROOT / "agents" / "assistant.md").read_text()
        self.assertIn("mav-files/", text)
        self.assertIn("[[file:", text)


if __name__ == "__main__":
    unittest.main()
