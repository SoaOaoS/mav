"""Mav Free / Pro: offline licence keys and the plan limits.

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
        return mav_licence.sign({"email": "a@b.c", "plan": "pro", **payload}, self.priv)

    def test_valid_key(self):
        info = mav_licence.verify(self.key(exp=int(time.time()) + 3600))
        self.assertTrue(info["valid"])
        self.assertEqual((info["plan"], info["email"]), ("pro", "a@b.c"))

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
        self.assertTrue(lic.allows("routines", 4))
        self.assertFalse(lic.allows("routines", 5))
        self.assertFalse(lic.save("nope")["ok"])
        self.assertTrue(lic.save(self.key())["ok"])
        self.assertEqual(lic.plan(), "pro")
        self.assertTrue(lic.allows("routines", 500))
        lic.remove()
        self.assertEqual(lic.plan(), "free")


class PlanGateTest(unittest.TestCase):
    def setUp(self):
        self.priv, pub = keypair()
        self.saved = (mav_api.JOBS_FILE, mav_api.LICENCE, mav_licence.PUBLIC_KEY)
        d = Path(tempfile.mkdtemp())
        mav_api.JOBS_FILE = d / "jobs.json"
        mav_api.LICENCE = mav_licence.Licence(d / "licence.json")
        mav_licence.PUBLIC_KEY = pub

    def tearDown(self):
        mav_api.JOBS_FILE, mav_api.LICENCE, mav_licence.PUBLIC_KEY = self.saved

    def job(self, name, **kw):
        return mav_api.save_job({"name": name, "prompt": "do it", "time": "08:00", **kw})

    def test_free_limit_on_new_routines_only(self):
        for i in range(5):
            self.assertTrue(self.job(f"r{i}")["ok"])
        res = self.job("r5")
        self.assertFalse(res["ok"])
        self.assertTrue(res["upgrade"])
        self.assertTrue(self.job("r0", original="r0", prompt="changed")["ok"])  # editing is fine
        # The daily briefing never counts.
        self.assertTrue(mav_api.set_briefing(True, "07:00")["ok"])
        self.assertEqual(mav_api.active_routines(), 5)
        # Switch one off: room for a new one.
        self.assertTrue(mav_api.set_job_enabled("r1", False))
        self.assertTrue(self.job("r5")["ok"])
        # Turning the first back on is over the limit.
        self.assertIsInstance(mav_api.set_job_enabled("r1", True), dict)

    def test_pro_lifts_the_limit(self):
        key = mav_licence.sign({"email": "a@b.c", "plan": "pro"}, self.priv)
        self.assertTrue(mav_api.LICENCE.save(key)["ok"])
        for i in range(8):
            self.assertTrue(self.job(f"p{i}")["ok"])
        plan = mav_api.get_plan()
        self.assertEqual(plan["plan"], "pro")
        self.assertIsNone(plan["limits"]["routines"])
        self.assertEqual(plan["used"]["routines"], 8)


if __name__ == "__main__":
    unittest.main()
