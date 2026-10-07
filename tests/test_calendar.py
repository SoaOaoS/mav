"""Calendars (bot/occalendar.py): iCal parsing and recurrences, CalDAV against
a fake server, today's events in the briefing, and routines that fire
"N minutes before" an event.

Run: python3 -m unittest discover -s tests -v
"""

import asyncio
import base64
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bot"), str(ROOT / "dashboard" / "server")]
os.environ.setdefault("PG_DSN", "host=127.0.0.1 port=1 user=x dbname=x connect_timeout=1")

import occalendar  # noqa: E402
import ocbriefing  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


def ics(*events: str) -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def vevent(**props) -> str:
    lines = ["BEGIN:VEVENT"] + [f"{k.replace('_', '-')}{v if v.startswith((':', ';')) else ':' + v}"
                                for k, v in props.items()] + ["END:VEVENT"]
    return "\r\n".join(lines) + "\r\n"


class ParseTest(unittest.TestCase):
    def test_times_zones_and_text(self):
        text = ics(
            vevent(UID="a", SUMMARY="Dentist\\, then lunch", DTSTART=";TZID=Europe/Paris:20261008T093000",
                   DTEND=";TZID=Europe/Paris:20261008T100000", LOCATION="12 rue X\\nLyon"),
            vevent(UID="b", SUMMARY="Call", DTSTART="20261008T140000Z", DURATION="PT45M"),
            vevent(UID="c", SUMMARY="Holiday", DTSTART=";VALUE=DATE:20261009"),
        ).replace("SUMMARY:Call", "SUMMARY:Ca\r\n ll")  # a folded line
        a, b, c = occalendar.parse_ics(text)
        self.assertEqual(a["title"], "Dentist, then lunch")
        self.assertEqual(a["location"], "12 rue X\nLyon")
        self.assertEqual(a["start"], datetime(2026, 10, 8, 9, 30, tzinfo=PARIS))
        self.assertEqual(a["end"] - a["start"], timedelta(minutes=30))
        self.assertEqual(b["title"], "Call")
        self.assertEqual(b["start"], datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(b["end"] - b["start"], timedelta(minutes=45))
        self.assertTrue(c["all_day"])
        self.assertEqual(c["end"] - c["start"], timedelta(days=1))

    def test_alarms_are_not_mistaken_for_the_event(self):
        text = ics("BEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Real\r\nDTSTART:20261008T080000Z\r\n"
                   "BEGIN:VALARM\r\nTRIGGER:-PT10M\r\nDESCRIPTION:Alarm text\r\nSUMMARY:Not this\r\nEND:VALARM\r\n"
                   "END:VEVENT\r\n")
        (e,) = occalendar.parse_ics(text)
        self.assertEqual(e["title"], "Real")


class RecurrenceTest(unittest.TestCase):
    def window(self, day):
        start = datetime(2026, 10, day, tzinfo=PARIS)
        return start, start + timedelta(days=1)

    def test_weekly_by_day_keeps_its_wall_clock_across_dst(self):
        ev = occalendar.parse_ics(ics(vevent(
            UID="w", SUMMARY="Gym", DTSTART=";TZID=Europe/Paris:20260921T183000",
            DTEND=";TZID=Europe/Paris:20260921T193000", RRULE="FREQ=WEEKLY;BYDAY=MO,WE")))
        # Monday 26 Oct 2026 is after the end of summer time: still 18:30 local.
        got = occalendar.expand(ev, *self.window(26))
        self.assertEqual([e["start"].astimezone(PARIS).strftime("%a %H:%M") for e in got], ["Mon 18:30"])
        self.assertEqual(occalendar.expand(ev, *self.window(27)), [])  # Tuesday
        self.assertEqual(len(occalendar.expand(ev, *self.window(28))), 1)  # Wednesday

    def test_count_until_interval(self):
        ev = occalendar.parse_ics(ics(vevent(UID="c", SUMMARY="Course", DTSTART="20261001T090000Z",
                                             RRULE="FREQ=DAILY;INTERVAL=2;COUNT=3")))
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        days = [e["start"].day for e in occalendar.expand(ev, start, start + timedelta(days=30))]
        self.assertEqual(days, [1, 3, 5])
        ev = occalendar.parse_ics(ics(vevent(UID="u", SUMMARY="Until", DTSTART="20261001T090000Z",
                                             RRULE="FREQ=DAILY;UNTIL=20261003T235959Z")))
        self.assertEqual(len(occalendar.expand(ev, start, start + timedelta(days=30))), 3)

    def test_an_old_daily_event_still_reaches_today(self):
        ev = occalendar.parse_ics(ics(vevent(UID="d", SUMMARY="Pills", DTSTART="20150101T080000Z", RRULE="FREQ=DAILY")))
        self.assertEqual(len(occalendar.expand(ev, *self.window(8))), 1)

    def test_monthly_skips_short_months_and_yearly(self):
        ev = occalendar.parse_ics(ics(vevent(UID="m", SUMMARY="Rent", DTSTART="20260131T090000Z", RRULE="FREQ=MONTHLY")))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        months = [e["start"].month for e in occalendar.expand(ev, start, start + timedelta(days=365))]
        self.assertEqual(months, [1, 3, 5, 7, 8, 10, 12])
        ev = occalendar.parse_ics(ics(vevent(UID="y", SUMMARY="Birthday", DTSTART=";VALUE=DATE:19900315", RRULE="FREQ=YEARLY")))
        got = occalendar.expand(ev, datetime(2027, 3, 1, tzinfo=PARIS), datetime(2027, 4, 1, tzinfo=PARIS))
        self.assertEqual([(e["start"].year, e["all_day"]) for e in got], [(2027, True)])

    def test_exceptions_moves_and_cancellations(self):
        text = ics(
            vevent(UID="s", SUMMARY="Standup", DTSTART="20261005T080000Z", DURATION="PT15M",
                   RRULE="FREQ=DAILY;COUNT=5", EXDATE="20261006T080000Z"),
            vevent(UID="s", SUMMARY="Standup (moved)", DTSTART="20261007T100000Z", DURATION="PT15M",
                   RECURRENCE_ID="20261007T080000Z"),
            vevent(UID="s", SUMMARY="Standup", DTSTART="20261008T080000Z", RECURRENCE_ID="20261008T080000Z",
                   STATUS="CANCELLED"),
            vevent(UID="gone", SUMMARY="Cancelled", DTSTART="20261005T120000Z", STATUS="CANCELLED"),
        )
        start = datetime(2026, 10, 5, tzinfo=timezone.utc)
        got = [(e["start"].day, e["start"].hour, e["title"])
               for e in occalendar.expand(occalendar.parse_ics(text), start, start + timedelta(days=7))]
        self.assertEqual(got, [(5, 8, "Standup"), (7, 10, "Standup (moved)"), (9, 8, "Standup")])


# ---------------------------------------------------------------- CalDAV
TODAY = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def caldav_event(uid: str, title: str, start: datetime, minutes: int = 30) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    return vevent(UID=uid, SUMMARY=title, DTSTART=start.astimezone(timezone.utc).strftime(fmt),
                  DTEND=(start + timedelta(minutes=minutes)).astimezone(timezone.utc).strftime(fmt))


class FakeCalDAV(BaseHTTPRequestHandler):
    events = ""
    calls: list = []

    def log_message(self, *a):
        pass

    def _auth(self) -> bool:
        ok = self.headers.get("Authorization") == "Basic " + base64.b64encode(b"alex:app-pass").decode()
        if not ok:
            self.send_response(401)
            self.end_headers()
        return ok

    def _xml(self, body: str):
        data = body.encode()
        self.send_response(207)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PROPFIND(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        FakeCalDAV.calls.append(("PROPFIND", self.path))
        if not self._auth():
            return
        self._xml("""<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
          <d:response><d:href>/dav/alex/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
          <d:response><d:href>/dav/alex/personal/</d:href><d:propstat><d:prop>
            <d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>Personal</d:displayname></d:prop></d:propstat></d:response>
          <d:response><d:href>/dav/alex/inbox/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
        </d:multistatus>""")

    def do_REPORT(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        FakeCalDAV.calls.append(("REPORT", self.path, "expand" in body and "time-range" in body))
        if not self._auth():
            return
        from xml.sax.saxutils import escape  # noqa: PLC0415

        self._xml(f"""<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
          <d:response><d:href>/dav/alex/personal/1.ics</d:href><d:propstat><d:prop>
            <c:calendar-data>{escape(ics(FakeCalDAV.events))}</c:calendar-data></d:prop></d:propstat></d:response>
        </d:multistatus>""")


class CalDAVTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeCalDAV)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = occalendar.CALENDAR_FILE, occalendar.STATE_FILE
        occalendar.CALENDAR_FILE = self.tmp / "calendar.json"
        occalendar.STATE_FILE = self.tmp / "calendar_state.json"
        occalendar._cache.clear()
        FakeCalDAV.calls = []
        FakeCalDAV.events = (caldav_event("e1", "Dentist", TODAY.replace(hour=9, minute=30))
                             + caldav_event("e2", "Team meeting", TODAY.replace(hour=14)))
        self.src = occalendar.upsert({"kind": "caldav", "name": "Nextcloud", "url": self.base + "/dav/alex/",
                                      "username": "alex", "password": "app-pass"})["id"]

    def tearDown(self):
        occalendar.CALENDAR_FILE, occalendar.STATE_FILE = self.saved

    def test_todays_events_reach_the_briefing(self):
        got = occalendar.today()
        self.assertEqual([e["title"] for e in got], ["Dentist", "Team meeting"])
        self.assertEqual(got[0]["calendar"], "Personal")
        # Discovery found the calendar inside the account, and the server was
        # asked to expand recurrences for the day.
        self.assertIn(("REPORT", "/dav/alex/personal/", True), FakeCalDAV.calls)
        ctx = ocbriefing.build_context(events=occalendar.briefing_lines(got), now=TODAY.timestamp() + 7 * 3600)
        self.assertIn("## Today's calendar", ctx)
        self.assertIn("- 09:30–10:00 Dentist", ctx)
        self.assertIn("- 14:00–14:30 Team meeting", ctx)
        # Without a calendar, the section is left out entirely.
        self.assertNotIn("## Today's calendar", ocbriefing.build_context(now=TODAY.timestamp()))

    def test_reads_are_cached(self):
        occalendar.today()
        n = len(FakeCalDAV.calls)
        occalendar.today()
        self.assertEqual(len(FakeCalDAV.calls), n)

    def test_wrong_password_is_reported(self):
        occalendar.upsert({"id": self.src, "password": "wrong"})
        res = occalendar.test(self.src)
        self.assertFalse(res["ok"])
        self.assertIn("401", res["error"])
        self.assertEqual(occalendar.today(), [])  # the briefing goes on without it

    def test_a_routine_fires_15_minutes_before_and_only_once(self):
        import mav_worker  # noqa: PLC0415

        meeting = datetime.now().astimezone().replace(second=0, microsecond=0) + timedelta(minutes=20)
        FakeCalDAV.events = caldav_event("m1", "Board meeting", meeting) + caldav_event("m2", "Lunch", meeting)
        jobs = self.tmp / "jobs.json"
        jobs.write_text('[{"name": "Prep", "prompt": "What do I need?", '
                        '"before_event": {"minutes": 15, "contains": "meeting"}}]')
        ran = []
        saved = mav_worker.JOBS_FILE, mav_worker._spawn, mav_worker.run_job
        mav_worker.JOBS_FILE = jobs
        mav_worker._spawn = lambda coro: (ran.append(coro.cr_frame.f_locals.get("extra_context")), coro.close())
        try:
            too_early = meeting - timedelta(minutes=16)
            self.assertEqual(asyncio.run(mav_worker.calendar_once(too_early)), 0)
            on_time = meeting - timedelta(minutes=15)
            self.assertEqual(asyncio.run(mav_worker.calendar_once(on_time)), 1)
            self.assertIn("Board meeting", ran[0])
            self.assertNotIn("Lunch", ran[0])
            # The next tick (and a restart) does not fire it again.
            self.assertEqual(asyncio.run(mav_worker.calendar_once(on_time + timedelta(seconds=40))), 0)
        finally:
            mav_worker.JOBS_FILE, mav_worker._spawn, mav_worker.run_job = saved


class DueBeforeTest(unittest.TestCase):
    def ev(self, title="Meeting", hour=10, all_day=False):
        start = datetime(2026, 10, 8, hour, tzinfo=PARIS)
        return {"uid": title, "title": title, "start": start, "end": start + timedelta(hours=1),
                "all_day": all_day, "location": ""}

    def test_the_moment_and_the_filters(self):
        job = {"name": "Prep", "before_event": {"minutes": 15}}
        evts = [self.ev(), self.ev("Holiday", 0, all_day=True)]
        at = datetime(2026, 10, 8, 9, 45, 20, tzinfo=PARIS)
        self.assertEqual([e["title"] for _, e in occalendar.due_before([job], evts, at, set())], ["Meeting"])
        self.assertEqual(occalendar.due_before([job], evts, at - timedelta(minutes=2), set()), [])
        fired = {occalendar.fire_key(job, evts[0])}
        self.assertEqual(occalendar.due_before([job], evts, at, fired), [])
        off = dict(job, enabled=False)
        self.assertEqual(occalendar.due_before([off], evts, at, set()), [])
        only = {"name": "X", "before_event": {"minutes": 15, "contains": "dentist"}}
        self.assertEqual(occalendar.due_before([only], evts, at, set()), [])
        self.assertIsNone(occalendar.before_rule({"before_event": {"minutes": "soon"}}))
        self.assertIsNone(occalendar.before_rule({"before_event": {"minutes": 99999}}))


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.saved = occalendar.CALENDAR_FILE
        occalendar.CALENDAR_FILE = Path(tempfile.mkdtemp()) / "calendar.json"

    def tearDown(self):
        occalendar.CALENDAR_FILE = self.saved

    def test_secrets_are_masked_and_kept(self):
        secret = "https://calendar.google.com/calendar/ical/abc%40group/private-0123456789/basic.ics"
        a = occalendar.upsert({"kind": "ics", "name": "Google", "url": secret.replace("https://", "webcal://")})["id"]
        b = occalendar.upsert({"kind": "caldav", "url": "https://dav.example.org/", "username": "me", "password": "p4ss"})["id"]
        view = {v["id"]: v for v in occalendar.public_view()}
        self.assertEqual(view[a]["url"], "https://calendar.google.com/" + occalendar.MASK)
        self.assertEqual(view[b]["password"], occalendar.MASK)
        self.assertNotIn("private-0123456789", str(view))
        self.assertNotIn("p4ss", str(view))
        occalendar.upsert({**view[a], "name": "Work"})
        occalendar.upsert({**view[b], "username": "me2"})
        stored = {s["id"]: s for s in occalendar.load()}
        self.assertEqual((stored[a]["url"], stored[a]["name"]), (secret, "Work"))
        self.assertEqual((stored[b]["password"], stored[b]["username"]), ("p4ss", "me2"))
        self.assertEqual(oct(occalendar.CALENDAR_FILE.stat().st_mode & 0o777), "0o600")

    def test_bad_addresses_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://x.org/c.ics", "https://user:pw@x.org/c", "not a url"):
            self.assertFalse(occalendar.upsert({"kind": "ics", "url": url})["ok"], url)
        self.assertFalse(occalendar.upsert({"kind": "exchange", "url": "https://x.org"})["ok"])


class RoutineFormTest(unittest.TestCase):
    """The web form sends the routine's own keys: each kind must survive saving."""

    def setUp(self):
        import mav_api  # noqa: PLC0415

        self.api = mav_api
        self.saved = mav_api.JOBS_FILE
        mav_api.JOBS_FILE = Path(tempfile.mkdtemp()) / "jobs.json"

    def tearDown(self):
        self.api.JOBS_FILE = self.saved

    def test_monthly_event_and_before_event_routines(self):
        save = self.api.save_job
        monthly = save({"name": "Rent", "prompt": "pay", "time": "09:00", "days_of_month": [1]})["job"]
        self.assertEqual(monthly["days_of_month"], [1])
        self.assertNotIn("days", monthly)  # it was saved as a daily routine before
        event = save({"name": "PR", "prompt": "review", "on_event": {"kind": "github", "contains": "opened"}})
        self.assertTrue(event["ok"], event)  # was refused: "Pick a time"
        self.assertEqual(event["job"]["on_event"], {"kind": "github", "contains": "opened"})
        before = save({"name": "Leave", "prompt": "traffic?", "time": "08:00",
                       "before_event": {"minutes": 15, "contains": "meeting"}})["job"]
        self.assertEqual(before["before_event"], {"minutes": 15, "contains": "meeting"})
        self.assertNotIn("time", before)
        self.assertFalse(save({"name": "Bad", "prompt": "x", "before_event": {"minutes": -5}})["ok"])


if __name__ == "__main__":
    unittest.main()
