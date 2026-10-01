#!/usr/bin/env python3
"""Collects biotech/health data for a daily brief.

Open sources, no API key:
  - Yahoo Finance: health indices, big pharma and biotech quotes.
  - openFDA: recent approvals (original NDA/BLA).
  - ClinicalTrials.gov: recently updated trials.
  - FDA press RSS: press releases.

By default prints compact text a LLM can read (the job reads it and writes
the brief). Options: --json for the raw structured output.

Designed never to fail as a whole: each source is isolated, one
source en panne produit une ligne « indisponible » sans casser le reste.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
YF_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

# Health and biotech indices / ETFs.
ETFS = ["XBI", "IBB", "XLV", "IHI", "ARKG", "XPH"]
# Grands labos.
MAJORS = ["LLY", "NVO", "JNJ", "ABBV", "MRK", "PFE", "AMGN", "GILD",
          "BMY", "VRTX", "REGN", "MRNA", "BIIB", "AZN", "SNY", "GSK"]
# Biotechs innovantes (small/mid caps).
INNOVATORS = ["CRSP", "NTLA", "BEAM", "VRNA", "SRPT", "ALNY", "IONS",
              "BMRN", "EXAS", "NTRA", "ILMN", "RVTY", "TXG", "PACB"]


def http_json(url: str, timeout: float = 15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --------------------------------------------------------------- Yahoo
def yf_chart(symbol: str, range_: str = "5d") -> dict | None:
    path = f"/v8/finance/chart/{urllib.parse.quote(symbol)}?range={range_}&interval=1d"
    for host in YF_HOSTS:
        try:
            d = http_json(f"https://{host}{path}")
            res = (d.get("chart") or {}).get("result") or []
            if res:
                return res[0]
        except Exception:
            continue
    return None


def quote(symbol: str) -> dict | None:
    r = yf_chart(symbol, "5d")
    if not r:
        return None
    m = r.get("meta") or {}
    price = m.get("regularMarketPrice")
    prev = m.get("chartPreviousClose")
    closes = [
        c
        for c in ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        if c is not None
    ]
    pct = None
    if price is not None and prev:
        pct = (price - prev) / prev * 100.0
    pct5d = None
    if price is not None and len(closes) >= 2 and closes[0]:
        pct5d = (price - closes[0]) / closes[0] * 100.0
    return {
        "symbol": symbol,
        "name": m.get("shortName") or m.get("longName") or symbol,
        "price": price,
        "prevClose": prev,
        "pct": round(pct, 2) if pct is not None else None,
        "pct5d": round(pct5d, 2) if pct5d is not None else None,
        "preMarket": m.get("preMarketPrice"),
        "postMarket": m.get("postMarketPrice"),
        "currency": m.get("currency"),
    }


def quotes(symbols: list[str]) -> list[dict]:
    out = []
    for s in symbols:
        try:
            q = quote(s)
            if q:
                out.append(q)
        except Exception:
            continue
    return out


# --------------------------------------------------------------- openFDA
def recent_approvals(days: int = 45, limit: int = 12) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = (
        "submissions.submission_type:ORIG AND "
        f"submissions.submission_status_date:[{start} TO {end}]"
    )
    url = (
        "https://api.fda.gov/drug/drugsfda.json?"
        + urllib.parse.urlencode({"search": q, "limit": limit, "sort": "submissions.submission_status_date:desc"})
    )
    try:
        d = http_json(url, timeout=20)
    except Exception:
        return []
    out = []
    for r in d.get("results", [])[:limit]:
        prods = r.get("products") or [{}]
        subs = [
            s for s in (r.get("submissions") or [])
            if s.get("submission_type") == "ORIG"
            and (s.get("submission_status_date") or "") >= start.replace("-", "")
        ]
        subs.sort(key=lambda s: s.get("submission_status_date", ""), reverse=True)
        if not subs:
            continue
        out.append({
            "sponsor": r.get("sponsor_name"),
            "brand": prods[0].get("brand_name"),
            "generic": prods[0].get("generic_name"),
            "date": subs[0].get("submission_status_date"),
            "status": subs[0].get("submission_status"),
            "priority": subs[0].get("review_priority"),
        })
    # Dedup (several products of one file) and sort by date.
    seen = set()
    uniq = []
    for a in out:
        key = (a["sponsor"], a["brand"], a["date"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    uniq.sort(key=lambda a: a["date"] or "", reverse=True)
    return uniq


# --------------------------------------------------------------- ClinicalTrials
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"


def trial_updates(days: int = 10, limit: int = 12) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    advanced = (
        f"AREA[LastUpdatePostDate]RANGE[{start},MAX] AND "
        "AREA[LeadSponsorClass]INDUSTRY AND "
        "(AREA[Phase]PHASE1 OR AREA[Phase]PHASE2 OR AREA[Phase]PHASE3)"
    )
    params = {
        "filter.advanced": advanced,
        "pageSize": str(limit),
        "sort": "LastUpdatePostDate:desc",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,LeadSponsorName,LastUpdatePostDate,PrimaryCompletionDate",
    }
    url = CT_BASE + "?" + urllib.parse.urlencode(params)
    try:
        d = http_json(url, timeout=20)
    except Exception:
        return []
    out = []
    for st in d.get("studies", [])[:limit]:
        p = st.get("protocolSection") or {}
        idm = p.get("identificationModule") or {}
        stm = p.get("statusModule") or {}
        dim = p.get("designModule") or {}
        sp = p.get("sponsorCollaboratorsModule") or {}
        phases = dim.get("phases") or []
        out.append({
            "nct": idm.get("nctId"),
            "title": idm.get("briefTitle"),
            "status": stm.get("overallStatus"),
            "phase": ",".join(phases) if phases else None,
            "sponsor": ((sp.get("leadSponsor") or {}).get("name")),
            "updated": stm.get("lastUpdatePostDateStruct", {}).get("date") if isinstance(stm.get("lastUpdatePostDateStruct"), dict) else stm.get("lastUpdatePostDate"),
            "completion": (stm.get("primaryCompletionDateStruct") or {}).get("date") if isinstance(stm.get("primaryCompletionDateStruct"), dict) else None,
        })
    return out


# --------------------------------------------------------------- rappels FDA
def recalls(days: int = 30, limit: int = 10) -> list[dict]:
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
    end = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = (
        "https://api.fda.gov/drug/enforcement.json?"
        + urllib.parse.urlencode({
            "search": f"report_date:[{start} TO {end}]",
            "limit": limit,
            "sort": "report_date:desc",
        })
    )
    try:
        d = http_json(url, timeout=20)
    except Exception:
        return []
    out = []
    for r in d.get("results", [])[:limit]:
        out.append({
            "date": r.get("report_date"),
            "firm": r.get("recalling_firm"),
            "product": (r.get("product_description") or "")[:120],
            "reason": (r.get("reason_for_recall") or "")[:160],
            "class": r.get("classification"),
        })
    return out


# --------------------------------------------------------------- rapport
def build() -> dict:
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "etfs": quotes(ETFS),
        "majors": quotes(MAJORS),
        "innovators": quotes(INNOVATORS),
        "approvals": recent_approvals(),
        "trials": trial_updates(),
        "recalls": recalls(),
    }


def fmt_pct(p) -> str:
    if p is None:
        return "n/a"
    return f"{p:+.2f}%"


def to_text(d: dict) -> str:
    L = []
    L.append("=== BIOTECH / HEALTH — collected data ===")
    L.append(f"(generated {d['generated']} UTC)")

    for label, key in (("INDICES & ETF SANTÉ", "etfs"),
                       ("GRANDS LABOS", "majors"),
                       ("BIOTECHS INNOVANTES", "innovators")):
        L.append("")
        L.append(f"[{label}]")
        rows = d.get(key) or []
        if not rows:
            L.append("  (indisponible)")
            continue
        for q in rows:
            L.append(
                f"  {q['symbol']:<6} {q.get('name','')[:34]:<34} "
                f"{q.get('price')} {q.get('currency','')} "
                f"jour {fmt_pct(q.get('pct'))}  5j {fmt_pct(q.get('pct5d'))}"
            )

    L.append("")
    L.append("[APPROBATIONS FDA RÉCENTES (NDA/BLA originaux)]")
    ap = d.get("approvals") or []
    if not ap:
        L.append("  (aucune ou indisponible)")
    for a in ap:
        L.append(f"  {a.get('date')} | {a.get('sponsor')} | {a.get('brand')} "
                 f"({a.get('generic')}) | {a.get('status')} | {a.get('priority')}")

    L.append("")
    L.append("[ESSAIS CLINIQUES RÉCEMMENT MIS À JOUR]")
    tr = d.get("trials") or []
    if not tr:
        L.append("  (indisponible)")
    for t in tr:
        L.append(f"  {t.get('nct')} | {t.get('phase')} | {t.get('status')} | "
                 f"{t.get('sponsor')} | {t.get('title','')[:90]} | maj {t.get('updated')}")

    L.append("")
    L.append("[RAPPELS FDA RÉCENTS]")
    rc = d.get("recalls") or []
    if not rc:
        L.append("  (aucun ou indisponible)")
    for r in rc:
        L.append(f"  {r.get('date')} | {r.get('firm')} | {r.get('class')} | "
                 f"{r.get('product','')[:70]} | {r.get('reason','')[:80]}")

    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Biotech data collection.")
    ap.add_argument("--json", action="store_true", help="sortie JSON brute")
    args = ap.parse_args()
    data = build()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print(to_text(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
