#!/usr/bin/env python3
"""Case Review: a local GUI for our Track 2 system.

    py -3 -X utf8 demo/app.py data/dev            # then open http://127.0.0.1:8765
    py -3 -X utf8 demo/app.py data/dev --port 9000

Runs the real engine (system/engine) on the data folder once at start-up, then serves a
single-page app that shows the alert queue and, for every hit, the "court" view:
  prosecution = what says the hit IS the customer (name, date of birth, country agreement)
  defence     = the SOP contradictions that say it is NOT (type, death, age, DOB, verified name, location)
  judge       = the decision our system actually wrote, its reason, and the cited records
Every cited ID opens the underlying record.

Safety: binds to 127.0.0.1 only and reads the data folder you give it, nothing leaves the
machine. The data is for event participants only: never deploy or publish this page with data.
Standard library only. Not part of system/ and never imported by it.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "system"))

from engine import countries, dates, explain, hitfacts, judge, load, names, resolve  # noqa: E402
from engine.model import BirthClaim, Fact, PartialDate  # noqa: E402

COST = {("DIFFERENT_ENTITY", "DIFFERENT_ENTITY"): 0, ("DIFFERENT_ENTITY", "SAME_ENTITY"): 3,
        ("DIFFERENT_ENTITY", "REVIEW"): 3, ("SAME_ENTITY", "DIFFERENT_ENTITY"): 60,
        ("SAME_ENTITY", "SAME_ENTITY"): 0, ("SAME_ENTITY", "REVIEW"): 2,
        ("REVIEW", "DIFFERENT_ENTITY"): 60, ("REVIEW", "SAME_ENTITY"): 2, ("REVIEW", "REVIEW"): 0}


# --------------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------------

class State:
    def __init__(self, folder: str):
        self.folder = folder
        self.lock = threading.Lock()
        self.ready = False
        self.status = "starting"
        self.data = None
        self.decisions = {}      # hit_id -> Decision
        self.resolutions = {}    # alert_id -> Resolution
        self.labels = {}         # hit_id -> practice label row
        self.records = {}        # any record ID -> (kind, row)
        self.run_seconds = 0.0

    def build(self):
        t = time.time()
        self.status = "loading data"
        data = load.load(self.folder)
        if hasattr(names, "use_variants") and getattr(data, "name_variants", None):
            names.use_variants(data.name_variants)
        self.status = "indexing records"
        rec = {}
        for rid, r in data.customers.items():
            rec[rid] = ("customer", r)
        for rows in data.accounts_by_id.values():
            for r in rows:
                rec.setdefault(str(r.get("account_id")), ("account", r))
        for rows in data.kyc_by_applicant.values():
            for r in rows:
                rec[str(r.get("check_id"))] = ("kyc_check", r)
        for rows in data.notes_by_email.values():
            for r in rows:
                rec[str(r.get("note_id"))] = ("note", r)
        for rows in data.search_by_query.values():
            for r in rows:
                rec[str(r.get("result_id"))] = ("search_result", r)
        for hid, r in data.hits.items():
            rec[hid] = ("hit", r)
        for aid, r in data.alerts.items():
            rec[aid] = ("alert", r)
        labels = {}
        lp = os.path.join(self.folder, "practice_labels.jsonl")
        if os.path.exists(lp):
            with open(lp, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        labels[row["hit_id"]] = row
        self.status = "running the engine on every hit"
        decisions, resolutions = {}, {}
        for hid in sorted(data.hits, key=lambda h: (str(data.hits[h].get("alert_id")), h)):
            hit = data.hits[hid]
            aid = str(hit.get("alert_id") or "")
            alert = data.alerts.get(aid, {"alert_id": aid})
            if aid not in resolutions:
                resolutions[aid] = resolve.resolve(alert, data)
            prof = hitfacts.extract(hit, data)
            d = judge.decide(prof, resolutions[aid], alert)
            d.hit_id, d.alert_id = hid, aid
            decisions[hid] = d
        with self.lock:
            self.data, self.records, self.labels = data, rec, labels
            self.decisions, self.resolutions = decisions, resolutions
            self.run_seconds = time.time() - t
            self.ready = True
            self.status = "ready"


# --------------------------------------------------------------------------------------------
# Serialising engine objects
# --------------------------------------------------------------------------------------------

def show(v):
    if isinstance(v, PartialDate):
        return explain.fmt_date(v)
    if isinstance(v, BirthClaim):
        return explain.fmt_claim(v)
    if isinstance(v, Fact):
        return {"value": show(v.value), "source": v.source, "kind": v.kind}
    if is_dataclass(v):
        return {k: show(getattr(v, k)) for k in asdict(v)}
    if isinstance(v, (list, tuple)):
        return [show(x) for x in v]
    if isinstance(v, dict):
        return {str(k): show(x) for k, x in v.items()}
    return v


def _is_company(t) -> bool:
    return str(t or "").strip().lower().startswith("comp")


def court(hit_prof, person, alert) -> dict:
    """Recompute, for display only, what agrees and what contradicts. The ruling is the engine's."""
    company = _is_company(hit_prof.entity_type)
    cnames = [person.verified_name] if person.verified_name else list(person.names)
    cdobs = [person.verified_dob] if person.verified_dob else list(person.dobs)
    cdobs = [f for f in cdobs if isinstance(f.value, PartialDate) and f.value.year]
    births = list(hit_prof.births)
    if not births and company and hit_prof.incorporated is not None and isinstance(hit_prof.incorporated.value, PartialDate):
        v = hit_prof.incorporated.value
        births = [BirthClaim(years=(v.year,), month=v.month, day=v.day, source=hit_prof.incorporated.source)]

    pros, dfn = [], []
    name_pair = next(((c, h) for c in cnames for h in hit_prof.names
                      if names.names_agree(str(c.value), str(h.value), company)), None)
    if name_pair:
        pros.append({"what": "Name agrees", "detail": "%s (%s) ~ %s" % (name_pair[0].value, name_pair[0].kind or "name", name_pair[1].value),
                     "sources": [name_pair[0].source, name_pair[1].source]})
    dob_pair = next(((c, b) for c in cdobs for b in births if dates.birth_agrees(c.value, b)), None)
    if dob_pair:
        pros.append({"what": "Date of birth agrees", "detail": "%s ~ hit %s" % (explain.fmt_date(dob_pair[0].value), explain.fmt_claim(dob_pair[1])),
                     "sources": [dob_pair[0].source, dob_pair[1].source]})
    cc = {str(f.value).lower(): f for f in person.countries}
    hc = {str(f.value).lower(): f for f in hit_prof.countries}
    shared = sorted(set(cc) & set(hc))
    if shared:
        pros.append({"what": "Country shared", "detail": ", ".join(cc[k].value for k in shared),
                     "sources": sorted({cc[k].source for k in shared} | {hc[k].source for k in shared})})

    # defence: every SOP contradiction, with whether it holds
    ht, pt = str(hit_prof.entity_type or "").lower()[:4], str(person.entity_type or "").lower()[:4]
    dfn.append({"rule": "Entity type", "holds": bool(ht and pt and ht != pt),
                "detail": "hit %s, customer %s" % (hit_prof.entity_type or "?", person.entity_type or "?")})
    screened = dates.parse(str(alert.get("screened_at") or "")[:10]) if alert.get("screened_at") else None
    dec = hit_prof.deceased.value if hit_prof.deceased is not None else None
    dfn.append({"rule": "Died before screening", "holds": bool(dec is not None and screened is not None and dates.before(dec, screened) is True),
                "detail": "death %s, screened %s" % (explain.fmt_date(dec) if dec else "unknown", explain.fmt_date(screened) if screened else "?")})
    rep = hit_prof.earliest_report.value if hit_prof.earliest_report is not None else None
    young = bool(rep is not None and cdobs and all(
        (dates.before(rep, f.value) is True) if company else dates.younger_than(f.value, rep, 16) for f in cdobs))
    dfn.append({"rule": "Too young / not yet incorporated", "holds": young,
                "detail": "earliest dated report %s" % (explain.fmt_date(rep) if rep else "none")})
    dob_x = bool(births and cdobs and not dob_pair and all(dates.birth_contradicted(c.value, b) for c in cdobs for b in births))
    dfn.append({"rule": "Every hit birth date contradicted", "holds": dob_x,
                "detail": "customer %s vs hit %s" % (", ".join(explain.fmt_date(c.value) for c in cdobs) or "unknown",
                                                    ", ".join(explain.fmt_claim(b) for b in births) or "unknown")})
    vn = person.verified_name
    vn_x = bool(vn is not None and hit_prof.names and names.real_part_count(str(vn.value), company) >= 2
                and not any(names.names_agree(str(vn.value), str(h.value), company) for h in hit_prof.names
                            if names.real_part_count(str(h.value), company) > 0))
    dfn.append({"rule": "Verified name matches none of the hit's names", "holds": vn_x,
                "detail": "verified %s" % (vn.value if vn else "none on file")})
    loc_x = bool(cc and hc and not shared)
    dfn.append({"rule": "Every country differs", "holds": loc_x,
                "detail": "customer %s vs hit %s" % (", ".join(sorted(f.value for f in cc.values())) or "none",
                                                    ", ".join(sorted(f.value for f in hc.values())) or "none"),
                "note": "blocked: name and date of birth agree" if (loc_x and name_pair and dob_pair) else ""})
    return {"person_id": person.person_id, "prosecution": pros, "defence": dfn}


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------

STATE: State = None  # type: ignore


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/api/status":
            return self._send(200, {"ready": STATE.ready, "status": STATE.status})
        if not STATE.ready:
            return self._send(503, {"error": STATE.status})
        if u.path == "/api/summary":
            return self._send(200, summary())
        if u.path == "/api/hits":
            return self._send(200, hit_list(q))
        if u.path.startswith("/api/hit/"):
            return self._send(*hit_detail(u.path.rsplit("/", 1)[-1]))
        if u.path.startswith("/api/record/"):
            rid = u.path.rsplit("/", 1)[-1]
            r = STATE.records.get(rid)
            return self._send(200, {"id": rid, "kind": r[0], "row": r[1]}) if r else self._send(404, {"error": "unknown id " + rid})
        return self._send(404, {"error": "not found"})


def summary():
    ds = list(STATE.decisions.values())
    by = {}
    for d in ds:
        by.setdefault(d.decision, {}).setdefault(d.reason_code, 0)
        by[d.decision][d.reason_code] += 1
    cost = base = right = unsafe = 0
    for hid, lab in STATE.labels.items():
        d = STATE.decisions.get(hid)
        if not d:
            continue
        cost += COST[(lab["decision"], d.decision)]
        base += COST[(lab["decision"], "REVIEW")]
        right += lab["decision"] == d.decision
        unsafe += d.decision == "DIFFERENT_ENTITY" and lab["decision"] != "DIFFERENT_ENTITY"
    return {"hits": len(ds), "alerts": len(STATE.resolutions), "by_decision": by,
            "seconds": round(STATE.run_seconds, 1), "folder": os.path.basename(STATE.folder.rstrip("/\\")),
            "practice": {"n": len(STATE.labels), "right": right, "unsafe": unsafe, "cost": cost, "baseline": base,
                         "score": round(100.0 * max(0.0, 1 - cost / base), 1) if base else None}}


def hit_list(q):
    out = []
    want_dec, want_code = q.get("decision"), q.get("reason")
    text = (q.get("q") or "").strip().lower()
    practice_only = q.get("practice") == "1"
    for hid, d in sorted(STATE.decisions.items(), key=lambda kv: (kv[1].alert_id, kv[0])):
        if want_dec and d.decision != want_dec:
            continue
        if want_code and d.reason_code != want_code:
            continue
        if practice_only and hid not in STATE.labels:
            continue
        hit = STATE.data.hits[hid]
        alert = STATE.data.alerts.get(d.alert_id, {})
        row = {"hit_id": hid, "alert_id": d.alert_id, "decision": d.decision, "reason_code": d.reason_code,
               "customer": d.customer_record_id, "hit_name": hit.get("name"), "screened": alert.get("customer_name"),
               "category": hit.get("primary_category") or hit.get("categories")}
        lab = STATE.labels.get(hid)
        if lab:
            row["truth"] = lab["decision"]
        if text and text not in json.dumps(row, ensure_ascii=False).lower():
            continue
        out.append(row)
    return {"rows": out[:2000], "total": len(out)}


def hit_detail(hid):
    d = STATE.decisions.get(hid)
    if not d:
        return 404, {"error": "unknown hit " + hid}
    data = STATE.data
    hit = data.hits[hid]
    alert = data.alerts.get(d.alert_id, {"alert_id": d.alert_id})
    res = STATE.resolutions.get(d.alert_id)
    prof = hitfacts.extract(hit, data)
    trials = [court(prof, p, alert) for p in (res.people if res else [])]
    lab = STATE.labels.get(hid)
    return 200, {
        "decision": show(d), "alert": alert, "hit_raw": {k: hit.get(k) for k in (
            "name", "aliases", "entity_type", "dobs", "countries", "nationality", "citizenship",
            "place_of_birth", "primary_category", "categories", "life_status", "deceased_date")},
        "profile": show(prof), "resolution": show(res) if res else None, "court": trials,
        "label": lab,
    }


def main(argv):
    global STATE
    if len(argv) < 2:
        raise SystemExit(__doc__)
    folder = os.path.abspath(argv[1])
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
    STATE = State(folder)
    threading.Thread(target=STATE.build, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Case Review on http://127.0.0.1:%d  (data: %s). Ctrl+C to stop." % (port, folder))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv)
