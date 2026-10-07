"""Keep an eye on things: alerts when they change.

Watched items live in Postgres (watch_items table):
  kind    : "web"   — a web page whose content changes
            "price" — a product page whose price changes ("URL" or "URL|50"
                      to only care about going below 50)
            "news"  — new headlines about a topic (Google News)
            "rss"   — new items in an RSS or Atom feed
            "github"— new releases of a GitHub repository ("owner/repo")
  target  : the URL, the topic or the repository. News, feeds and releases
            take an optional condition after "|": "topic|word, other" only
            alerts on items that mention one of the words.
  last_state / last_checked : so we only alert again on a change

The worker runs this loop alongside the routines scheduler. The first check
only records the state; afterwards a push notification is sent on change.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("ocwatch")

PG_DSN = os.environ.get(
    "PG_DSN",
    "host=127.0.0.1 port=5432 user=mav password=mav_secret dbname=mav",
)

# Base interval between two passes of the loop (seconds).
BASE_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "900"))
NEWS_LANG = os.environ.get("NEWS_LANG", "en-US")  # e.g. fr-FR
NEWS_COUNTRY = os.environ.get("NEWS_COUNTRY", "US")  # e.g. FR

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

KINDS = ("web", "price", "news", "rss", "github")
FEED_KINDS = ("news", "rss", "github")
FEED_LIMIT = 30  # newest items considered per pass (the state remembers 40)
_REPO_PART = re.compile(r"[A-Za-z0-9_.-]{1,100}")


# ------------------------------------------------------------------ parsing


def fetch(url: str, limit: int = 1_500_000) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": f"{NEWS_LANG},en;q=0.8"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(limit)
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def visible_text(page: str) -> str:
    """The page's readable text: no scripts, styles, tags or whitespace noise,
    so ads/tokens in the markup do not count as a change."""
    page = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    return re.sub(r"\s+", " ", page).strip()


_PRICE_PATTERNS = [
    r'"price"\s*:\s*"?([0-9]+(?:[.,][0-9]{1,2})?)"?',
    r'itemprop=["\']price["\'][^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)',
    r'content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\'][^>]*itemprop=["\']price',
    r'property=["\'](?:product|og):price:amount["\'][^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)',
]
_CURRENCY = re.compile(r'"priceCurrency"\s*:\s*"([A-Z]{3})"')
_VISIBLE_PRICE = re.compile(
    r"(?:([€$£])\s?([0-9]{1,6}(?:[.,  ][0-9]{3})*(?:[.,][0-9]{2})?))"
    r"|(?:([0-9]{1,6}(?:[.,  ][0-9]{3})*(?:[.,][0-9]{2})?)\s?([€$£]|EUR|USD|GBP))"
)


def _num(s: str) -> float | None:
    s = s.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) == 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def find_price(page: str) -> tuple[float, str] | None:
    """Best guess of a product page's price: structured data first, then the
    first amount with a currency in the visible text."""
    cur = _CURRENCY.search(page)
    currency = cur.group(1) if cur else ""
    for pat in _PRICE_PATTERNS:
        m = re.search(pat, page, re.I)
        if m:
            v = _num(m.group(1))
            if v:
                return v, currency
    m = _VISIBLE_PRICE.search(visible_text(page))
    if m:
        sym = m.group(1) or m.group(4) or ""
        v = _num(m.group(2) or m.group(3) or "")
        if v:
            return v, {"€": "EUR", "$": "USD", "£": "GBP"}.get(sym, sym)
    return None


def news_items(topic: str) -> list[dict]:
    q = urllib.parse.quote(topic)
    lang = NEWS_LANG.split("-")[0]
    url = (
        f"https://news.google.com/rss/search?q={q}&hl={NEWS_LANG}"
        f"&gl={NEWS_COUNTRY}&ceid={NEWS_COUNTRY}:{lang}"
    )
    root = ET.fromstring(fetch(url).encode("utf-8"))
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title:
            out.append({
                "title": title,
                "link": link,
                "id": hashlib.sha1((link or title).encode()).hexdigest()[:8],
            })
    return out[:15]


def split_price_target(target: str) -> tuple[str, float | None]:
    url, _, below = target.partition("|")
    return url.strip(), _num(below.strip()) if below.strip() else None


_ATOM = "{http://www.w3.org/2005/Atom}"


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", s or ""))).strip()


def feed_items(xml_text: str) -> list[dict]:
    """Items of an RSS 2.0, RSS 1.0 or Atom feed, newest first as published."""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    out = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = guid = summary = ""
        for child in it:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title":
                title = _strip(child.text or "")
            elif name == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    link = link or href
                elif not href and child.text:
                    link = link or child.text.strip()
            elif name in ("guid", "id"):
                guid = (child.text or "").strip()
            elif name in ("description", "summary", "content") and not summary:
                summary = _strip(child.text or "")[:300]
        if title or link:
            out.append({
                "title": title or link,
                "link": link,
                "summary": summary,
                "id": hashlib.sha1((guid or link or title).encode()).hexdigest()[:8],
            })
        if len(out) >= FEED_LIMIT:
            break
    return out


def split_condition(target: str) -> tuple[str, list[str]]:
    """'topic|word, other' → ('topic', ['word', 'other'])."""
    base, _, cond = target.partition("|")
    words = [w.strip().lower() for w in re.split(r"[,;]", cond) if w.strip()]
    return base.strip(), words


def mentions(item: dict, words: list[str]) -> bool:
    if not words:
        return True
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(w in text for w in words)


def github_repo(target: str) -> str | None:
    """'owner/repo', or a github.com address of it → 'owner/repo'.

    Plain string handling, no backtracking regex on what the user typed.
    """
    s = target.strip()
    for prefix in ("https://github.com/", "http://github.com/", "https://www.github.com/", "github.com/"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2 or (len(parts) > 2 and parts[2] != "releases"):
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not (_REPO_PART.fullmatch(owner) and _REPO_PART.fullmatch(repo)):
        return None
    return f"{owner}/{repo}"


def github_feed(target: str) -> tuple[str, str] | None:
    """'owner/repo' (or its URL) → (releases feed URL, 'owner/repo')."""
    repo = github_repo(target)
    return (f"https://github.com/{repo}/releases.atom", repo) if repo else None


# ------------------------------------------------------------------ watcher


class Watch:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self._pg = None
        # What changed, per item, for the alert text (filled by the checks).
        self._detail: dict[int, str] = {}
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: PLC0415

            self._pg = psycopg2.connect(PG_DSN, connect_timeout=3)
            self._pg.autocommit = True
        except Exception as exc:  # noqa: BLE001
            self._pg = None
            log.warning("Postgres unreachable for watch: %s", exc)

    def _ensure(self) -> None:
        if self._pg is None:
            self._connect()
        if self._pg is not None:
            try:
                self._pg.cursor().execute("SELECT 1")
            except Exception:  # noqa: BLE001
                self._connect()

    def list(self) -> list[dict]:
        self._ensure()
        if self._pg is None:
            return []
        try:
            cur = self._pg.cursor()
            cur.execute(
                "SELECT id, kind, target, last_state, last_checked, enabled "
                "FROM watch_items WHERE enabled ORDER BY id"
            )
            return [
                {
                    "id": r[0], "kind": r[1], "target": r[2],
                    "last_state": r[3], "last_checked": r[4], "enabled": r[5],
                }
                for r in cur.fetchall()
                if r[1] in KINDS
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("listing watch items failed: %s", exc)
            return []

    def _set_state(self, item_id: int, state: str | None) -> None:
        self._ensure()
        if self._pg is None:
            return
        try:
            self._pg.cursor().execute(
                "UPDATE watch_items SET last_state = coalesce(%s, last_state), last_checked = %s "
                "WHERE id = %s",
                (state, int(time.time()), item_id),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("watch state update failed: %s", exc)

    # ------------------------------------------------------------- checks

    async def _check_one(self, item: dict) -> None:
        try:
            state = await asyncio.to_thread(self._fetch_state, item)
        except Exception as exc:  # noqa: BLE001
            log.warning("check %s/%s failed: %s", item["kind"], item["target"], exc)
            self._set_state(item["id"], None)
            return
        if state is None:
            self._set_state(item["id"], None)
            return
        if item["last_state"] is None:
            # First pass: record without alerting.
            self._set_state(item["id"], state)
            return
        if state != item["last_state"]:
            self._set_state(item["id"], state)
            if item["id"] in self._detail:
                await self._alert(item)

    def _fetch_state(self, item: dict) -> str | None:
        kind, target, prev = item["kind"], item["target"], item.get("last_state") or ""
        iid = item["id"]
        self._detail.pop(iid, None)

        if kind == "web":
            text = visible_text(fetch(target))
            if len(text) < 40:
                return None  # blocked / empty page: not a real change
            self._detail[iid] = f"{target} has changed."
            return "h=" + hashlib.sha1(text.encode()).hexdigest()[:16]

        if kind == "price":
            url, below = split_price_target(target)
            found = find_price(fetch(url))
            if not found:
                return None
            price, cur = found
            old = None
            m = re.match(r"price=([0-9.]+)", prev)
            if m:
                old = float(m.group(1))
            if below is not None:
                zone = "below" if price <= below else "above"
                self._detail[iid] = (
                    f"Now {price:g} {cur} — at or under your {below:g} target."
                    if zone == "below" else f"Back above your target: {price:g} {cur}."
                )
                return f"price={price}|{zone}"
            if old:
                pct = (price - old) / old * 100
                arrow = "dropped" if price < old else "went up"
                self._detail[iid] = f"Price {arrow}: {old:g} → {price:g} {cur} ({pct:+.0f}%)."
            return f"price={price}"

        if kind in FEED_KINDS:
            base, words = split_condition(target)
            if kind == "news":
                items = news_items(base)
            elif kind == "github":
                gh = github_feed(base)
                items = feed_items(fetch(gh[0])) if gh else []
            else:
                items = feed_items(fetch(base))
            if not items:
                return None
            return self._feed_state(iid, items, prev, words)

        return None

    def _feed_state(self, iid: int, items: list[dict], prev: str, words: list[str]) -> str:
        """New items since last time, grouped into one alert; only those that
        mention one of `words` when a condition is set."""
        seen = set(re.findall(r"[0-9a-f]{8}", prev))
        fresh = [i for i in items if i["id"] not in seen and mentions(i, words)]
        if fresh:
            lines = [f"• {i['title']}" for i in fresh[:3]]
            more = f"\n+{len(fresh) - 3} more" if len(fresh) > 3 else ""
            self._detail[iid] = "\n".join(lines) + more
        # Remember a window of recent items (the ones skipped by the condition
        # too), so an item moving down the feed never counts as new again.
        keep = [i["id"] for i in items] + [x for x in prev.split(",") if x]
        return ",".join(dict.fromkeys(keep).keys())[: 9 * 40]

    async def _alert(self, item: dict) -> None:
        kind = item["kind"]
        emoji = {"web": "🌐", "price": "🏷️", "news": "📰", "rss": "📡", "github": "🚀"}.get(kind, "🔔")
        base = split_condition(item["target"])[0]
        label = {
            "web": "Page changed",
            "price": "Price change",
            "news": f"News · {base[:40]}",
            "rss": f"New in {urllib.parse.urlparse(base).netloc.removeprefix('www.')[:40] or 'your feed'}",
            "github": f"New release · {(github_feed(base) or ('', base))[1][:40]}",
        }.get(kind, "Change")
        try:
            from ocnotify import notify  # noqa: PLC0415

            notify(
                f"{emoji} {label}",
                self._detail.get(item["id"], item["target"])[:600],
                chat_id=self.chat_id,
                topic="watch",
                dedup_key=f"watch:{item['id']}:{hashlib.sha1(self._detail.get(item['id'], '').encode()).hexdigest()[:12]}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("watch push failed: %s", exc)

    # ------------------------------------------------------------- loop

    async def run(self) -> None:
        """Check each item about every BASE_INTERVAL seconds."""
        while True:
            try:
                for item in self.list():
                    if item["last_checked"] is None or time.time() - item["last_checked"] >= BASE_INTERVAL:
                        await self._check_one(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("watch loop error: %s", exc)
            await asyncio.sleep(60)


__all__ = ["Watch", "KINDS", "FEED_KINDS", "find_price", "visible_text", "news_items",
           "feed_items", "split_condition", "mentions", "github_feed", "github_repo"]
