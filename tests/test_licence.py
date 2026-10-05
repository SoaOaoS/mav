"""Mav and Mav Connect: offline licence keys, plans, and no limits on Mav itself.

Run: python3 -m unittest discover -s tests -v
"""

import base64
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import mav_api  # noqa: E402
import mav_licence  # noqa: E402


def keypair():
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                           serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return enc(priv), enc(pub)


class LicenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv, cls.pub = keypair()
        cls.saved = mav_licence.PUBLIC_KEY
        mav_licence.PUBLIC_KEY = cls.pub

    @classmethod
    def tearDownClass(cls):
        mav_licence.PUBLIC_KEY = cls.saved

    def key(self, **payload):
        return mav_licence.sign({"email": "a@b.c", "plan": "connect", **payload}, self.priv)

    def test_valid_key(self):
        info = mav_licence.verify(self.key(exp=int(time.time()) + 3600))
        self.assertTrue(info["valid"])
        self.assertEqual((info["plan"], info["email"]), ("connect", "a@b.c"))

    def test_first_edition_pro_keys_are_connect(self):
        info = mav_licence.verify(self.key(plan="pro"))
        self.assertEqual(info["plan"], "connect")

    def test_rejections(self):
        good = self.key()
        head, body, sig = good.split(".")
        flipped = sig[:10] + ("B" if sig[10] != "B" else "C") + sig[11:]
        self.assertFalse(mav_licence.verify(f"{head}.{body}.{flipped}")["valid"])  # signature
        spare = sig[:-1] + ("A" if sig[-1] != "A" else "B")  # same bytes or not: refused
        self.assertFalse(mav_licence.verify(f"{head}.{body}.{spare}")["valid"])
        body = good.split(".")
        forged = ".".join([body[0], base64.urlsafe_b64encode(b'{"plan":"pro"}').decode().rstrip("="), body[2]])
        self.assertFalse(mav_licence.verify(forged)["valid"])                    # payload swapped
        self.assertFalse(mav_licence.verify("hello")["valid"])                   # not a key
        other_priv, _ = keypair()
        foreign = mav_licence.sign({"plan": "pro"}, other_priv)
        self.assertFalse(mav_licence.verify(foreign)["valid"])                   # other signer

    def test_expired_falls_back_to_free(self):
        info = mav_licence.verify(self.key(exp=int(time.time()) - 10))
        self.assertFalse(info["valid"])
        self.assertEqual(info["plan"], "free")
        self.assertTrue(info.get("expired"))

    def test_store_and_limits(self):
        lic = mav_licence.Licence(Path(tempfile.mkdtemp()) / "licence.json")
        self.assertEqual(lic.plan(), "free")
        self.assertFalse(lic.has("backup"))
        self.assertFalse(lic.save("nope")["ok"])
        self.assertTrue(lic.save(self.key())["ok"])
        self.assertEqual(lic.plan(), "connect")
        self.assertTrue(lic.has("backup"))
        lic.remove()
        self.assertEqual(lic.plan(), "free")


class NoLimitsTest(unittest.TestCase):
    """Mav itself is free without limits; Connect only adds services."""

    def setUp(self):
        self.priv, pub = keypair()
        self.saved = (mav_api.JOBS_FILE, mav_api.LICENCE, mav_licence.PUBLIC_KEY)
        d = Path(tempfile.mkdtemp())
        mav_api.JOBS_FILE = d / "jobs.json"
        mav_api.LICENCE = mav_licence.Licence(d / "licence.json")
        mav_licence.PUBLIC_KEY = pub

    def tearDown(self):
        mav_api.JOBS_FILE, mav_api.LICENCE, mav_licence.PUBLIC_KEY = self.saved

    def test_free_has_no_routine_limit(self):
        for i in range(12):
            res = mav_api.save_job({"name": f"r{i}", "prompt": "do it", "time": "08:00"})
            self.assertTrue(res["ok"], res)
        self.assertTrue(mav_api.set_job_enabled("r3", False))
        self.assertTrue(mav_api.set_job_enabled("r3", True))

    def test_plan_lists_connect_services(self):
        plan = mav_api.get_plan()
        self.assertEqual(plan["plan"], "free")
        backup = next(x for x in plan["services"] if x["id"] == "backup")
        self.assertFalse(backup["included"])
        key = mav_licence.sign({"email": "a@b.c", "plan": "connect"}, self.priv)
        self.assertTrue(mav_api.LICENCE.save(key)["ok"])
        plan = mav_api.get_plan()
        self.assertEqual(plan["plan"], "connect")
        self.assertTrue(next(x for x in plan["services"] if x["id"] == "backup")["included"])


if __name__ == "__main__":
    unittest.main()
