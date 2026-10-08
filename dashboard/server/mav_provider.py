#!/usr/bin/env python3
"""Model provider configuration — single source of truth.

Used by the dashboard (Settings → Model) and by install.sh, so the provider is
always written the same way:

  - ~/.config/opencode/opencode.json : `model` + a `provider` block for
    OpenAI-compatible endpoints (never for providers opencode knows natively,
    which would drop their auth);
  - /etc/mav-server.env              : the API key, read by the engine through
    the environment (`{env:NAME}` in the JSON), never stored in clear in the
    JSON;
  - /etc/mav.env, /etc/mav-dashboard.env : OPENCODE_MODEL for the worker and
    the dashboard.

Stdlib only. CLI (for the installer):

  mav_provider.py presets
  mav_provider.py models --provider anthropic [--base-url URL]   (key in $MAV_PROVIDER_APIKEY)
  mav_provider.py apply  --config-dir DIR --env-server FILE [--env-file FILE ...]
                         --provider ID --model M [--base-url URL] [--name NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# id -> preset. `native` providers are built into opencode: we only set the
# model and the key env var. The others are declared as OpenAI-compatible.
PRESETS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic",
        "hint": "Claude models. Needs an API key from console.anthropic.com.",
        "native": True,
        "env": "ANTHROPIC_API_KEY",
        "base": "https://api.anthropic.com/v1",
        "key": "required",
        "model": "claude-sonnet-4-5",
    },
    "openai": {
        "label": "OpenAI",
        "hint": "GPT models. Needs an API key from platform.openai.com.",
        "native": True,
        "env": "OPENAI_API_KEY",
        "base": "https://api.openai.com/v1",
        "key": "required",
        "model": "gpt-4o",
    },
    "ollama": {
        "label": "Ollama (local)",
        "self_only": True,  # on this machine: unreachable from Mav Cloud
        "hint": "Models running on your own machine or LAN. No key needed.",
        "native": False,
        "env": "OLLAMA_API_KEY",
        "base": "http://localhost:11434/v1",
        "key": "optional",
        "model": "llama3.1",
    },
    "ollama-cloud-api": {
        "label": "Ollama Cloud",
        "hint": "Hosted open models on ollama.com. Needs an Ollama API key.",
        "native": False,
        "env": "OLLAMA_API_KEY",
        "base": "https://ollama.com/v1",
        "key": "required",
        "model": "deepseek-v4.1-flash",
    },
    "openrouter": {
        "label": "OpenRouter",
        "hint": "Hundreds of models behind one key (openrouter.ai).",
        "native": False,
        "env": "OPENROUTER_API_KEY",
        "base": "https://openrouter.ai/api/v1",
        "key": "required",
        "model": "anthropic/claude-sonnet-4.5",
    },
    "custom": {
        "label": "Custom endpoint",
        "hint": "Any OpenAI-compatible API (LM Studio, vLLM, Groq, Mistral…).",
        "native": False,
        "env": "",
        "base": "",
        "key": "optional",
        "model": "",
    },
}

# Configured through `opencode auth login`; we keep them as they are.
AUTH_MANAGED = {"ollama-cloud"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


# ------------------------------------------------------------------ helpers


def env_name_for(pid: str) -> str:
    preset = PRESETS.get(pid)
    if preset and preset["env"]:
        return preset["env"]
    return re.sub(r"[^A-Z0-9]", "_", pid.upper()) + "_API_KEY"


def read_env(path: Path) -> dict:
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return out


def set_env(path: Path, values: dict) -> None:
    """Set KEY=value lines in an env file, keeping every other line."""
    path = Path(path)
    lines = path.read_text().splitlines() if path.is_file() else []
    seen = set()
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line else None
        if k in values and not line.lstrip().startswith("#"):
            if values[k] is not None:
                out.append(f"{k}={values[k]}")
            seen.add(k)
        else:
            out.append(line)
    for k, v in values.items():
        if k not in seen and v is not None:
            out.append(f"{k}={v}")
    mode = path.stat().st_mode & 0o777 if path.is_file() else 0o600
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n")
    os.chmod(tmp, mode)
    tmp.replace(path)


def _owner_like(path: Path, ref: Path) -> None:
    """When running as root, give a file back to the owner of `ref`."""
    if os.geteuid() != 0:
        return
    try:
        st = ref.stat()
        os.chown(path, st.st_uid, st.st_gid)
    except Exception:  # noqa: BLE001
        pass


def _auth_providers(config_dir: Path) -> set:
    """Providers registered with `opencode auth login` (auth.json)."""
    home = config_dir.parent.parent  # ~/.config/opencode -> ~
    auth = home / ".local/share/opencode/auth.json"
    try:
        return set(json.loads(auth.read_text()).keys())
    except Exception:  # noqa: BLE001
        return set()


# ------------------------------------------------------------------ read


def current(config_dir: Path, env_server: Path) -> dict:
    """What is configured now (never returns the key itself)."""
    cfg_path = Path(config_dir) / "opencode.json"
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception:  # noqa: BLE001
        cfg = {}
    ref = str(cfg.get("model") or "")
    pid, _, model = ref.partition("/")
    block = (cfg.get("provider") or {}).get(pid) or {}
    opts = block.get("options") or {}
    env = read_env(env_server)
    key_env = env_name_for(pid) if pid else ""
    api_key = opts.get("apiKey", "")
    has_key = bool(env.get(key_env)) or (bool(api_key) and not str(api_key).startswith("{env:"))
    if pid in AUTH_MANAGED or pid in _auth_providers(Path(config_dir)):
        has_key = True
    return {
        "provider": pid,
        "model": model,
        "ref": ref,
        "base_url": opts.get("baseURL", "") or (PRESETS.get(pid, {}).get("base", "") if pid else ""),
        "has_key": has_key,
        "preset": pid if pid in PRESETS else ("custom" if block else pid),
        "name": block.get("name", ""),
        "configured": bool(ref),
        "auth_managed": pid in AUTH_MANAGED,
    }


# ------------------------------------------------------------------ test


def list_models(pid: str, base_url: str = "", api_key: str = "", timeout: float = 12) -> dict:
    """Ask the provider for its models. Doubles as a connection/key test."""
    preset = PRESETS.get(pid, PRESETS["custom"])
    base = (base_url or preset["base"] or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "An endpoint URL is required."}
    headers = {"Accept": "application/json", "User-Agent": "mav"}
    if pid == "anthropic":
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base}/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        msg = {401: "The API key was rejected (401).", 403: "Access denied (403)."}.get(
            exc.code, f"The provider answered HTTP {exc.code}."
        )
        return {"ok": False, "error": msg, "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Cannot reach {base}: {getattr(exc, 'reason', exc)}"}
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list) and isinstance(data, dict):
        items = data.get("models") or []
    models = []
    for m in items or []:
        mid = m.get("id") or m.get("name") if isinstance(m, dict) else m
        if mid and mid not in models:
            models.append(str(mid))
    models.sort()
    return {"ok": True, "models": models[:500], "base_url": base}


# ------------------------------------------------------------------ write


def apply(
    config_dir: Path,
    env_server: Path,
    pid: str,
    model: str,
    base_url: str = "",
    api_key: str | None = None,
    env_files: list | None = None,
    name: str = "",
) -> dict:
    """Write the provider config. `api_key=None` keeps the existing key."""
    pid = (pid or "").strip().lower()
    model = (model or "").strip()
    # "anthropic/claude-…" as well as "claude-…": the provider is given apart.
    if model.lower().startswith(pid + "/"):
        model = model[len(pid) + 1:]
    if not ID_RE.match(pid):
        return {"ok": False, "error": "Invalid provider id (a-z, 0-9, - _)."}
    if not model:
        return {"ok": False, "error": "Choose a model."}
    config_dir = Path(config_dir)
    preset = PRESETS.get(pid, PRESETS["custom"])
    native = preset["native"] or pid in AUTH_MANAGED or pid in _auth_providers(config_dir)
    key_env = env_name_for(pid)

    cfg_path = config_dir / "opencode.json"
    try:
        cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    blocks = cfg.get("provider") or {}

    if native:
        # Undo a stale empty override for a native provider (it breaks auth),
        # but keep a real user override that carries options.
        blk = blocks.get(pid)
        if isinstance(blk, dict) and not (blk.get("options") or {}):
            blocks.pop(pid, None)
        if base_url and base_url.rstrip("/") != preset["base"].rstrip("/"):
            blk = blocks.setdefault(pid, {})
            blk.setdefault("options", {})["baseURL"] = base_url
            # Behind another endpoint (Mav Cloud's proxy), the model may be
            # newer than the engine's catalogue: declare it.
            blk.setdefault("models", {}).setdefault(model, {"name": model})
    else:
        base = base_url or preset["base"]
        if not base:
            return {"ok": False, "error": "An endpoint URL is required."}
        old = blocks.get(pid) or {}
        models = dict(old.get("models") or {})
        models.setdefault(model, {"name": model})
        opts = {"baseURL": base}
        has_key = bool(api_key) or (api_key is None and bool(read_env(env_server).get(key_env)))
        if has_key:
            opts["apiKey"] = "{env:%s}" % key_env
        blocks[pid] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": name or preset["label"] if pid in PRESETS else (name or pid),
            "options": opts,
            "models": models,
        }
    if blocks:
        cfg["provider"] = blocks
    else:
        cfg.pop("provider", None)
    ref = f"{pid}/{model}"
    cfg["model"] = ref
    cfg.setdefault("$schema", "https://opencode.ai/config.json")

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        tmp = cfg_path.with_name("opencode.json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(cfg_path)
        _owner_like(cfg_path, config_dir)
        if api_key is not None and key_env:
            set_env(env_server, {key_env: api_key})
        for f in env_files or []:
            if Path(f).is_file():
                set_env(Path(f), {"OPENCODE_MODEL": ref})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "ref": ref, "native": native}


# ------------------------------------------------------------------ CLI


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Mav provider configuration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets")
    m = sub.add_parser("models")
    m.add_argument("--provider", required=True)
    m.add_argument("--base-url", default="")
    a = sub.add_parser("apply")
    a.add_argument("--config-dir", required=True)
    a.add_argument("--env-server", required=True)
    a.add_argument("--env-file", action="append", default=[])
    a.add_argument("--provider", required=True)
    a.add_argument("--model", required=True)
    a.add_argument("--base-url", default="")
    a.add_argument("--name", default="")
    args = ap.parse_args()

    # The key comes from the environment, never from argv (visible in ps).
    key = os.environ.get("MAV_PROVIDER_APIKEY")

    if args.cmd == "presets":
        print(json.dumps(PRESETS, indent=1))
        return 0
    if args.cmd == "models":
        res = list_models(args.provider, args.base_url, key or "")
        if not res["ok"]:
            print(res["error"], file=sys.stderr)
            return 1
        print("\n".join(res["models"]))
        return 0
    res = apply(
        Path(args.config_dir), Path(args.env_server), args.provider, args.model,
        args.base_url, key, args.env_file, args.name,
    )
    if not res["ok"]:
        print(res["error"], file=sys.stderr)
        return 1
    print(res["ref"])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
