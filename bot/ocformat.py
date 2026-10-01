"""Rendu markdown -> HTML Telegram, et découpage sans casser les balises."""

from __future__ import annotations

import html
import re

TG_LIMIT = 3800  # Telegram's hard cap is 4096; leave room for tag repair


def _protect(text: str) -> tuple[str, list[str]]:
    """Pull fenced blocks and inline code out so inline rules can't touch them."""
    stash: list[str] = []

    def keep(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"```.*?```", keep, text, flags=re.S)
    # Models truncate; rescue a fence that was opened and never closed.
    text = re.sub(r"```[^`]*\Z", keep, text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", keep, text)
    return text, stash


def _render_code(raw: str) -> str:
    if raw.startswith("```"):
        body = raw[3:-3] if raw.endswith("```") else raw[3:]
        lang, _, code = body.partition("\n")
        lang = lang.strip()
        if not code and "\n" not in body:  # ```oneliner```
            code, lang = body, ""
        code = html.escape(code.strip("\n"), quote=False)
        cls = f' class="language-{html.escape(lang)}"' if lang.isalnum() else ""
        return f"<pre><code{cls}>{code}</code></pre>"
    return f"<code>{html.escape(raw.strip(chr(96)), quote=False)}</code>"


def _tables_to_pre(text: str) -> str:
    """Telegram can't render tables; monospace at least keeps them aligned."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if (
            lines[i].strip().startswith("|")
            and i + 1 < len(lines)
            and re.fullmatch(r"\s*\|[\s:|-]+\|\s*", lines[i + 1])
        ):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            out.append("<pre>" + "\n".join(block) + "</pre>")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def md_to_html(text: str) -> str:
    text, stash = _protect(text)
    text = html.escape(text, quote=False)  # keep ' and " readable

    # Links before anything else touches the brackets.
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )

    text = _tables_to_pre(text)

    out: list[str] = []
    for line in text.split("\n"):
        # Headings -> bold line
        h = re.match(r"\s{0,3}(#{1,6})\s+(.*)$", line)
        if h:
            out.append(f"<b>{h.group(2).strip()}</b>")
            continue
        # Horizontal rules are noise on a phone
        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            continue
        # Bullets -> real bullet chars, preserving indent
        b = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if b:
            line = f"{b.group(1)}• {b.group(2)}"
        # Blockquotes
        q = re.match(r"^\s*&gt;\s?(.*)$", line)
        if q:
            line = f"<blockquote>{q.group(1)}</blockquote>"
        out.append(line)
    text = "\n".join(out)

    # Inline emphasis. Guard against 2 * 3 * 4 being read as italics by
    # forbidding whitespace next to the markers.
    text = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"__(?!\s)(.+?)(?<!\s)__", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"~~(?!\s)(.+?)(?<!\s)~~", r"<s>\1</s>", text, flags=re.S)

    # Collapse runs of blank lines; vertical space is expensive on a phone.
    text = re.sub(r"\n{3,}", "\n\n", text)

    for i, raw in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", _render_code(raw))
    return text.strip()


def split_markdown(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Chunk the *markdown* on line boundaries, keeping code fences balanced,
    so each chunk converts to standalone valid HTML."""
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    fence: str | None = None  # language of the fence we're inside, if any

    def flush() -> None:
        nonlocal buf, size
        if buf:
            body = "\n".join(buf)
            if fence is not None:  # close an open fence before cutting
                body += "\n```"
            chunks.append(body)
            buf, size = ([f"```{fence}"], len(fence) + 4) if fence is not None else ([], 0)

    for line in text.split("\n"):
        f = re.match(r"^\s*```(\w*)", line)
        if f:
            fence = None if fence is not None else f.group(1)

        while len(line) > limit:  # single monstrous line
            flush()
            chunks.append(line[:limit])
            line = line[limit:]

        if size + len(line) + 1 > limit and buf:
            flush()
        buf.append(line)
        size += len(line) + 1

    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()] or [""]


TG_HARD = 4096


def format_for_telegram(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Chunk, convert, and guarantee every result fits Telegram's hard cap.

    Escaping expands text (& -> &amp;), so a source chunk that fitted can
    overflow once converted. Shrink the source limit until it doesn't.
    """
    while True:
        out = [md_to_html(c) for c in split_markdown(text, limit)]
        if all(len(c) <= TG_HARD for c in out) or limit < 400:
            return [c for c in out if c.strip()] or ["(empty response)"]
        limit = int(limit * 0.7)
