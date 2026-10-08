#!/usr/bin/env python3
"""mav_code — lets Mav run code and commands, read and write files, and hand
the results to the person, like a code interpreter. An MCP server (stdio,
JSON-RPC, stdlib only) that the engine starts as the "code" connection.

Where the code runs depends on the install:

  - self-hosted (Settings → General → "Run code and commands"): on this
    machine, as Mav's user, in its own folder (MAV_CODE_DIR, by default
    ~/workspace/code), without the secrets in its environment. The owner
    turns it on, knowingly: it is their machine.
  - Mav Cloud (MAV_CODE_URL and MAV_CODE_TOKEN set): in the person's own
    sandbox container, run by the platform, which holds no key, no
    database access and no file of Mav's. Files cross over only through
    save_to_chat and load_from_chat.

Tools: run_command, run_python, write_file, read_file, list_files,
save_to_chat (a workspace file → a download card in the chat) and
load_from_chat (a file from the chat → the workspace).
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

PROTOCOL = "2025-06-18"
MAX_OUTPUT = 30_000  # characters of stdout / stderr given back to the model
MAX_FILE = 25 * 1024 * 1024  # bytes moved by save_to_chat / load_from_chat / read_file
MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 120

HOME = Path(os.environ.get("HOME", "/tmp"))
FILES = Path(os.environ.get("MAV_FILES", HOME / "workspace" / "mav-files"))
ATTACH = Path(os.environ.get("MAV_ATTACH", Path(os.environ.get("BOT_DIR", HOME / "bot")) / "attachments"))
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSW|DSN|CREDENTIAL|AUTH|COOKIE|DATABASE|REDIS", re.I)
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class ToolError(Exception):
    """A failure the model should read (bad path, too big, timed out…)."""


def rel_path(path: str) -> str:
    """A path inside the workspace, as a clean relative POSIX path."""
    p = PurePosixPath(str(path or ".").strip() or ".")
    if p.parts[:2] == ("/", "work"):  # the sandbox's own name for the workspace
        p = PurePosixPath(*p.parts[2:]) if len(p.parts) > 2 else PurePosixPath(".")
    if p.is_absolute() or ".." in p.parts:
        raise ToolError(f"Stay inside the workspace: use a relative path, not {path!r}.")
    return p.as_posix()


def chat_name(name: str) -> str:
    base = PurePosixPath(str(name or "")).name
    clean = SAFE_NAME.sub("-", base).strip(" .-")[:120]
    if not clean:
        raise ToolError("Give the file a name, e.g. report.xlsx.")
    return clean


def clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n… ({len(text) - MAX_OUTPUT} more characters not shown)"


# ------------------------------------------------------------------ backends
class Local:
    """This machine, in its own folder, without the secrets in the environment."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def where(self) -> str:
        return f"this machine, in {self.root}"

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root.resolve() and self.root.resolve() not in p.parents:
            raise ToolError("Stay inside the workspace.")
        return p

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not SECRET_NAME.search(k) and not k.startswith(("OPENCODE_", "MAV_", "PG"))}
        env["HOME"] = str(self.root)
        return env

    def run(self, command: str, timeout: int) -> dict:
        proc = subprocess.Popen(["bash", "-lc", command], cwd=self.root, env=self._env(),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
            return {"exit_code": proc.returncode, "stdout": out.decode(errors="replace"),
                    "stderr": err.decode(errors="replace"), "timed_out": False}
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            return {"exit_code": -9, "stdout": out.decode(errors="replace"),
                    "stderr": err.decode(errors="replace"), "timed_out": True}

    def put(self, rel: str, data: bytes) -> None:
        p = self._path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, rel: str) -> bytes:
        p = self._path(rel)
        if not p.is_file():
            raise ToolError(f"No such file in the workspace: {rel}")
        if p.stat().st_size > MAX_FILE:
            raise ToolError(f"{rel} is larger than {MAX_FILE // (1024 * 1024)} MB.")
        return p.read_bytes()


class Remote:
    """The person's sandbox, through Mav Cloud's edge (/code/...)."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def where(self) -> str:
        return "your own sandbox in Mav Cloud (Linux, Python 3, Node, internet access)"

    def _call(self, method: str, path: str, data: bytes | None = None, ctype: str = "application/json",
              timeout: int = 60) -> bytes:
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the platform's own URL
                return r.read(MAX_FILE + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            raise ToolError(f"The sandbox said: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ToolError(f"The sandbox could not be reached: {exc}") from None

    def run(self, command: str, timeout: int) -> dict:
        body = json.dumps({"command": command, "timeout": timeout}).encode()
        return json.loads(self._call("POST", "/exec", body, timeout=timeout + 60))

    def put(self, rel: str, data: bytes) -> None:
        self._call("PUT", "/files?path=" + urllib.parse.quote(rel), data, "application/octet-stream")

    def get(self, rel: str) -> bytes:
        data = self._call("GET", "/files?path=" + urllib.parse.quote(rel))
        if len(data) > MAX_FILE:
            raise ToolError(f"{rel} is larger than {MAX_FILE // (1024 * 1024)} MB.")
        return data


def backend() -> Local | Remote:
    url, token = os.environ.get("MAV_CODE_URL", ""), os.environ.get("MAV_CODE_TOKEN", "")
    if url and token:
        return Remote(url, token)
    return Local(Path(os.environ.get("MAV_CODE_DIR", HOME / "workspace" / "code")))


# ------------------------------------------------------------------ tools
def _timeout(args: dict) -> int:
    try:
        t = int(args.get("timeout_seconds") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT
    return max(1, min(t, MAX_TIMEOUT))


def _report(res: dict) -> str:
    parts = [f"exit code: {res.get('exit_code')}" + (" (stopped: took too long)" if res.get("timed_out") else "")]
    if res.get("stdout"):
        parts.append("--- stdout ---\n" + clip(res["stdout"]))
    if res.get("stderr"):
        parts.append("--- stderr ---\n" + clip(res["stderr"]))
    return "\n".join(parts)


def tool_run_command(b, args: dict) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        raise ToolError("Give a command to run.")
    return _report(b.run(command, _timeout(args)))


def tool_run_python(b, args: dict) -> str:
    code = str(args.get("code") or "")
    if not code.strip():
        raise ToolError("Give some Python code to run.")
    b.put(".mav/run.py", code.encode())
    return _report(b.run("python3 .mav/run.py", _timeout(args)))


def tool_write_file(b, args: dict) -> str:
    rel = rel_path(args.get("path", ""))
    data = str(args.get("content") or "").encode()
    b.put(rel, data)
    return f"Wrote {rel} ({len(data)} bytes)."


def tool_read_file(b, args: dict) -> str:
    rel = rel_path(args.get("path", ""))
    data = b.get(rel)
    try:
        text = data.decode()
    except UnicodeDecodeError:
        return f"{rel} is a binary file ({len(data)} bytes). Use save_to_chat to hand it to the person."
    return clip(text)


def tool_list_files(b, args: dict) -> str:
    rel = rel_path(args.get("path", "."))
    res = b.run(f"find {json.dumps(rel)} -maxdepth 3 -not -path '*/.mav*' -printf '%y %10s  %p\\n' | sort -k3 | head -300", 30)
    return clip(res.get("stdout") or "(empty)") if res.get("exit_code") == 0 else _report(res)


def tool_save_to_chat(b, args: dict) -> str:
    rel = rel_path(args.get("path", ""))
    name = chat_name(args.get("name") or PurePosixPath(rel).name)
    data = b.get(rel)
    FILES.mkdir(parents=True, exist_ok=True)
    (FILES / name).write_bytes(data)
    return (f"Saved {name} ({len(data)} bytes) for the person. Put [[file:{name}]] on a line of its own "
            "in your answer: it shows as a download card.")


def tool_load_from_chat(b, args: dict) -> str:
    name = chat_name(args.get("name", ""))
    for folder in (FILES, ATTACH):
        src = folder / name
        if src.is_file():
            if src.stat().st_size > MAX_FILE:
                raise ToolError(f"{name} is larger than {MAX_FILE // (1024 * 1024)} MB.")
            dest = rel_path(args.get("path") or name)
            b.put(dest, src.read_bytes())
            return f"Copied {name} into the workspace as {dest}."
    known = sorted({p.name for d in (FILES, ATTACH) if d.is_dir() for p in d.iterdir() if p.is_file()})[:40]
    raise ToolError(f"No file called {name} in the chat. Files there: {', '.join(known) or 'none'}.")


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TIMEOUT_PROP = {"type": "integer", "description": f"Seconds before it is stopped (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT})."}
TOOLS = {
    "run_command": (tool_run_command, "Run a shell command (bash) in the workspace and get its output. Install "
                    "what you need (pip install, npm install), convert files, compute, fetch data.",
                    _obj({"command": {"type": "string"}, "timeout_seconds": TIMEOUT_PROP}, ["command"])),
    "run_python": (tool_run_python, "Run a Python 3 script in the workspace and get its output. pandas, numpy, "
                   "matplotlib, openpyxl, python-docx and reportlab are usually available; print what you need to see.",
                   _obj({"code": {"type": "string"}, "timeout_seconds": TIMEOUT_PROP}, ["code"])),
    "write_file": (tool_write_file, "Create or replace a text file in the workspace.",
                   _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])),
    "read_file": (tool_read_file, "Read a text file from the workspace.",
                  _obj({"path": {"type": "string"}}, ["path"])),
    "list_files": (tool_list_files, "List the files in the workspace (or one of its folders).",
                   _obj({"path": {"type": "string"}}, [])),
    "save_to_chat": (tool_save_to_chat, "Hand a file from the workspace to the person: it becomes a download "
                     "card in the chat. Use it for anything they should keep (xlsx, pdf, png, csv, docx…).",
                     _obj({"path": {"type": "string"}, "name": {"type": "string", "description": "The name they see; defaults to the file's."}}, ["path"])),
    "load_from_chat": (tool_load_from_chat, "Copy a file the person shared in the chat (or one Mav made earlier) "
                       "into the workspace, to work on it.",
                       _obj({"name": {"type": "string"}, "path": {"type": "string", "description": "Where to put it; defaults to the same name."}}, ["name"])),
}


# ------------------------------------------------------------------ MCP
def handle(msg: dict, b) -> dict | None:
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:  # a notification: nothing to answer
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mav-code", "version": "1.0"},
            "instructions": f"Runs code and commands in {b.where()}.",
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
            text, is_error = TOOLS[name][0](b, params.get("arguments") or {}), False
        except ToolError as exc:
            text, is_error = str(exc), True
        except Exception as exc:  # noqa: BLE001 — told to the model, not a crash
            text, is_error = f"{type(exc).__name__}: {exc}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    b = backend()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg, b) if isinstance(msg, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
