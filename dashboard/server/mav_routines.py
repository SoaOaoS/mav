"""Routines and what fires them: the jobs file, schedules and conditions,
templates, the daily briefing, the first-run welcome, background actions,
keep-an-eye-on items and incoming events.

Part of the web app server (see mav_api.py).
"""

from __future__ import annotations

import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import mav_core
import mav_store
import mav_chat
import mav_stream
import mav_media


def job_owner(name: str, jobs: list | None = None) -> int:
    """Who a routine belongs to (routines without an owner are the owner's)."""
    if jobs is None:
        jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    job = next((j for j in jobs or [] if isinstance(j, dict) and j.get("name") == name), None)
    try:
        return int((job or {}).get("owner", mav_core.DEFAULT_CHAT_ID))
    except (TypeError, ValueError):
        return mav_core.DEFAULT_CHAT_ID


def _mine(job) -> bool:
    if not isinstance(job, dict):
        return False
    try:
        return int(job.get("owner", mav_core.DEFAULT_CHAT_ID)) == mav_core.uid()
    except (TypeError, ValueError):
        return False


def my_jobs() -> list[dict]:
    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    return [j for j in jobs if _mine(j)] if isinstance(jobs, list) else []


def get_jobs() -> dict:
    jobs = my_jobs()
    state = mav_core.read_json(mav_core.JOBS_STATE, {})
    # routine name -> its chat, when it ran at least once
    head = mav_chat.PREFIX + ROUTINE_PREFIX
    chats = {
        str(s_.get("title", ""))[len(head):]: s_["id"]
        for s_ in mav_chat._list_raw_sessions()
        if str(s_.get("title", "")).startswith(head)
    }
    out = []
    for j in jobs:
        out.append(
            {
                "name": j.get("name"),
                "description": j.get("description", ""),
                "time": j.get("time", ""),
                "every_minutes": j.get("every_minutes"),
                "days": j.get("days", []),
                "agent": j.get("agent", ""),
                "prompt": j.get("prompt", ""),
                "enabled": j.get("enabled", True),
                "days_of_month": j.get("days_of_month", []),
                "last_day_of_month": bool(j.get("last_day_of_month")),
                "on_event": j.get("on_event"),
                "before_event": j.get("before_event"),
                "skip_if": j.get("skip_if"),
                "channels": j.get("channels") or [],
                "snooze_until": j.get("snooze_until", 0),
                "last_run": state.get(j.get("name")),
                "running": j.get("name") in _running_jobs,
                "session": chats.get(j.get("name")),
            }
        )
    return {"jobs": out}


JOB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}$")


JOB_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def delete_job(name: str) -> bool:
    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    keep = [j for j in jobs if not (j.get("name") == name and _mine(j))]
    if len(keep) == len(jobs):
        return False
    mav_core.write_json(mav_core.JOBS_FILE, keep)
    return True


def _schedule_from_payload(payload: dict) -> dict:
    """Translate the web form's schedule fields into jobs.json keys."""
    every = payload.get("every_minutes")
    try:
        every = int(every) if every not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        every = -1  # sentinel: invalid
    out: dict = {"every_minutes": every}
    if every < 0:
        return out
    if every:
        return out
    out["every_minutes"] = 0
    time_ = str(payload.get("time") or "").strip()
    if time_:
        out["time"] = time_
    mode = str(payload.get("schedule_mode") or "").strip().lower()
    if not mode:
        # The web form sends the routine's own keys (on_event, before_event,
        # days_of_month…) rather than a mode: read the mode from them, or a
        # monthly routine would be saved as a daily one.
        ev, before = payload.get("on_event"), payload.get("before_event")
        if isinstance(before, dict):
            mode = "before_event"
            payload = {**payload, "before_minutes": before.get("minutes"),
                       "before_contains": before.get("contains", "")}
        elif ev:
            mode = "event"
            ev = {"kind": ev} if isinstance(ev, str) else ev if isinstance(ev, dict) else {}
            payload = {**payload, "event_kind": ev.get("kind") or "custom",
                       "event_contains": ev.get("contains", "")}
        elif payload.get("days_of_month") or payload.get("last_day_of_month"):
            mode = "monthly"
    if mode == "monthly":
        dom = payload.get("days_of_month") or []
        if isinstance(dom, str):
            dom = [d for d in re.split(r"[,\s]+", dom) if d]
        dom = [int(d) for d in dom if str(d).strip().isdigit()]
        last = bool(payload.get("last_day_of_month"))
        if not dom and not last:
            return {**out, "_error": "Pick a day of the month (or the last day)."}
        if dom:
            out["days_of_month"] = dom
        if last:
            out["last_day_of_month"] = True
        return out
    if mode == "before_event":
        try:
            minutes = int(payload.get("before_minutes"))
        except (TypeError, ValueError):
            minutes = -1
        if not 0 <= minutes <= 24 * 60:
            return {**out, "_error": "How many minutes before the event (0 to 1440)?"}
        rule: dict = {"minutes": minutes}
        needle = str(payload.get("before_contains") or "").strip()[:80]
        if needle:
            rule["contains"] = needle
        out["before_event"] = rule
        out.pop("time", None)  # fired by the calendar, not the clock
        return out
    if mode == "event":
        kind = str(payload.get("event_kind") or "custom").strip()
        ev: dict = {"kind": kind}
        needle = str(payload.get("event_contains") or "").strip()
        if needle:
            ev["contains"] = needle
        out["on_event"] = ev
        out.pop("time", None)
        return out
    days = [d for d in (payload.get("days") or []) if d in JOB_DAYS]
    out["days"] = days or JOB_DAYS
    return out


def _condition_from_payload(payload: dict) -> dict | None:
    """Build a ``skip_if`` block, or None when there is no condition."""
    ctype = str(payload.get("condition_type") or "").strip().lower()
    if not ctype or ctype == "none":
        return None
    cond: dict = {"type": ctype}
    value = payload.get("condition_value")
    if value not in (None, ""):
        cond["value"] = value
    source = str(payload.get("condition_source") or "").strip()
    if source:
        cond["source"] = source
    negate = payload.get("condition_negate")
    if negate in (True, "true", "on", 1, "1"):
        cond["negate"] = True
    if ctype == "number":
        op = str(payload.get("condition_op") or ">=").strip()
        cond["op"] = op if op in (">", "<", ">=", "<=", "==", "!=") else ">="
    return cond


def save_job(payload: dict) -> dict:
    """Create or update a routine (`original` = name before a rename).

    Extends the simple form with: monthly schedules, event triggers, a
    condition (`skip_if`) and snooze (`snooze_until`, an epoch second).
    """
    name = str(payload.get("name") or "").strip()
    if not JOB_NAME_RE.match(name):
        return {"ok": False, "error": "Give the automation a name (letters, digits, - _ .)."}
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Write what Mav should do."}

    sched = _schedule_from_payload(payload)
    if sched.pop("_error", None):
        return {"ok": False, "error": sched.pop("_error", "Invalid schedule.")}
    if not mav_core.is_owner() and (sched.get("on_event") or sched.get("before_event")):
        # Events and calendars are the owner's: a member's routine runs on a schedule.
        return {"ok": False, "error": "Pick a time or an interval."}
    if not sched.get("every_minutes") and not sched.get("on_event") and not sched.get("before_event"):
        # A timed job needs a valid time; an event job does not.
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(sched.get("time") or "")):
            return {"ok": False, "error": "Pick a time (HH:MM), an interval, or an event."}

    job = {
        "name": name,
        "description": str(payload.get("description") or "").strip()[:200],
        "prompt": prompt,
        "agent": str(payload.get("agent") or "").strip(),
        "enabled": bool(payload.get("enabled", True)),
        **sched,
    }
    cond = _condition_from_payload(payload)
    if cond:
        job["skip_if"] = cond
    if not mav_core.is_owner():
        job["owner"] = mav_core.uid()
    chans = payload.get("channels")
    # Channels (ntfy, Discord…) are the owner's: a member's reports go to
    # their own devices.
    if isinstance(chans, list) and chans and mav_core.is_owner():
        # Where its reports go: "push" and/or channel ids (empty = everywhere).
        job["channels"] = [str(c)[:16] for c in chans if isinstance(c, str)][:10]
    try:
        snooze = int(payload.get("snooze_until") or 0)
    except (TypeError, ValueError):
        snooze = 0
    if snooze > int(time.time()):
        job["snooze_until"] = snooze

    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    if not isinstance(jobs, list):
        jobs = []
    original = str(payload.get("original") or "").strip()
    if name != original and any(j.get("name") == name for j in jobs):
        return {"ok": False, "error": f"An automation named \"{name}\" already exists."}
    target = original or name
    if any(j.get("name") == target and not _mine(j) for j in jobs):
        return {"ok": False, "error": f"An automation named \"{name}\" already exists."}
    replaced = False
    for i, j in enumerate(jobs):
        if j.get("name") == target:
            # Keep unknown keys (retries, chat_id…) from hand-edited files.
            keep = {k: v for k, v in j.items() if k not in (
                "time", "every_minutes", "days", "days_of_month",
                "last_day_of_month", "on_event", "before_event", "skip_if", "snooze_until", "channels",
            )}
            jobs[i] = {**keep, **job}
            replaced = True
            break
    if not replaced:
        jobs.append(job)
    mav_core.write_json(mav_core.JOBS_FILE, jobs)
    mav_core._chown_user(mav_core.JOBS_FILE)
    return {"ok": True, "job": job}


def job_templates(lang: str = "en") -> dict:
    """Ready-made routines for the dashboard's two-click creation."""
    if not mav_core.ocroutine_templates:
        return {"templates": []}
    return {"templates": [mav_core.ocroutine_templates.localized(t, lang) for t in mav_core.ROUTINE_TEMPLATES]}


def template_to_job(template_id: str, *, name: str = "", lang: str = "en") -> dict:
    """Expand a template into a concrete job (not saved here)."""
    if not mav_core.ocroutine_templates:
        return {"ok": False, "error": "Templates unavailable."}
    tpl = mav_core.ocroutine_templates.get(template_id, lang)
    if not tpl:
        return {"ok": False, "error": "Unknown template."}
    when = dict(tpl.get("when") or {})
    job = {
        "name": (name or tpl["label"])[:61].strip(),
        "description": tpl.get("description", "")[:200],
        "prompt": tpl["prompt"],
        "agent": tpl.get("agent", ""),
        "enabled": True,
    }
    job.update(when)
    if tpl.get("skip_if"):
        job["skip_if"] = dict(tpl["skip_if"])
    return {"ok": True, "job": job}


def detect_routine(text: str) -> dict:
    """Turn a chat sentence into a routine draft (multilingual)."""
    if not mav_core.ocroutine_nl:
        return {"draft": None}
    draft = mav_core.ocroutine_nl.detect(text)
    return {"draft": draft}


def get_proactivity() -> dict:
    """The user's proactivity preference + what is waiting per level."""
    level = "normal"
    try:
        rows = mav_core.pg_query(
            "select value from preferences where key = 'notify.proactivity' and chat_id = %s limit 1",
            (mav_core.uid(),))
        if rows and rows[0].get("value"):
            level = rows[0]["value"]
    except Exception:  # noqa: BLE001
        pass
    counts = {"pending": 0, "low": 0}
    who, args = mav_core.mine()
    try:
        counts["pending"] = int(mav_core.pg_query(
            f"select count(*) as n from notify_digest where not sent and {who}", args
        )[0]["n"])
        counts["low"] = counts["pending"]
    except Exception:  # noqa: BLE001
        pass
    owner = mav_core.is_owner()  # drafts and actions are the owner's
    drafts = len(mav_core.DRAFTS.list("pending", limit=200)) if mav_core.DRAFTS and owner else 0
    actions = mav_core.ACTIONS.list("running", limit=200) if mav_core.ACTIONS and owner else []
    return {"level": level, "digest_pending": counts["pending"],
            "drafts_pending": drafts, "actions_running": len(actions)}


def set_proactivity(level: str) -> dict:
    level = (level or "normal").strip().lower()
    if level not in ("quiet", "normal", "chatty"):
        return {"ok": False, "error": "Level must be quiet, normal or chatty."}
    try:
        mav_core.pg_exec(
            "insert into preferences (chat_id, key, value, ts) values (%s, 'notify.proactivity', %s, %s) "
            "on conflict (chat_id, key) do update set value = excluded.value, ts = excluded.ts",
            (mav_core.uid(), level, int(time.time())),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "level": level}


def snooze_job(name: str, until: int) -> bool:
    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    found = False
    for j in jobs:
        if j.get("name") == name and _mine(j):
            if until > 0:
                j["snooze_until"] = until
            else:
                j.pop("snooze_until", None)
            found = True
    if found:
        mav_core.write_json(mav_core.JOBS_FILE, jobs)
    return found


_running_jobs: set = set()


# Each routine posts into its own dashboard chat, which the user can open and
# continue. The worker (scheduled runs) finds it by the same title.
ROUTINE_PREFIX = "Routine · "


def routine_session(name: str, agent: str = "") -> str:
    title = mav_chat.PREFIX + ROUTINE_PREFIX + name
    for s_ in mav_chat._list_raw_sessions():
        if s_.get("title") == title:
            return s_["id"]
    sid = mav_chat.create_session(ROUTINE_PREFIX + name, agent)["id"]
    mav_chat.set_session_meta(sid, title_locked=True, titled=True, routine=name)
    return sid


def run_job_now(name: str) -> dict:
    """Run a routine now, in the background, exactly like a scheduled run:
    in the routine's chat, with memory, then a push + an inbox entry.

    It runs as a live answer (the run registry), so opening the routine's chat
    shows it being written instead of an empty chat."""
    job = next((j for j in my_jobs() if j.get("name") == name), None)
    if not job:
        return {"ok": False, "error": "Unknown routine."}
    if name in _running_jobs:
        return {"ok": False, "error": "Already running."}
    agent = job.get("agent", "") or mav_core.DEFAULT_AGENT
    sid = routine_session(name, agent)
    briefing = mav_core.ocbriefing is not None and mav_core.ocbriefing.is_briefing(job)
    context = briefing_context() if briefing else ""
    run = mav_stream.start_run(job.get("prompt", ""), sid, agent, raw_session=True,
                    with_memory=True, context=context)

    def work():
        _running_jobs.add(name)
        try:
            if run._thread:
                run._thread.join(timeout=1000)
            text = run.text
            summary = " ".join(re.sub(r"[*_`#>|]+", "", text or "").split())
            if len(summary) > 220:
                summary = summary[:217] + "…"
            if summary and run.status == "done":
                link = f"./#chat/{sid}"
                title = "☀️ Your briefing" if briefing else f"🔁 {name}"
                mav_store.record_notification("briefing" if briefing else "routine", title, summary, link)
                mav_media.send_push(title, summary, link)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _running_jobs.discard(name)

    mav_core.spawn(work)
    return {"ok": True, "session": sid}


def briefing_context() -> str:
    """Everything the briefing should know, as hidden context."""
    if mav_core.ocbriefing is None:
        return ""
    facts, notes, drafts, interests = [], [], 0, []
    if mav_core.MEMORY and mav_core.MEMORY_ENABLED:
        try:
            facts = mav_core.MEMORY.facts(mav_core.uid(), limit=30)
        except Exception:  # noqa: BLE001
            facts = []
    try:
        notes = mav_store.get_notifications(40).get("notifications") or []
    except Exception:  # noqa: BLE001
        notes = []
    if not mav_core.is_owner():
        # Drafts, interests and the calendars are the owner's.
        return mav_core.ocbriefing.build_context(facts=facts, notifications=notes, drafts=0, interests=[])
    try:
        rows = mav_core.pg_query("select count(*) as n from drafts where status = 'pending'")
        drafts = int(rows[0]["n"]) if rows else 0
    except Exception:  # noqa: BLE001
        drafts = 0
    if mav_core.INTERESTS is not None:
        try:
            interests = mav_core.INTERESTS.list(include_muted=False)
        except Exception:  # noqa: BLE001
            interests = []
    events = None
    if mav_core.occalendar is not None and mav_core.occalendar.load():
        try:
            events = mav_core.occalendar.briefing_lines(mav_core.occalendar.today())
        except Exception:  # noqa: BLE001
            events = None
    return mav_core.ocbriefing.build_context(
        facts=facts, notifications=notes, drafts=drafts, interests=interests, events=events,
    )


def briefing_job() -> dict | None:
    return next((j for j in my_jobs() if j.get("kind") == "briefing"), None)


def _briefing_job_new(time_hm: str = "") -> dict:
    """A new briefing routine for the current user (names are unique)."""
    job = mav_core.ocbriefing.default_job(time_hm or mav_core.ocbriefing.DEFAULT_TIME, mav_core.DEFAULT_AGENT)
    if not mav_core.is_owner():
        who = (mav_core.AUTH.account(mav_core.uid()) or {}).get("name") or str(mav_core.uid())
        job["name"] = f"{job['name']} ({who})"
        job["owner"] = mav_core.uid()
    return job


# A 3-step welcome on the first visit: connect a model, a few facts about
# you, a couple of routines — then a first briefing. Existing installs (with
# routines or memory already) are never asked.
ONBOARDING_FILE = mav_core.BOT_DIR / "onboarding.json"


LANGUAGES = {"en": "English", "fr": "French", "es": "Spanish", "de": "German",
             "it": "Italian", "pt": "Portuguese", "nl": "Dutch"}


def _has_history() -> bool:
    if any(j.get("kind") != "briefing" for j in my_jobs()):
        return True
    who, args = mav_core.mine()
    try:
        return mav_core.pg_query(f"select count(*) c from facts where {who}", args)[0]["c"] > 0
    except Exception:
        return False


def _onboarding_state() -> dict:
    """The welcome flow's state: the owner's at the top, members' by id."""
    data = mav_core.read_json(ONBOARDING_FILE, {})
    data = data if isinstance(data, dict) else {}
    if mav_core.is_owner():
        return data
    mine = (data.get("members") or {}).get(str(mav_core.uid()))
    return mine if isinstance(mine, dict) else {}


def get_onboarding() -> dict:
    done = _onboarding_state().get("done")
    if done is None:
        done = _has_history()
    return {"done": bool(done), "languages": LANGUAGES, "briefing": get_briefing()}


def set_onboarding(done: bool) -> dict:
    entry = {"done": bool(done), "ts": int(time.time())}
    data = mav_core.read_json(ONBOARDING_FILE, {})
    data = data if isinstance(data, dict) else {}
    if mav_core.is_owner():
        data.update(entry)
    else:
        members = data.get("members") if isinstance(data.get("members"), dict) else {}
        members[str(mav_core.uid())] = entry
        data["members"] = members
    mav_core.write_json(ONBOARDING_FILE, data)
    mav_core._chown_user(ONBOARDING_FILE)
    return {"ok": True, "done": bool(done)}


def onboarding_profile(payload: dict) -> dict:
    """Turn the "About you" step into memory facts and interests."""
    name = str(payload.get("name") or "").strip()[:60]
    city = str(payload.get("city") or "").strip()[:80]
    lang = str(payload.get("language") or "").strip().lower()
    raw = payload.get("interests") or []
    if isinstance(raw, str):
        raw = re.split(r"[,;\n]+", raw)
    interests = [str(i).strip()[:60] for i in raw if str(i).strip()][:12]
    facts = []
    if name:
        facts.append(f"Their name is {name}.")
    if city:
        facts.append(f"Lives in {city} (use it for the weather and local suggestions).")
    if lang in LANGUAGES:
        facts.append(f"Prefers answers in {LANGUAGES[lang]}.")
    saved = 0
    for f in facts:
        try:
            if mav_store.memory_action("fact/add", {"fact": f}).get("ok"):
                saved += 1
        except Exception:
            pass
    added = 0
    for label in interests if mav_core.is_owner() else []:  # the interest profile is the owner's
        try:
            if mav_store.add_interest({"label": label}).get("ok"):
                added += 1
        except Exception:
            pass
    return {"ok": True, "facts": saved, "interests": added}


def _job_name(label: str) -> str:
    """A routine name the scheduler accepts, from any template label."""
    ascii_ = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9 _.-]", "", ascii_).strip()[:61] or "Routine"
    return name if name[0].isalnum() else "Routine " + name


def onboarding_routines(payload: dict) -> dict:
    """Create the routines picked in the welcome flow (skipping duplicates)."""
    ids = [str(i) for i in (payload.get("templates") or []) if str(i)][:8]
    existing = {j.get("name") for j in mav_core.read_json(mav_core.JOBS_FILE, []) if isinstance(j, dict)}
    taken = existing - {j.get("name") for j in my_jobs()}
    created, errors = [], []
    for tid in ids:
        res = template_to_job(tid, lang=str(payload.get("language") or "en"))
        if not res.get("ok"):
            errors.append(res.get("error") or tid)
            continue
        job = res["job"]
        job["name"] = _job_name(job["name"])
        if job["name"] in taken:  # another person's routine: keep theirs, name this one apart
            who = (mav_core.AUTH.account(mav_core.uid()) or {}).get("name") or str(mav_core.uid())
            job["name"] = _job_name(f"{job['name']} {who}")
        if job["name"] in existing:
            continue
        saved = save_job(job)
        if saved.get("ok"):
            created.append(job["name"])
            existing.add(job["name"])
        else:
            errors.append(saved.get("error") or tid)
    brief = payload.get("briefing")
    briefing = None
    if isinstance(brief, dict):
        briefing = set_briefing(bool(brief.get("enabled")), str(brief.get("time") or ""))
    return {"ok": not errors, "created": created, "errors": errors, "briefing": briefing}


def get_briefing() -> dict:
    job = briefing_job()
    return {
        "available": mav_core.ocbriefing is not None,
        "exists": bool(job),
        "enabled": bool(job and job.get("enabled", True)),
        "time": (job or {}).get("time") or (mav_core.ocbriefing.DEFAULT_TIME if mav_core.ocbriefing else "07:30"),
        "name": (job or {}).get("name") or (mav_core.ocbriefing.NAME if mav_core.ocbriefing else "Daily briefing"),
    }


def set_briefing(enabled: bool, time_hm: str = "") -> dict:
    """Turn the daily briefing on/off and set its time (a regular routine)."""
    if mav_core.ocbriefing is None:
        return {"ok": False, "error": "Briefing unavailable."}
    if time_hm and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", time_hm):
        return {"ok": False, "error": "Pick a time like 07:30."}
    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    if not isinstance(jobs, list):
        jobs = []
    job = next((j for j in jobs if _mine(j) and j.get("kind") == "briefing"), None)
    if job is None:
        if not enabled:
            return {"ok": True, **get_briefing()}
        job = _briefing_job_new(time_hm)
        jobs.append(job)
    job["enabled"] = bool(enabled)
    if time_hm:
        job["time"] = time_hm
    mav_core.write_json(mav_core.JOBS_FILE, jobs)
    mav_core._chown_user(mav_core.JOBS_FILE)
    return {"ok": True, **get_briefing()}


def run_briefing_now() -> dict:
    """"Brief me now": runs the briefing routine (created switched off if the
    daily schedule was never turned on, so it has its own chat)."""
    if mav_core.ocbriefing is None:
        return {"ok": False, "error": "Briefing unavailable."}
    job = briefing_job()
    if job is None:
        job = _briefing_job_new()
        job["enabled"] = False
        jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
        jobs = jobs if isinstance(jobs, list) else []
        jobs.append(job)
        mav_core.write_json(mav_core.JOBS_FILE, jobs)
        mav_core._chown_user(mav_core.JOBS_FILE)
    return run_job_now(job["name"])


ACTION_PREFIX = "Action · "


def start_action(prompt: str, name: str = "", agent: str = "") -> dict:
    """Run a long task in the background and deliver its result later.

    Unlike a routine, an action is a one-off: it gets its own chat, is tracked
    in the `actions` table while it runs, and pushes the answer when done.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "Give the action something to do."}
    title = (name or prompt)[:60].strip() or "Action"
    agent = agent or mav_core.DEFAULT_AGENT
    sid = mav_chat.create_session(ACTION_PREFIX + title, agent)["id"]
    mav_chat.set_session_meta(sid, title_locked=True, titled=True, action=title)
    aid = mav_core.ACTIONS.add(mav_core.DEFAULT_CHAT_ID, title, "task", f"./#chat/{sid}") if mav_core.ACTIONS else None

    def work():
        if mav_core.ACTIONS and aid:
            mav_core.ACTIONS.update(aid, "running")
        try:
            text = mav_stream.ask(prompt, agent, sid, raw_session=True, with_memory=True)
            failed = not text or text.startswith("Error:")
            if mav_core.ACTIONS and aid:
                mav_core.ACTIONS.update(aid, "failed" if failed else "done", result=text or "")
            if not failed:
                summary = " ".join(re.sub(r"[*_`#>|]+", "", text).split())
                if len(summary) > 220:
                    summary = summary[:217] + "…"
                mav_store.record_notification("action", f"✅ {title}", summary, f"./#chat/{sid}")
                mav_media.send_push(f"✅ {title}", summary, f"./#chat/{sid}")
        except Exception as exc:  # noqa: BLE001
            if mav_core.ACTIONS and aid:
                mav_core.ACTIONS.update(aid, "failed", result=str(exc)[:500])

    mav_core.spawn(work)
    return {"ok": True, "id": aid, "session": sid}


def set_job_enabled(name: str, enabled: bool) -> bool:
    jobs = mav_core.read_json(mav_core.JOBS_FILE, [])
    found = False
    for j in jobs:
        if j.get("name") == name and _mine(j):
            j["enabled"] = bool(enabled)
            found = True
    if found:
        mav_core.write_json(mav_core.JOBS_FILE, jobs)
    return found


def get_job_results(limit: int = 8) -> dict:
    """Latest report of each routine (the last answer in its chat)."""
    head = mav_chat.PREFIX + ROUTINE_PREFIX
    mine = {j.get("name") for j in my_jobs()}
    chats = []
    for s_ in mav_chat._list_raw_sessions():
        title = str(s_.get("title", ""))
        if title.startswith(head) and title[len(head):] in mine:
            t = s_.get("time", {})
            chats.append({"id": s_["id"], "name": title[len(head):], "updated": t.get("updated") or t.get("created") or 0})
    chats.sort(key=lambda x: x["updated"], reverse=True)
    out = []
    for c in chats[:limit]:
        text = next((m["text"] for m in reversed(mav_chat.session_messages(c["id"])) if m["role"] == "mav"), "")
        if text:
            out.append({"name": c["name"], "updated": c["updated"], "text": text[:4000], "session": c["id"]})
    return {"results": out}


def get_watch() -> dict:
    who, args = mav_core.mine()
    try:
        items = mav_core.pg_query(
            f"select id, kind, target, last_state, last_checked, enabled from watch_items where {who} order by id desc",
            args,
        )
    except Exception:
        items = []
    return {"items": items}


def get_events(limit: int = 30) -> dict:
    try:
        from ocevents import recent  # noqa: PLC0415

        return {"events": recent(limit)}
    except Exception:  # noqa: BLE001
        return {"events": []}


def hook_event(kind: str, payload: dict, token: str = "") -> dict:
    """Record an incoming event and (best-effort) kick the worker."""
    try:
        from ocevents import ensure_schema, push  # noqa: PLC0415

        ensure_schema()
        # Optional shared-secret guard, configured in Settings → Proactivity.
        want = ""
        try:
            rows = mav_core.pg_query("select value from preferences where key = 'hooks.token' limit 1")
            want = (rows[0].get("value") or "") if rows else ""
        except Exception:  # noqa: BLE001
            want = ""
        if want and token != want:
            return {"ok": False, "error": "bad token"}
        eid = push(kind, payload)
        return {"ok": eid is not None, "id": eid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


VALID_WATCH_KINDS = ["web", "price", "news", "rss", "github"]


def watch_target(kind: str, target: str) -> str | None:
    """Normalise what the form sent, or None when it can't be watched.

    News, feeds and releases keep an optional condition after "|" (words the
    item must mention); a price keeps its "|below" target.
    """
    base, sep, extra = str(target or "").strip().partition("|")
    base = base.strip()
    if not base:
        return None
    if kind in ("web", "price", "rss"):
        u = urllib.parse.urlparse(base)
        if u.scheme not in ("http", "https") or not u.netloc:
            return None
    if kind == "github":
        from ocwatch import github_repo  # noqa: PLC0415

        base = github_repo(base)
        if not base:
            return None
    extra = re.sub(r"\s+", " ", extra).strip()[:120]
    return (f"{base}|{extra}" if sep and extra else base)[:500]


def watch_add(kind: str, target: str) -> bool:
    if kind not in VALID_WATCH_KINDS:
        return False
    target = watch_target(kind, target)
    if not target:
        return False
    mav_core.pg_exec(
        "insert into watch_items (chat_id, kind, target, ts) values (%s, %s, %s, %s)",
        (mav_core.uid(), kind, target, int(time.time())),
    )
    return True


def watch_remove(item_id: int) -> bool:
    who, args = mav_core.mine()
    mav_core.pg_exec(f"delete from watch_items where id = %s and {who}", (item_id, *args))
    return True


__all__ = ['_briefing_job_new', '_mine', '_onboarding_state', 'job_owner', 'my_jobs', 'ACTION_PREFIX', 'JOB_DAYS', 'JOB_NAME_RE', 'LANGUAGES', 'ONBOARDING_FILE', 'ROUTINE_PREFIX', 'VALID_WATCH_KINDS', '_condition_from_payload', '_has_history', '_job_name', '_running_jobs', '_schedule_from_payload', 'briefing_context', 'briefing_job', 'delete_job', 'detect_routine', 'get_briefing', 'get_events', 'get_job_results', 'get_jobs', 'get_onboarding', 'get_proactivity', 'get_watch', 'hook_event', 'job_templates', 'onboarding_profile', 'onboarding_routines', 'routine_session', 'run_briefing_now', 'run_job_now', 'save_job', 'set_briefing', 'set_job_enabled', 'set_onboarding', 'set_proactivity', 'snooze_job', 'start_action', 'template_to_job', 'watch_add', 'watch_remove', 'watch_target']
