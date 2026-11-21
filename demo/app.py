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
try:  # optional: the Grok cross-examiner (system/engine/crossexam.py), off without a key
    from engine import crossexam, llm  # noqa: E402
except Exception:  # pragma: no cover
    crossexam = llm = None
sys.path.insert(0, HERE)
import review_api  # noqa: E402
try:  # optional: the LLM court (prosecution / defence / adjudicator), called only on a reviewer's request
    import court_llm  # noqa: E402
except Exception:
    court_llm = None
STORE = None
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
        decisions, resolutions, items = {}, {}, []
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
            items.append((d, prof, resolutions[aid], alert))
        # same cross-examination as system/run, so the GUI shows exactly what the output file holds
        rules_decisions = {}
        if crossexam is not None and llm is not None and llm.available():
            self.status = "Grok is cross-examining the clearances"
            try:
                new = crossexam.review_all(items, data)
            except Exception:
                new = {}
            for hid, nd in new.items():
                old = decisions.get(hid)
                if old is not None and old.decision == "DIFFERENT_ENTITY" and nd.decision == "REVIEW":
                    rules_decisions[hid] = old
                    decisions[hid] = nd
        with self.lock:
            self.data, self.records, self.labels = data, rec, labels
            self.decisions, self.resolutions = decisions, resolutions
            self.rules_decisions = rules_decisions
            self.llm = llm.describe() if llm is not None else "rules only"
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
    if hasattr(judge, "name_match"):  # the judge's own SOP check, so the GUI can never disagree with the ruling
        cf, hf = judge.name_match(hit_prof, person)
        name_pair = (cf, hf) if cf is not None and hf is not None else None
    else:
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

    def _static(self, path):
        """The built React app (demo/ui/dist) if present, else the older single-file page."""
        dist = os.path.join(HERE, "ui", "dist")
        if not os.path.isdir(dist):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(dist, rel))
        if not full.startswith(os.path.normpath(dist)) or not os.path.isfile(full):
            full = os.path.join(dist, "index.html")  # client-side routes
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".woff2": "font/woff2", ".json": "application/json"}.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def _authorised(self):
        """Optional passcode for a hosted demo (TRYLL_DEMO_PASSCODE): the browser's own sign-in prompt."""
        code = os.environ.get("TRYLL_DEMO_PASSCODE", "")
        if not code:
            return True
        import base64, hmac
        got = self.headers.get("Authorization", "")
        if got.startswith("Basic "):
            try:
                pw = base64.b64decode(got[6:]).decode("utf-8", "replace").split(":", 1)[-1]
                if hmac.compare_digest(pw, code):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Tryll demo"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_POST(self):
        if not self._authorised():
            return
        u = urlparse(self.path)
        if not STATE.ready:
            return self._send(503, {"error": STATE.status})
        try:
            body = self._body()
        except Exception:
            return self._send(400, {"error": "body must be JSON"})
        if u.path == "/api/review":
            return self._send(*post_review(body))
        if u.path == "/api/court":
            return self._send(*post_court(body))
        return self._send(404, {"error": "not found"})

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._send(200, {"ok": True})
        if not self._authorised():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not u.path.startswith("/api/"):
            return self._static(u.path)
        if u.path == "/api/status":
            return self._send(200, {"ready": STATE.ready, "status": STATE.status})
        if not STATE.ready:
            return self._send(503, {"error": STATE.status})
        if u.path == "/api/cases":
            return self._send(200, review_api.case_rows(STATE, STORE, q))
        if u.path.startswith("/api/case/"):
            return self._send(*case_detail(u.path.rsplit("/", 1)[-1]))
        if u.path.startswith("/api/reviews/"):
            return self._send(200, {"history": STORE.history(u.path.rsplit("/", 1)[-1])})
        if u.path == "/api/reviewed_decisions.jsonl":
            return self._send(200, review_api.export_lines(STATE, STORE).encode("utf-8"), "application/x-ndjson; charset=utf-8")
        if u.path == "/api/mi":
            return self._send(200, review_api.mi(STATE, STORE))
        if u.path.startswith("/api/report/"):
            hid = u.path.rsplit("/", 1)[-1].replace(".md", "")
            code, det = case_detail(hid)
            if code != 200:
                return self._send(code, det)
            return self._send(200, review_api.case_report(STATE, STORE, hid, det).encode("utf-8"), "text/markdown; charset=utf-8")
        if u.path == "/api/codes":
            return self._send(200, {k: list(v) for k, v in review_api.CODES.items()})
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
            "llm": getattr(STATE, "llm", "rules only"),
            "blindfold": bool(getattr(STATE, "blindfold", False)),
            "crossexam_downgrades": len(getattr(STATE, "rules_decisions", {})),
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
        "crossexam": {
            "provider": getattr(STATE, "llm", "rules only"),
            "downgraded": hid in getattr(STATE, "rules_decisions", {}),
            "rules_decision": show(STATE.rules_decisions[hid]) if hid in getattr(STATE, "rules_decisions", {}) else None,
        },
    }


def case_detail(hid):
    code, detail = hit_detail(hid)
    if code != 200:
        return code, detail
    detail["comparison"] = review_api.comparison(detail)
    detail["records"] = review_api.selectable_records(STATE, hid, detail)
    detail["history"] = STORE.history(hid)
    detail["workflow"] = review_api.workflow(detail["decision"]["decision"], detail["history"])["bucket"]
    detail["qa_sample"] = review_api.qa_sampled(hid, detail["decision"]["decision"])
    detail["court_available"] = court_llm is not None and llm is not None and llm.available()
    detail["people"] = people_view(hid)
    return 200, detail


def people_view(hid):
    """When several customers fit an alert: each person's key facts and the decision the SOP gives them."""
    d = STATE.decisions.get(hid)
    res = STATE.resolutions.get(d.alert_id) if d else None
    if not res or len(res.people) < 2:
        return []
    hit = STATE.data.hits[hid]
    alert = STATE.data.alerts.get(d.alert_id, {})
    prof = hitfacts.extract(hit, STATE.data)
    out = []
    for p in res.people:
        one = judge.decide_one(prof, p, alert)
        dob = p.verified_dob or (p.dobs[0] if p.dobs else None)
        name = p.verified_name or (p.names[0] if p.names else None)
        out.append({
            "person_id": p.person_id, "record_ids": p.record_ids,
            "name": show(name.value) if name else None,
            "dob": show(dob.value) if dob else None, "dob_source": dob.source if dob else None,
            "countries": sorted({str(f.value) for f in p.countries}),
            "decision": one.decision, "reason_code": one.reason_code,
        })
    return out


def post_review(body):
    hid = str(body.get("hit_id") or "")
    d = STATE.decisions.get(hid)
    if not d:
        return 404, {"error": "unknown hit " + hid}
    action = str(body.get("action") or "DECIDE").upper()
    reviewer = str(body.get("reviewer") or "").strip()[:80]
    role = str(body.get("role") or "analyst").strip().lower()[:20]
    rationale = str(body.get("rationale") or "").strip()[:4000]
    if not reviewer:
        return 400, {"error": "sign in with a reviewer name first"}
    if len(rationale) < 10:
        return 400, {"error": "write a rationale of at least 10 characters"}
    hist = STORE.history(hid)
    wf = review_api.workflow(d.decision, hist)
    engine_version = "rules+%s" % (getattr(STATE, "llm", "rules only"))
    if action == "DECIDE":
        decision = str(body.get("decision") or "").upper()
        if decision not in review_api.HUMAN:
            return 400, {"error": "decision must be one of " + ", ".join(review_api.HUMAN)}
        if wf["bucket"] in ("pending_approval", "done"):
            return 409, {"error": "this case already has a decision %s; the checker must return it first" % wf["bucket"].replace("_", " ")}
        code = str(body.get("reason_code") or "").upper()
        if code not in review_api.CODES[decision]:
            return 400, {"error": "%s needs a reason code from: %s" % (decision, ", ".join(review_api.CODES[decision]))}
        allowed = {r["id"] for r in review_api.selectable_records(STATE, hid, hit_detail(hid)[1])}
        rec_ids = [r for r in body.get("record_ids") or [] if r in allowed]
        if decision in ("CLEAR", "CONFIRM") and not rec_ids:
            return 400, {"error": "cite at least one record that supports the %s" % decision.lower()}
        STORE.add(hid, d.alert_id, reviewer, role, "DECIDE", decision, code, rec_ids, rationale,
                  d.decision, d.reason_code, body.get("court"), engine_version, getattr(STATE, "llm", ""))
    elif action in ("APPROVE", "RETURN"):
        if wf["bucket"] != "pending_approval":
            return 409, {"error": "nothing is waiting for approval on this case"}
        if wf["maker"]["reviewer"].strip().lower() == reviewer.lower():
            return 403, {"error": "four-eyes rule: the checker must be a different person from %s" % wf["maker"]["reviewer"]}
        STORE.add(hid, d.alert_id, reviewer, role, action, None, None, [], rationale,
                  d.decision, d.reason_code, None, engine_version, getattr(STATE, "llm", ""))
    else:
        return 400, {"error": "action must be DECIDE, APPROVE or RETURN"}
    hist = STORE.history(hid)
    return 200, {"ok": True, "history": hist, "workflow": review_api.workflow(d.decision, hist)["bucket"]}


def post_court(body):
    if court_llm is None:
        return 501, {"error": "the LLM court module (demo/court_llm.py) is not installed yet"}
    if llm is None or not llm.available():
        return 503, {"error": "no LLM key configured (set XAI_API_KEY or OPENROUTER_API_KEY in .env)"}
    hid = str(body.get("hit_id") or "")
    role = str(body.get("role") or "")
    if role not in ("prosecution", "defence", "adjudicator"):
        return 400, {"error": "role must be prosecution, defence or adjudicator"}
    code, detail = hit_detail(hid)
    if code != 200:
        return code, detail
    allowed = {r["id"]: r for r in review_api.selectable_records(STATE, hid, detail)}
    records = [{"id": rid, "kind": allowed[rid]["kind"], "text": allowed[rid]["text"]}
               for rid in body.get("record_ids") or [] if rid in allowed]
    try:
        out = court_llm.argue(role, review_api.court_case(detail), records, body.get("prior"))
    except Exception as e:  # never take the GUI down
        return 502, {"error": "court call failed: %s" % type(e).__name__}
    return 200, out


def main(argv):
    global STATE, STORE
    if len(argv) < 2:
        raise SystemExit(__doc__)
    folder = os.path.abspath(argv[1])
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else int(os.environ.get("PORT", "8765"))
    # Local by default. A hosted demo passes --host 0.0.0.0 (and should load invented fixtures only).
    host = argv[argv.index("--host") + 1] if "--host" in argv else "127.0.0.1"
    STATE = State(folder)
    STORE = review_api.ReviewStore()
    if "--blindfold" in argv:
        # Demo only: switch off our note parser so the rules miss lived-in places and verified
        # dates of birth, then watch the Grok cross-examiner catch the clearances that go wrong.
        resolve._parse_note = lambda note: None
        if crossexam is not None:
            crossexam._notes = None
        STATE.blindfold = True
        print("BLINDFOLD demo mode: note parser off, decisions differ from system/run on purpose")
    threading.Thread(target=STATE.build, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), Handler)
    print("Tryll on http://%s:%d  (data: %s)%s. Ctrl+C to stop." % (
        host, port, folder, ", passcode on" if os.environ.get("TRYLL_DEMO_PASSCODE") else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv)
