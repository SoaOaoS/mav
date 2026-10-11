#!/usr/bin/env python3
"""mav_memory — the assistant's own hands on its long-term memory: remember a
fact the moment it learns it, correct one that changed, forget one that is no
longer true, look up what it knows. An MCP server (stdio, JSON-RPC, stdlib
only) that the engine starts as the "memory" connection; Mav's web app
writes that connection itself (mav_engine.ensure_memory_tool).

The facts live in Mav's database, per person. This process does not touch
it: it asks the web app (MAV_AGENT_API_URL, with MAV_AGENT_TOKEN), which
works out whose conversation is asking and acts in that person's memory only.

Tools: remember, update, forget, recall (the engine shows them as
memory_remember, memory_update…).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"
API = os.environ.get("MAV_AGENT_API_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("MAV_AGENT_TOKEN", "")


class ToolError(Exception):
    """A failure the model should read."""


def call(action: str, **args) -> dict:
    req = urllib.request.Request(
        f"{API}/api/agent/memory",
        data=json.dumps({"action": action, **args}).encode(),
        headers={"Content-Type": "application/json", "X-Mav-Agent-Token": TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            res = json.loads(exc.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            res = {}
        raise ToolError(res.get("error") or f"Mav answered {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Mav's memory is unreachable right now ({exc}).") from exc
    if not res.get("ok"):
        raise ToolError(res.get("error") or "That did not work.")
    return res


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def tool_remember(a: dict) -> str:
    res = call("remember", fact=str(a.get("fact") or ""))
    return f"Remembered (#{res['id']}): {res['fact']}" if not res.get("existing") else f"Already known (#{res['id']}): {res['fact']}"


def tool_update(a: dict) -> str:
    res = call("update", id=a.get("id"), fact=str(a.get("fact") or ""))
    return f"Updated #{res['id']}: {res['fact']}"


def tool_forget(a: dict) -> str:
    res = call("forget", id=a.get("id"))
    return f"Forgotten #{res['id']}: {res['fact']}"


def tool_recall(a: dict) -> str:
    res = call("recall", query=str(a.get("query") or ""))
    lines = [f"#{f['id']} {f['fact']}" for f in res.get("facts") or []] or ["(no fact saved yet)"]
    out = "What I know about them:\n" + "\n".join(lines)
    past = res.get("past") or []
    if past:
        out += "\n\nRelated past conversations:\n" + "\n".join(f"- Q: {p['q'][:200]}\n  A: {p['a'][:300]}" for p in past)
    return out


FACT = {"type": "string", "description": "One durable fact about the person, as a short sentence in the language of the "
        "conversation, with dates when it is temporary (e.g. 'Raphaël is in Alès for his work-study until 15 Nov 2026, "
        "then back in Toulouse')."}
ID = {"type": "integer", "description": "The fact's number, as recall shows it (#12 → 12)."}

TOOLS = {
    "remember": (tool_remember, "Save a durable fact about the person in your long-term memory, right away and "
                 "without asking: where they live or stay, job, studies, family, health or diet, preferences, "
                 "important dates, constraints. Then just tell them it is noted.",
                 _obj({"fact": FACT}, ["fact"])),
    "update": (tool_update, "Correct a fact you already know when it changed (use recall to find its number): "
               "change it instead of adding a contradicting one.",
               _obj({"id": ID, "fact": FACT}, ["id", "fact"])),
    "forget": (tool_forget, "Delete a fact that is no longer true, or that the person asks you to forget.",
               _obj({"id": ID}, ["id"])),
    "recall": (tool_recall, "List the facts you know about the person (with their numbers) and the past "
               "conversations related to a topic.",
               _obj({"query": {"type": "string", "description": "A topic to look for in past conversations (optional)."}}, [])),
}


def handle(msg: dict) -> dict | None:
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mav-memory", "version": "1.0"},
            "instructions": "Your long-term memory of the person: keep it right yourself.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (_, d, s) in TOOLS.items()]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            text, is_error = TOOLS[name][0](params.get("arguments") or {}), False
        except ToolError as exc:
            text, is_error = str(exc), True
        except Exception as exc:  # noqa: BLE001
            text, is_error = f"{type(exc).__name__}: {exc}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
