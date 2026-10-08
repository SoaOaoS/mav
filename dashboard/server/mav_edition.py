"""Which Mav this is, and so which parts of the app it has.

  self       — self-hosted: everything (it is your machine).
  mymav      — Mav Cloud with your own model key: no family, password,
               backup, updates, advanced or webhook (the platform does those:
               e-mail sign-in, nightly backups and export, updates, one
               account per subscription).
  cloudmav   — Mav Cloud with the model included: as MyMav, and no model
               settings, no costs and budget (the plan's allowance is on the
               account page) and no debates (they burn the allowance).

Set by Mav Cloud with MAV_EDITION; MAV_MODEL_MANAGED=1 alone (older Mav
Cloud) means cloudmav. One table below decides; the API refuses the routes of
a part that is off, and the app hides it (/api/auth/state carries the table).
"""

from __future__ import annotations

import os

EDITIONS = ("self", "mymav", "cloudmav")

#                       self   mymav  cloudmav
_TABLE: dict[str, tuple[bool, bool, bool]] = {
    "model":    (True,  True,  False),   # choose the model, its key, the background model
    "usage":    (True,  True,  False),   # costs per chat and routine, monthly budget
    "debates":  (True,  True,  False),   # multi-helper debates
    "family":   (True,  False, False),   # other people's accounts
    "password": (True,  False, False),   # Mav's own sign-in
    "backup":   (True,  False, False),   # download / restore in the app
    "updates":  (True,  False, False),   # version check and self-update
    "advanced": (True,  False, False),   # engine status, raw connection config, paths
    "webhook":  (True,  False, False),   # other services starting a routine
    "code_setting": (True, False, False),  # the "Run code" switch (always on in the cloud sandbox)
}

# The routes of each part: (method or "*", exact path or prefix ending in "/").
_ROUTES: dict[str, tuple[tuple[str, str], ...]] = {
    "model": (("POST", "/api/config/provider"), ("POST", "/api/config/provider/test"),
              ("POST", "/api/usage/small-model")),
    "usage": (("POST", "/api/usage/budget"),),
    "debates": (("*", "/api/debates"), ("*", "/api/debate")),
    "family": (("*", "/api/family"), ("*", "/api/family/")),
    "password": (("POST", "/api/auth/password"),),
    "backup": (("*", "/api/backup"), ("*", "/api/backup/")),
    "updates": (("*", "/api/update"), ("*", "/api/update/")),
    "webhook": (("*", "/api/webhook"), ("*", "/api/webhook/"), ("*", "/api/hooks/")),
    "code_setting": (("POST", "/api/config/code"),),
}


def _edition() -> str:
    e = os.environ.get("MAV_EDITION", "").strip().lower()
    if e in EDITIONS:
        return e
    if os.environ.get("MAV_MODEL_MANAGED", "").lower() in ("1", "true", "yes"):
        return "cloudmav"
    return "self"


EDITION = _edition()
FEATURES: dict[str, bool] = {k: v[EDITIONS.index(EDITION)] for k, v in _TABLE.items()}


def table() -> dict[str, dict[str, bool]]:
    """The whole matrix, for the docs and the tests."""
    return {e: {k: v[i] for k, v in _TABLE.items()} for i, e in enumerate(EDITIONS)}


def off_feature(method: str, path: str, features: dict[str, bool] | None = None) -> str | None:
    """The part that is off and that this request belongs to, if any."""
    feats = FEATURES if features is None else features
    for feat, routes in _ROUTES.items():
        if feats.get(feat, True):
            continue
        for m, p in routes:
            if m not in ("*", method):
                continue
            if path == p or (p.endswith("/") and path.startswith(p)):
                return feat
    return None
