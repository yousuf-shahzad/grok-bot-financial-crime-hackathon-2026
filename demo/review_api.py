"""Human-in-the-loop review API for Case Review (owner: Yousuf's Claude).

The engine only RECOMMENDS. A named reviewer records every final call here:
  CLEAR     -> the hit is a different entity (false positive), alert can close
  CONFIRM   -> the hit is the customer, goes to compliance
  ESCALATE  -> needs more information or a second reviewer
with a written rationale. Reviews are append-only (an audit trail): a later review supersedes an
earlier one but never deletes it. Storage is SQLite (stdlib), in demo/.reviews/ (gitignored) or the
path in CASE_REVIEW_DB. The LLM court (demo/court_llm.py) runs only when a reviewer asks for it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
HUMAN = ("CLEAR", "CONFIRM", "ESCALATE")
SYSTEM_TO_HUMAN = {"DIFFERENT_ENTITY": "CLEAR", "SAME_ENTITY": "CONFIRM", "REVIEW": "ESCALATE"}
HUMAN_TO_OUTPUT = {"CLEAR": "DIFFERENT_ENTITY", "CONFIRM": "SAME_ENTITY", "ESCALATE": "REVIEW"}


class ReviewStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("CASE_REVIEW_DB") or os.path.join(HERE, ".reviews", "reviews.sqlite3")
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hit_id TEXT NOT NULL, alert_id TEXT NOT NULL, reviewer TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'analyst', action TEXT NOT NULL DEFAULT 'DECIDE',
                decision TEXT, reason_code TEXT, record_ids TEXT, rationale TEXT NOT NULL,
                system_decision TEXT, system_reason_code TEXT, agreed_with_system INTEGER,
                court_json TEXT, engine_version TEXT, llm TEXT, created_at TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_reviews_hit ON reviews(hit_id, id)")
            # append-only audit trail: the database itself refuses edits and deletions
            c.execute("CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON reviews "
                      "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END")
            c.execute("CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON reviews "
                      "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, hit_id, alert_id, reviewer, role, action, decision, reason_code, record_ids, rationale,
            system_decision, system_code, court=None, engine_version="", llm_name="") -> dict:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        agreed = int(SYSTEM_TO_HUMAN.get(system_decision) == decision) if decision else None
        with self.lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO reviews(hit_id, alert_id, reviewer, role, action, decision, reason_code, record_ids, "
                "rationale, system_decision, system_reason_code, agreed_with_system, court_json, engine_version, llm, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (hit_id, alert_id, reviewer, role, action, decision, reason_code, json.dumps(record_ids or []),
                 rationale, system_decision, system_code, agreed, json.dumps(court) if court else None,
                 engine_version, llm_name, now))
            rid = cur.lastrowid
        return {"id": rid, "created_at": now}

    def history(self, hit_id) -> List[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM reviews WHERE hit_id=? ORDER BY id", (hit_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["court"] = json.loads(d.pop("court_json")) if d.get("court_json") else None
            d["record_ids"] = json.loads(d["record_ids"]) if d.get("record_ids") else []
            out.append(d)
        return out

    def all_rows(self) -> Dict[str, List[dict]]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM reviews ORDER BY id").fetchall()
        out: Dict[str, List[dict]] = {}
        for r in rows:
            out.setdefault(r["hit_id"], []).append(dict(r))
        return out

    def stats(self) -> dict:
        with self._conn() as c:
            total, = c.execute("SELECT COUNT(*) FROM reviews").fetchone()
            reviewers = [r[0] for r in c.execute("SELECT DISTINCT reviewer FROM reviews ORDER BY reviewer")]
        return {"reviews_logged": total, "reviewers": reviewers}


# --------------------------------------------------------------------------------------------
# Views built on the engine state (STATE from app.py)
# --------------------------------------------------------------------------------------------

CLEAR_CODES = ("TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH", "NAME_MISMATCH_VERIFIED",
               "ENTITY_TYPE_MISMATCH", "DECEASED")
CONFIRM_CODES = ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH")
ESCALATE_CODES = ("INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD", "RFI_REQUESTED", "SECOND_OPINION")
CODES = {"CLEAR": CLEAR_CODES, "CONFIRM": CONFIRM_CODES, "ESCALATE": ESCALATE_CODES}
QA_RATE = 10  # one in ten engine clearances is sampled for human QA (deterministic by hit ID)


def qa_sampled(hit_id: str, system_decision: str) -> bool:
    import hashlib
    return system_decision == "DIFFERENT_ENTITY" and int(hashlib.sha256(hit_id.encode()).hexdigest(), 16) % QA_RATE == 0


def workflow(system_decision: str, rows: List[dict]) -> dict:
    """Maker-checker state of one hit from its append-only history.

    DECIDE (maker) CLEAR/CONFIRM -> pending_approval until a DIFFERENT reviewer APPROVEs (done) or
    RETURNs it (returned, back to the queue). DECIDE ESCALATE -> escalated (needs a second-line view).
    """
    decides = [r for r in rows if r.get("action") == "DECIDE"]
    if not decides:
        b = {"REVIEW": "needs_decision", "DIFFERENT_ENTITY": "proposed_clear", "SAME_ENTITY": "proposed_match"}.get(system_decision, "needs_decision")
        return {"bucket": b, "maker": None, "checker": None, "decision": None}
    d = decides[-1]
    after = [r for r in rows if r["id"] > d["id"] and r.get("action") in ("APPROVE", "RETURN")]
    last = after[-1] if after else None
    if last and last["action"] == "APPROVE":
        return {"bucket": "done", "maker": d, "checker": last, "decision": d["decision"]}
    if last and last["action"] == "RETURN":
        return {"bucket": "returned", "maker": d, "checker": last, "decision": None}
    if d["decision"] == "ESCALATE":
        return {"bucket": "escalated", "maker": d, "checker": None, "decision": "ESCALATE"}
    return {"bucket": "pending_approval", "maker": d, "checker": None, "decision": d["decision"]}


BUCKET_ORDER = ["needs_decision", "returned", "pending_approval", "proposed_match", "proposed_clear", "escalated", "done"]


def case_rows(state, store, q: dict) -> dict:
    hist = store.all_rows()
    want_bucket = q.get("bucket") or ""
    text = (q.get("q") or "").strip().lower()
    practice_only = q.get("practice") == "1"
    qa_only = q.get("qa") == "1"
    counts = {b: 0 for b in BUCKET_ORDER}
    counts["qa_sample"] = 0
    rows = []
    for hid, d in state.decisions.items():
        wf = workflow(d.decision, hist.get(hid, []))
        b = wf["bucket"]
        qa = qa_sampled(hid, d.decision)
        counts[b] += 1
        counts["qa_sample"] += int(qa and b == "proposed_clear")
        if want_bucket and b != want_bucket:
            continue
        if practice_only and hid not in state.labels:
            continue
        if qa_only and not qa:
            continue
        hit = state.data.hits[hid]
        alert = state.data.alerts.get(d.alert_id, {})
        row = {
            "hit_id": hid, "alert_id": d.alert_id, "hit_name": hit.get("name"),
            "screened_name": alert.get("customer_name"), "entity_type": hit.get("entity_type"),
            "listing": hit.get("primary_category") or hit.get("categories"),
            "system": {"decision": d.decision, "reason_code": d.reason_code},
            "bucket": b, "qa_sample": qa,
            "human": ({"decision": wf["decision"], "maker": wf["maker"]["reviewer"],
                       "checker": wf["checker"]["reviewer"] if wf["checker"] else None,
                       "at": (wf["checker"] or wf["maker"])["created_at"]} if wf["maker"] else None),
            "crossexamined": hid in getattr(state, "rules_decisions", {}),
        }
        lab = state.labels.get(hid)
        if lab:
            row["practice_truth"] = lab["decision"]
        if text and text not in json.dumps(row, ensure_ascii=False).lower():
            continue
        rows.append(row)
    sev = {"Sanctions": 0, "PEP": 1, "Enforcement": 2, "Adverse Media": 3}
    rows.sort(key=lambda r: (BUCKET_ORDER.index(r["bucket"]), sev.get(str(r["listing"] or "").split(";")[0].strip(), 4), r["alert_id"], r["hit_id"]))
    return {"rows": rows[:3000], "total": len(rows), "counts": counts}


def mi(state, store) -> dict:
    """Management information: workload, agreement with the engine, four-eyes outcomes."""
    hist = store.all_rows()
    decides = [r for rows in hist.values() for r in rows if r.get("action") == "DECIDE"]
    approvals = [r for rows in hist.values() for r in rows if r.get("action") == "APPROVE"]
    returns = [r for rows in hist.values() for r in rows if r.get("action") == "RETURN"]
    agreed = sum(1 for r in decides if r.get("agreed_with_system"))
    by_rev = {}
    for r in decides + approvals + returns:
        by_rev[r["reviewer"]] = by_rev.get(r["reviewer"], 0) + 1
    buckets = {b: 0 for b in BUCKET_ORDER}
    for hid, d in state.decisions.items():
        buckets[workflow(d.decision, hist.get(hid, []))["bucket"]] += 1
    return {"decisions": len(decides), "approvals": len(approvals), "returns": len(returns),
            "agreement_rate": round(100.0 * agreed / len(decides), 1) if decides else None,
            "overrides": len(decides) - agreed, "by_reviewer": by_rev, "buckets": buckets,
            "audit_rows": sum(len(v) for v in hist.values())}


def _fmt(v) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, dict) and "value" in v:
        return str(v["value"])
    return str(v)


def comparison(detail: dict) -> List[dict]:
    """Side-by-side rows customer vs hit, each with a status: agree | contradict | unknown."""
    trial = (detail.get("court") or [None])[0]
    prof = detail.get("profile") or {}
    res = detail.get("resolution") or {}
    person = (res.get("people") or [None])[0]
    pros = {p["what"]: p for p in (trial or {}).get("prosecution", [])}
    dfn = {d["rule"]: d for d in (trial or {}).get("defence", [])}

    def status(agree_key, rule):
        if agree_key in pros:
            return "agree"
        if rule in dfn and dfn[rule]["holds"]:
            return "contradict"
        return "unknown"

    def facts(lst):
        return [{"value": _fmt(f), "source": f.get("source"), "kind": f.get("kind")} for f in (lst or []) if isinstance(f, dict)]

    rows = []
    if person:
        cust_names = facts([person.get("verified_name")] if person.get("verified_name") else person.get("names"))
        cust_dobs = facts([person.get("verified_dob")] if person.get("verified_dob") else person.get("dobs"))
        cust_c = facts(person.get("countries"))
        cust_type = [{"value": person.get("entity_type") or "unknown", "source": person.get("person_id")}]
    else:
        cust_names = cust_dobs = cust_c = cust_type = []
    rows.append({"field": "Name", "customer": cust_names, "hit": facts(prof.get("names")),
                 "status": status("Name agrees", "Verified name matches none of the hit's names"),
                 "note": (pros.get("Name agrees") or {}).get("detail") or (dfn.get("Verified name matches none of the hit's names") or {}).get("detail")})
    rows.append({"field": "Date of birth", "customer": cust_dobs,
                 "hit": [{"value": b, "source": None} for b in (prof.get("births") or [])],
                 "status": status("Date of birth agrees", "Every hit birth date contradicted"),
                 "note": (pros.get("Date of birth agrees") or {}).get("detail") or (dfn.get("Every hit birth date contradicted") or {}).get("detail")})
    rows.append({"field": "Countries", "customer": cust_c, "hit": facts(prof.get("countries")),
                 "status": status("Country shared", "Every country differs"),
                 "note": (dfn.get("Every country differs") or {}).get("note") or (pros.get("Country shared") or {}).get("detail")})
    rows.append({"field": "Entity type", "customer": cust_type, "hit": [{"value": prof.get("entity_type") or "unknown", "source": prof.get("hit_id")}],
                 "status": "contradict" if (dfn.get("Entity type") or {}).get("holds") else ("agree" if person else "unknown"), "note": None})
    timeline = []
    if prof.get("earliest_report"):
        timeline.append({"value": "earliest dated report " + _fmt(prof["earliest_report"]), "source": prof["earliest_report"].get("source")})
    if prof.get("deceased"):
        timeline.append({"value": "deceased " + _fmt(prof["deceased"]), "source": prof["deceased"].get("source")})
    young = (dfn.get("Too young / not yet incorporated") or {}).get("holds")
    dead = (dfn.get("Died before screening") or {}).get("holds")
    rows.append({"field": "Timeline", "customer": cust_dobs[:1], "hit": timeline,
                 "status": "contradict" if (young or dead) else "unknown",
                 "note": "too young at the earliest report" if young else ("died before screening" if dead else None)})
    return rows


def _record_text(kind: str, row: dict) -> str:
    keep = {
        "customer": ("full_name", "preferred_name", "dob", "nationality", "residence_country", "city", "address", "entity_type", "status"),
        "kyc_check": ("provider", "verified_name", "verified_dob", "document_type", "document_country", "result", "checked_at"),
        "note": ("created_at", "channel", "text"),
        "search_result": ("query", "title", "snippet", "source"),
        "hit": ("name", "aliases", "entity_type", "dobs", "countries", "nationality", "citizenship", "place_of_birth",
                "primary_category", "categories", "life_status", "deceased_date", "profile_notes"),
        "alert": ("customer_name", "entity_type", "dob", "country", "city", "screened_at"),
    }.get(kind)
    if not keep:
        return json.dumps(row, ensure_ascii=False)[:1500]
    parts = []
    for k in keep:
        v = row.get(k)
        if v not in (None, "", []):
            parts.append("%s: %s" % (k, v if not isinstance(v, list) else "; ".join(map(str, v))))
    return "\n".join(parts)[:4000]


def selectable_records(state, hit_id: str, detail: dict) -> List[dict]:
    """Every record a reviewer may hand to the LLM court, grouped and pre-ticked sensibly."""
    data = state.data
    hit = data.hits[hit_id]
    out, seen = [], set()
    cited = set(((detail.get("decision") or {}).get("evidence")) or [])

    def add(rid, group, default):
        if not rid or rid in seen or rid not in state.records:
            return
        seen.add(rid)
        kind, row = state.records[rid]
        out.append({"id": rid, "kind": kind, "group": group, "default": bool(default or rid in cited),
                    "text": _record_text(kind, row)})

    add(hit_id, "Watchlist hit", True)
    add(str(hit.get("alert_id")), "Alert", True)
    res = detail.get("resolution") or {}
    for person in res.get("people") or []:
        for rid in person.get("record_ids") or []:
            add(rid, "Customer records", True)
            for chk_rows in [data.kyc_by_applicant.get(str(o.get("kyc_applicant_id")), []) for o in data.onboarding_by_customer.get(rid, [])]:
                for chk in chk_rows:
                    add(str(chk.get("check_id")), "Identity checks", str(chk.get("result")).lower() == "approved")
            email = str((data.customers.get(rid) or {}).get("email") or "").strip().lower()
            for note in data.notes_by_email.get(email, []) if email else []:
                if str(note.get("channel")).lower() != "app":
                    add(str(note.get("note_id")), "Customer notes", str(note.get("channel")).lower() in ("kyc", "email", "phone"))
    try:
        from engine import hitfacts
        q = hitfacts._folded_query(str(hit.get("name") or ""))
        for r in data.search_by_query.get(q, [])[:12]:
            add(str(r.get("result_id")), "Web search results (mostly namesakes)", False)
    except Exception:
        pass
    return out


def court_case(detail: dict) -> dict:
    prof = detail.get("profile") or {}
    res = detail.get("resolution") or {}
    person = (res.get("people") or [None])[0]
    trial = (detail.get("court") or [None])[0] or {}
    d = detail.get("decision") or {}
    return {
        "hit": {k: prof.get(k) for k in ("hit_id", "names", "births", "countries", "listing_kind", "earliest_report", "deceased", "missing", "entity_type")},
        "customer": person,
        "rules": {"recommendation": d.get("decision"), "reason_code": d.get("reason_code"), "reason": d.get("reason"),
                  "evidence": d.get("evidence"), "prosecution": trial.get("prosecution", []), "defence": trial.get("defence", [])},
    }


def export_lines(state, store) -> str:
    """reviewed_decisions.jsonl: our output format with the APPROVED human call where one exists.
    Never save this as output/dev.jsonl: that file must come from system/run alone."""
    hist = store.all_rows()
    lines = []
    for hid, d in sorted(state.decisions.items(), key=lambda kv: (kv[1].alert_id, kv[0])):
        wf = workflow(d.decision, hist.get(hid, []))
        done = wf["bucket"] == "done"
        m = wf["maker"]
        lines.append(json.dumps({
            "hit_id": hid, "alert_id": d.alert_id,
            "decision": HUMAN_TO_OUTPUT[wf["decision"]] if done else d.decision,
            "reason_code": (m["reason_code"] or d.reason_code) if done else d.reason_code,
            "customer_record_id": d.customer_record_id,
            "reason": m["rationale"] if done else d.reason,
            "evidence": json.loads(m["record_ids"]) if done and m.get("record_ids") else d.evidence,
            "status": wf["bucket"], "maker": m["reviewer"] if m else None,
            "checker": wf["checker"]["reviewer"] if wf["checker"] else None,
        }, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def case_report(state, store, hit_id: str, detail: dict) -> str:
    """A one-page Markdown case file for audit: facts, comparison, engine view, human decisions."""
    d = detail.get("decision") or {}
    hist = store.history(hit_id)
    wf = workflow(d.get("decision"), hist)
    prof = detail.get("profile") or {}
    alert = detail.get("alert") or {}
    first_name = ((prof.get("names") or [{}])[0] or {}).get("value")
    lines = ["# Screening case %s (alert %s)" % (hit_id, d.get("alert_id")), "",
             "- Screened as: %s" % alert.get("customer_name"),
             "- Watchlist profile: %s (%s)" % (first_name, prof.get("listing_kind") or "listing"),
             "- Customer record: %s" % d.get("customer_record_id"),
             "- Status: **%s**" % wf["bucket"].replace("_", " "), "",
             "## Engine recommendation", "",
             "%s / %s" % (d.get("decision"), d.get("reason_code")), "", d.get("reason") or "", "",
             "Evidence: %s" % ", ".join(d.get("evidence") or []), "", "## Customer vs hit", "",
             "| Field | Customer | Hit | Status |", "|---|---|---|---|"]
    for r in detail.get("comparison") or []:
        cust = "; ".join(str(x.get("value")) for x in r["customer"]) or "-"
        hitv = "; ".join(str(x.get("value") if isinstance(x, dict) else x) for x in r["hit"]) or "-"
        lines.append("| %s | %s | %s | %s |" % (r["field"], cust, hitv, r["status"]))
    if prof.get("missing"):
        lines += ["", "Known unknowns: " + "; ".join(prof["missing"])]
    lines += ["", "## Audit trail (append-only)", ""]
    for h in hist:
        what = (" " + h["decision"] + " / " + (h.get("reason_code") or "")) if h.get("decision") else ""
        lines.append("- %s %s by %s (%s)%s: %s" % (h["created_at"], h["action"], h["reviewer"], h.get("role"), what, h["rationale"]))
    if not hist:
        lines.append("- no human review yet")
    return "\n".join(lines) + "\n"
