"""Calendars: what is on today, and routines that fire "N minutes before".

Two kinds of source, both read-only:

  caldav  a CalDAV calendar or account (Nextcloud, iCloud, Fastmail,
          Radicale…): the server expands recurring events for us.
  ics     a private iCal link (Google Calendar "secret address", Outlook,
          Proton…): parsed here, with the common recurrences.

Sources live in ``BOT_DIR/calendar.json`` (0600, passwords inside). The web
app edits them (secrets come back masked); the worker reads them for the
daily briefing and for ``before_event`` routines::

    {"name": "Leave for the meeting", "prompt": "…",
     "before_event": {"minutes": 15, "contains": "meeting"}}

Pure parts (parsing, expansion, which routine is due) are separate from the
network, for tests. Nothing here raises to the caller.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # noqa: BLE001
    ZoneInfo = None  # type: ignore[assignment]

log = logging.getLogger("occalendar")

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).resolve().parent))
CALENDAR_FILE = Path(os.environ.get("MAV_CALENDAR_FILE", BOT_DIR / "calendar.json"))
STATE_FILE = BOT_DIR / "calendar_state.json"
TIMEOUT = 15
CACHE_S = 300          # a source is read at most every 5 minutes
MAX_ICS = 5_000_000    # bytes read from a feed
MASK = "••••"
KINDS = ("caldav", "ics")

DAV = "{DAV:}"
CAL = "{urn:ietf:params:xml:ns:caldav}"
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def local_tz():
    return datetime.now().astimezone().tzinfo


# ------------------------------------------------------------------ ICS
def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _prop(line: str) -> tuple[str, dict, str]:
    """'DTSTART;TZID="Europe/Paris":2026…' → ('DTSTART', {'TZID': …}, '2026…')."""
    head, value, in_q = "", "", False
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return line.upper(), {}, ""
    parts = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', head)
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _text(v: str) -> str:
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v).strip()


def _zone(tzid: str | None):
    if not tzid:
        return None
    if ZoneInfo is not None:
        for name in (tzid, tzid.split("/", 1)[-1] if tzid.startswith("/") else tzid):
            try:
                return ZoneInfo(name)
            except Exception:  # noqa: BLE001
                continue
    return local_tz()  # unknown (e.g. Windows names): the server's own zone


def parse_dt(value: str, params: dict) -> tuple[datetime, bool]:
    """(aware datetime, all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=local_tz()), True
    utc = value.endswith("Z")
    d = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        return d.replace(tzinfo=timezone.utc), False
    return d.replace(tzinfo=_zone(params.get("TZID")) or local_tz()), False


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse_ics(text: str) -> list[dict]:
    """The VEVENTs of an iCalendar text, as dicts (no expansion yet)."""
    events, cur, depth = [], None, 0
    for line in _unfold(text):
        name, params, value = _prop(line)
        if name == "BEGIN":
            if value.upper() == "VEVENT" and depth == 0:
                cur = {"exdates": []}
            elif cur is not None:
                depth += 1  # VALARM inside an event: ignore its properties
            continue
        if name == "END":
            if cur is not None and depth:
                depth -= 1
            elif cur is not None and value.upper() == "VEVENT":
                if cur.get("start"):
                    events.append(cur)
                cur = None
            continue
        if cur is None or depth:
            continue
        try:
            if name == "SUMMARY":
                cur["title"] = _text(value)
            elif name == "LOCATION":
                cur["location"] = _text(value)
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "STATUS":
                cur["status"] = value.strip().upper()
            elif name == "DTSTART":
                cur["start"], cur["all_day"] = parse_dt(value, params)
            elif name == "DTEND":
                cur["end"], _ = parse_dt(value, params)
            elif name == "DURATION":
                cur["duration"] = _duration(value)
            elif name == "RRULE":
                cur["rrule"] = dict(p.partition("=")[::2] for p in value.upper().split(";") if "=" in p)
            elif name == "EXDATE":
                cur["exdates"] += [parse_dt(v, params)[0] for v in value.split(",") if v.strip()]
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"], _ = parse_dt(value, params)
        except (ValueError, KeyError):
            continue
    for e in events:
        if "end" not in e:
            e["end"] = e["start"] + (e.pop("duration", None) or (timedelta(days=1) if e["all_day"] else timedelta(0)))
        e.pop("duration", None)
        e.setdefault("title", "(no title)")
        e.setdefault("uid", f"{e['title']}@{e['start'].isoformat()}")
    return events


def _add_months(d: datetime, n: int) -> datetime | None:
    y, m = divmod(d.month - 1 + n, 12)
    try:
        return d.replace(year=d.year + y, month=m + 1)
    except ValueError:
        return None  # e.g. the 31st in a 30-day month: no occurrence


def _occurrences(ev: dict, start: datetime, end: datetime, cap: int = 2000):
    """Start times of a (possibly recurring) event that overlap [start, end)."""
    length = ev["end"] - ev["start"]
    rule = ev.get("rrule")
    if not rule:
        if ev["start"] < end and ev["start"] + max(length, timedelta(seconds=1)) > start:
            yield ev["start"]
        return
    freq = rule.get("FREQ")
    step = max(1, int(rule.get("INTERVAL") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        try:
            until = parse_dt(rule["UNTIL"], {})[0]
        except ValueError:
            until = None
    bydays = [d[-2:] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS]
    excluded = {x.timestamp() for x in ev.get("exdates", [])}
    seen = 0
    base = ev["start"]

    # Jump close to the window (an old daily event must not exhaust the cap
    # before today). Not with COUNT: occurrences are counted from the start.
    i0 = 0
    if count is None and start > base:
        gap = start - base
        units = {"DAILY": gap.days, "WEEKLY": gap.days // 7,
                 "MONTHLY": (start.year - base.year) * 12 + start.month - base.month,
                 "YEARLY": start.year - base.year}.get(freq, 0)
        i0 = max(0, units // step - 1)

    def candidates():
        i = i0
        while i < i0 + cap:
            if freq == "DAILY":
                yield base + timedelta(days=i * step)
            elif freq == "WEEKLY":
                week = base + timedelta(weeks=i * step)
                monday = week - timedelta(days=week.weekday())
                days = sorted({WEEKDAYS.index(d) for d in bydays} or {base.weekday()})
                for wd in days:
                    c = monday + timedelta(days=wd)
                    if c >= base:
                        yield c
            elif freq == "MONTHLY":
                c = _add_months(base, i * step)
                if c:
                    yield c
            elif freq == "YEARLY":
                try:
                    yield base.replace(year=base.year + i * step)
                except ValueError:
                    pass
            else:
                yield base
                return
            i += 1

    for occ in candidates():
        if until and occ > until:
            return
        seen += 1
        if count and seen > count:
            return
        if occ >= end:
            return
        if occ.timestamp() in excluded:
            continue
        if occ + max(length, timedelta(seconds=1)) > start:
            yield occ


def expand(events: list[dict], start: datetime, end: datetime, calendar: str = "") -> list[dict]:
    """Every occurrence in [start, end), moved instances and cancellations applied."""
    moved = {(e["uid"], e["recurrence_id"].timestamp()) for e in events if e.get("recurrence_id")}
    out = []
    for e in events:
        if e.get("status") == "CANCELLED" and not e.get("recurrence_id"):
            continue
        length = e["end"] - e["start"]
        for occ in _occurrences(e, start, end):
            if not e.get("recurrence_id") and (e["uid"], occ.timestamp()) in moved:
                continue  # this instance was moved or cancelled: its override decides
            if e.get("status") == "CANCELLED":
                continue
            out.append({
                "uid": e["uid"], "title": e["title"], "location": e.get("location", ""),
                "start": occ, "end": occ + length, "all_day": e["all_day"], "calendar": calendar,
            })
    out.sort(key=lambda x: (x["start"], x["title"]))
    return out


# ------------------------------------------------------------------ network
def _request(url: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None,
             user: str = "", password: str = "", limit: int = MAX_ICS) -> tuple[int, bytes]:
    h = {"User-Agent": "Mav", **(headers or {})}
    if user or password:
        h["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (validated http/https)
            return r.status, r.read(limit)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _report_body(start: datetime, end: datetime) -> bytes:
    s = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    e = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop><C:calendar-data><C:expand start="{s}" end="{e}"/></C:calendar-data></D:prop>
  <C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">
    <C:time-range start="{s}" end="{e}"/>
  </C:comp-filter></C:comp-filter></C:filter>
</C:calendar-query>""".encode()


_PROPFIND = b"""<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:"><D:prop><D:resourcetype/><D:displayname/></D:prop></D:propfind>"""


def _calendars(src: dict) -> list[tuple[str, str]]:
    """(url, name) of the calendars behind a CalDAV address: the address itself
    when it is a calendar, else the calendars directly inside it."""
    code, data = _request(src["url"], "PROPFIND", _PROPFIND, {"Depth": "1", "Content-Type": "application/xml"},
                          src.get("username", ""), src.get("password", ""), limit=2_000_000)
    if code not in (200, 207) or not data:
        raise OSError(f"the server answered HTTP {code}" if code else "no answer")
    root = ET.fromstring(data)
    found = []
    for resp in root.iter(f"{DAV}response"):
        href = (resp.findtext(f"{DAV}href") or "").strip()
        rtype = resp.find(f".//{DAV}resourcetype")
        if href and rtype is not None and rtype.find(f"{CAL}calendar") is not None:
            name = (resp.findtext(f".//{DAV}displayname") or "").strip()
            found.append((urllib.parse.urljoin(src["url"], href), name))
    return found


def fetch_source(src: dict, start: datetime, end: datetime) -> list[dict]:
    """Occurrences of one source in [start, end). Raises OSError on failure."""
    label = src.get("name") or src.get("kind")
    if src["kind"] == "ics":
        code, data = _request(src["url"])
        if code != 200:
            raise OSError(f"the server answered HTTP {code}")
        return expand(parse_ics(data.decode("utf-8", "replace")), start, end, label)
    out = []
    for url, name in _calendars(src) or [(src["url"], "")]:
        code, data = _request(url, "REPORT", _report_body(start, end),
                              {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
                              src.get("username", ""), src.get("password", ""))
        if code not in (200, 207):
            raise OSError(f"the server answered HTTP {code}")
        for el in ET.fromstring(data).iter(f"{CAL}calendar-data"):
            out += expand(parse_ics(el.text or ""), start, end, name or label)
    out.sort(key=lambda x: (x["start"], x["title"]))
    return out


# ------------------------------------------------------------------ sources
def load() -> list[dict]:
    try:
        data = json.loads(CALENDAR_FILE.read_text())
    except Exception:  # noqa: BLE001
        return []
    return [s for s in (data.get("sources") if isinstance(data, dict) else []) or []
            if isinstance(s, dict) and s.get("kind") in KINDS and s.get("url")]


def _save(sources: list[dict]) -> None:
    CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CALENDAR_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"sources": sources}, fh, indent=2)
    os.replace(tmp, CALENDAR_FILE)
    _cache.clear()


def _mask_url(url: str) -> str:
    """An iCal link is a secret too: keep the host, hide the rest."""
    u = urllib.parse.urlparse(url)
    return f"{u.scheme}://{u.netloc}/{MASK}" if u.netloc else MASK


def public_view() -> list[dict]:
    out = []
    for s in load():
        out.append({
            "id": s.get("id"), "kind": s["kind"], "name": s.get("name", ""), "enabled": s.get("enabled", True),
            "url": _mask_url(s["url"]) if s["kind"] == "ics" else s["url"],
            "username": s.get("username", ""), "password": MASK if s.get("password") else "",
        })
    return out


def _valid_url(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return u.scheme in ("http", "https") and bool(u.netloc) and not u.username and not u.password


def upsert(payload: dict) -> dict:
    sources = load()
    sid = str(payload.get("id") or "")
    old = next((s for s in sources if s.get("id") == sid), None) if sid else None
    kind = payload.get("kind") or (old or {}).get("kind")
    if kind not in KINDS:
        return {"ok": False, "error": "Pick CalDAV or an iCal link."}
    url = str(payload.get("url") or "").strip()
    if old and (not url or MASK in url):
        url = old["url"]
    url = re.sub(r"^webcals?://", "https://", url, flags=re.I)
    if not _valid_url(url):
        return {"ok": False, "error": "Enter the calendar's https:// address."}
    password = str(payload.get("password") or "")
    if old and (not password or password == MASK):
        password = old.get("password", "")
    src = {"id": sid or secrets.token_hex(3), "kind": kind,
           "name": str(payload.get("name") or "").strip()[:40] or ("Calendar" if kind == "caldav" else "iCal"),
           "url": url, "enabled": bool(payload.get("enabled", True))}
    if kind == "caldav":
        src["username"] = str(payload.get("username") or "").strip()[:200]
        src["password"] = password
    sources = [src if s is old else s for s in sources] if old else sources + [src]
    _save(sources)
    return {"ok": True, "id": src["id"]}


def remove(sid: str) -> dict:
    sources = load()
    keep = [s for s in sources if s.get("id") != sid]
    if len(keep) == len(sources):
        return {"ok": False, "error": "No such calendar."}
    _save(keep)
    return {"ok": True}


_cache: dict = {}


def events(start: datetime, end: datetime, *, sources: list[dict] | None = None) -> list[dict]:
    """Occurrences from every enabled source, cached a few minutes per source."""
    out = []
    for src in sources if sources is not None else load():
        if not src.get("enabled", True):
            continue
        key = (src.get("id"), src.get("url"), int(start.timestamp() // 60), int(end.timestamp() // 60))
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            out += hit[1]
            continue
        try:
            got = fetch_source(src, start, end)
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar %s: %s", src.get("name"), exc)
            continue
        _cache[key] = (time.time(), got)
        out += got
    out.sort(key=lambda x: (x["start"], x["title"]))
    return out


def test(sid: str) -> dict:
    src = next((s for s in load() if s.get("id") == sid), None)
    if not src:
        return {"ok": False, "error": "No such calendar."}
    now = datetime.now().astimezone()
    try:
        got = fetch_source(src, now, now + timedelta(days=14))
    except ET.ParseError:
        return {"ok": False, "error": "That address does not answer like a calendar."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not read it: {exc}"}
    return {"ok": True, "upcoming": [view(e) for e in got[:5]], "count": len(got)}


# ------------------------------------------------------------------ views
def view(e: dict) -> dict:
    return {"title": e["title"], "location": e.get("location", ""), "all_day": e["all_day"],
            "start": int(e["start"].timestamp()), "end": int(e["end"].timestamp()),
            "calendar": e.get("calendar", "")}


def day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = (now or datetime.now()).astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def today(now: datetime | None = None) -> list[dict]:
    if not load():
        return []
    return events(*day_window(now))


def briefing_lines(evts: list[dict]) -> list[str]:
    """'- 09:30–10:00 Dentist (12 rue X)' for the briefing context."""
    lines = []
    for e in evts[:15]:
        if e["all_day"]:
            when = "all day"
        else:
            s, en = e["start"].astimezone(), e["end"].astimezone()
            when = s.strftime("%H:%M") + (f"–{en.strftime('%H:%M')}" if en > s else "")
        where = f" ({e['location']})" if e.get("location") else ""
        lines.append(f"- {when} {e['title']}{where}")
    return lines


# ------------------------------------------------------------------ routines
def before_rule(job: dict) -> dict | None:
    rule = job.get("before_event")
    if not isinstance(rule, dict):
        return None
    try:
        minutes = int(rule.get("minutes"))
    except (TypeError, ValueError):
        return None
    if not 0 <= minutes <= 24 * 60:
        return None
    return {"minutes": minutes, "contains": str(rule.get("contains") or "").strip().lower()}


def due_before(jobs: list[dict], evts: list[dict], now: datetime, fired: set,
               window_s: int = 90) -> list[tuple[dict, dict]]:
    """(job, event) pairs whose "N minutes before" moment is now.

    A moment counts when it fell in the last `window_s` seconds (the loop runs
    every minute) and was not fired already (`fired` holds job|uid|start keys,
    so a restart does not fire twice). All-day events never trigger.
    """
    out = []
    for job in jobs:
        rule = before_rule(job)
        if not rule or not job.get("enabled", True):
            continue
        for e in evts:
            if e["all_day"]:
                continue
            if rule["contains"] and rule["contains"] not in f"{e['title']} {e.get('location', '')}".lower():
                continue
            moment = e["start"] - timedelta(minutes=rule["minutes"])
            if not (now - timedelta(seconds=window_s) < moment <= now):
                continue
            key = fire_key(job, e)
            if key not in fired:
                out.append((job, e))
    return out


def fire_key(job: dict, e: dict) -> str:
    return f"{job.get('name')}|{e['uid']}|{int(e['start'].timestamp())}"


def event_context(e: dict, minutes: int) -> str:
    lines = [
        "<calendar-event>",
        f"This routine runs {minutes} minutes before this event:",
        f"- {e['title']}",
        f"- starts {e['start'].astimezone().strftime('%A %H:%M')}, ends {e['end'].astimezone().strftime('%H:%M')}",
    ]
    if e.get("location"):
        lines.append(f"- where: {e['location']}")
    lines.append("</calendar-event>")
    return "\n".join(lines)


def max_lead(jobs: list[dict]) -> int:
    return max((r["minutes"] for r in map(before_rule, jobs) if r), default=-1)


def load_fired() -> set:
    try:
        data = json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return set()
    cutoff = time.time() - 2 * 86400
    return {k for k, ts in data.items() if ts >= cutoff}


def save_fired(fired: set) -> None:
    try:
        old = json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        old = {}
    now = int(time.time())
    cutoff = now - 2 * 86400
    data = {k: ts for k, ts in old.items() if ts >= cutoff}
    for k in fired:
        data.setdefault(k, now)
    try:
        STATE_FILE.write_text(json.dumps(data))
    except OSError as exc:
        log.warning("calendar state: %s", exc)
