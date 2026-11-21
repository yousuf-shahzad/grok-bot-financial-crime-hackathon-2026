"""Reason text (2 to 4 sentences, this hit's own facts) and evidence selection. [D]

make(hit, decision, code, customer_record_id, people, ctx) -> Decision
Evidence = the person's record IDs + source IDs of the facts that decided it.
H- and ACC- IDs are never cited (the practice labels never cite them).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .model import BirthClaim, Decision, Fact, HitProfile, PartialDate, Person

NO_CITE = ("H-", "ACC-")


def _clean(s) -> str:
    """Display text for a name or place: no sentence punctuation (keeps the sentence count honest)."""
    s = re.sub(r"[.!?;]+", "", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _q(s) -> str:
    return '"%s"' % _clean(s)


def fmt_date(d) -> str:
    if isinstance(d, Fact):
        d = d.value
    if not isinstance(d, PartialDate) or not d.year:
        return "an unknown date"
    out = "%04d" % d.year
    if d.month:
        out += "-%02d" % d.month
        if d.day:
            out += "-%02d" % d.day
    return out


def fmt_claim(c: BirthClaim) -> str:
    ys = sorted(set(c.years))
    if len(ys) == 1 and c.month:
        return fmt_date(PartialDate(ys[0], c.month, c.day))
    years = " or ".join(str(y) for y in ys)
    if c.month:
        return "%s (month %02d%s)" % (years, c.month, ", day %02d" % c.day if c.day else "")
    return years


def _src(f) -> str:
    s = getattr(f, "source", "") or ""
    return " (%s)" % s if s and not s.startswith(NO_CITE) else ""


def _join(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _countries(facts: Iterable[Fact], limit: int = 4) -> str:
    seen, out = set(), []
    for f in facts:
        k = _clean(f.value)
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    more = len(out) - limit
    text = _join(out[:limit])
    return text + (" and %d more" % more if more > 0 else "")


def _cite(people: List[Person], facts: Iterable) -> List[str]:
    ev = set()
    for p in people:
        ev.update(p.record_ids)
    for f in facts:
        s = getattr(f, "source", None)
        if s and not str(s).startswith(NO_CITE):
            ev.add(str(s))
    return sorted(ev)


def _hit_label(hit: HitProfile) -> str:
    return "the hit's %s" % ("listing as " + _clean(hit.listing_kind) if hit.listing_kind else "profile")


def _missing_sentence(hit: HitProfile, ctx: dict) -> str:
    gaps = []
    if not ctx.get("births"):
        gaps.append("the hit gives no date of birth")
    if not ctx.get("cdobs"):
        gaps.append("the customer has no date of birth on record")
    if ctx.get("births") and ctx.get("cdobs") and not ctx.get("dob_ok"):
        gaps.append("the dates of birth neither agree nor clearly contradict")
    if not ctx.get("name_ok"):
        gaps.append("the names do not agree closely enough")
    if not ctx.get("ccountries") or not ctx.get("hcountries"):
        gaps.append("a country is missing on one side")
    if not gaps:
        return "The evidence does not reach the bar for confirming the match."
    s = _join(gaps[:3])
    return s[0].upper() + s[1:] + "."


def make(hit: HitProfile, decision: str, code: str, customer_record_id: Optional[str],
         people: List[Person], ctx: Optional[dict] = None) -> Decision:
    ctx = ctx or {}
    used: List = []
    s: List[str] = []
    cust = ("the customer record %s" % customer_record_id
            if customer_record_id and customer_record_id != "AMBIGUOUS" else "the customer")

    if code == "ENTITY_TYPE_MISMATCH":
        who = "the screened customer" if ctx.get("screened_only") else cust
        s.append("The hit is listed as %s, but %s is %s." % (
            "a company" if ctx.get("hit_type") == "company" else "an individual", who,
            "a company" if ctx.get("cust_type") == "company" else "an individual"))
        s.append("A person and a company cannot be the same entity, so the hit is cleared.")

    elif code == "DECEASED":
        s.append("The hit's profile gives a date of death of %s." % fmt_date(ctx.get("deceased")))
        s.append("The customer was screened on %s, after that date, so the hit cannot be the customer."
                 % fmt_date(ctx.get("screened")))

    elif code == "TEMPORAL_IMPOSSIBILITY":
        dob, rep = ctx.get("dob"), ctx.get("report")
        used.append(dob)
        if ctx.get("company"):
            s.append("The customer company was incorporated on %s%s." % (fmt_date(dob), _src(dob)))
            s.append("The earliest dated report in the hit's profile is from %s, before the company existed."
                     % fmt_date(rep))
        else:
            s.append("The customer's date of birth is %s%s." % (fmt_date(dob), _src(dob)))
            s.append("The earliest dated report in the hit's profile is from %s, when the customer was "
                     "younger than 16." % fmt_date(rep))
        s.append("The reported activity cannot be the customer's, so the hit is cleared.")

    elif code == "DOB_MISMATCH":
        cdobs = ctx.get("cdobs") or []
        births = ctx.get("births") or []
        used.extend(cdobs)
        used.extend(births)
        s.append("The customer's date of birth is %s%s." % (
            _join([fmt_date(f) + _src(f) for f in cdobs[:2]]), ""))
        s.append("The hit gives a date of birth of %s, and every one of these is contradicted by the "
                 "customer's." % _join([fmt_claim(b) + _src(b) for b in births[:3]]))
        s.append("The dates of birth show they are different people.")

    elif code == "NAME_MISMATCH_VERIFIED":
        vn = ctx.get("verified")
        used.append(vn)
        hn = (ctx.get("hit_names") or [None])[0]
        s.append("The customer's verified legal name is %s%s." % (_q(vn.value), _src(vn)))
        s.append("It agrees with neither the hit's name %s nor any of its aliases." % (
            _q(hn.value) if hn else ""))
        s.append("The verified identity belongs to a different person, so the hit is cleared.")

    elif code == "LOCATION_MISMATCH":
        cc = ctx.get("ccountries") or []
        used.extend(cc)
        s.append("The customer is tied to %s%s." % (
            _countries(cc), " (%s)" % ", ".join(sorted({f.source for f in cc if f.source and not f.source.startswith(NO_CITE)}))
            if any(f.source and not f.source.startswith(NO_CITE) for f in cc) else ""))
        s.append("The hit is tied only to %s, so no country is shared." % _countries(ctx.get("hcountries") or []))
        if ctx.get("name_ok"):
            s.append("The names agree but no date of birth confirms it, so the location difference "
                     "clears the hit.")
        else:
            s.append("Nothing else ties the hit to the customer, so the location difference clears it.")

    elif decision == "SAME_ENTITY":
        nf, hn, df, cl = ctx.get("name"), ctx.get("hit_name"), ctx.get("dob"), ctx.get("claim")
        used.extend([nf, df, cl] + list(ctx.get("shared") or []))
        s.append("The customer's name %s%s agrees with the hit's name %s." % (
            _q(nf.value) if nf else "", _src(nf), _q(hn.value) if hn else ""))
        if code != "NAME_LOCATION_MATCH" and df is not None and cl is not None:
            s.append("The customer's date of birth %s%s agrees with the hit's %s%s." % (
                fmt_date(df), _src(df), fmt_claim(cl), _src(cl)))
        if ctx.get("shared"):
            s.append("Both are tied to %s." % _countries(ctx["shared"]))
        s.append("Nothing in the records contradicts the match.")

    elif code == "AMBIGUOUS_CUSTOMER_RECORD":
        ids = [p.person_id for p in people]
        each = ctx.get("each") or []
        kinds = _join(sorted({d.decision.replace("_", " ").lower() for d in each}))
        s.append("%d different customers fit this alert (%s)." % (len(ids), ", ".join(ids[:4])))
        s.append("Judged one by one they lead to different outcomes (%s)." % kinds)
        s.append("An analyst must decide which customer was screened.")
        for d in each:
            used.extend(Fact(value="", source=e) for e in d.evidence)

    else:  # REVIEW / INSUFFICIENT_DATA
        why = ctx.get("why")
        if why == "no_customer":
            s.append("No customer record could be found that fits the screened details.")
            s.append("Without the customer's own facts the hit can be neither confirmed nor cleared.")
        elif why == "no_customer_facts":
            s.append("The customer has no usable name, date of birth or country on record.")
            s.append("Nothing can be compared with the hit, so it goes to an analyst.")
        elif why == "matchers_missing":
            s.append("The name and date matchers are not available in this build.")
            s.append("The hit is sent to an analyst for review.")
        elif why == "countries_differ_name_dob_agree":
            nf, hn, df, cl = ctx.get("name"), ctx.get("hit_name"), ctx.get("dob"), ctx.get("claim")
            used.extend([nf, df, cl])
            s.append("The customer's name %s%s agrees with the hit's %s, and their date of birth %s%s "
                     "agrees with the hit's %s." % (
                         _q(nf.value) if nf else "", _src(nf), _q(hn.value) if hn else "name",
                         fmt_date(df), _src(df), fmt_claim(cl) if cl else "date of birth"))
            s.append("However the customer is tied to %s and the hit only to %s." % (
                _countries(ctx.get("ccountries") or []), _countries(ctx.get("hcountries") or [])))
            s.append("A country difference does not clear a hit whose name and date of birth agree, "
                     "so an analyst must decide.")
        else:
            s.append("No contradiction rules the hit out, but there is not enough agreement to confirm it.")
            s.append(_missing_sentence(hit, ctx))
            if hit.missing:
                s.append("Known gaps: %s." % _clean("; ".join(hit.missing[:2]).replace(";", ",")))

    s = [x for x in s if x][:4]
    if len(s) < 2:
        s.append("The hit is sent to an analyst for review.")
    return Decision(hit_id=hit.hit_id, alert_id=hit.alert_id, decision=decision, reason_code=code,
                    customer_record_id=customer_record_id, reason=" ".join(s),
                    evidence=_cite(people, [u for u in used if u is not None]))


def ambiguous_same(first: Decision, people: List[Person]) -> str:
    """Reason when several people fit but all lead to the same decision."""
    ids = ", ".join(p.person_id for p in people[:4])
    body = first.reason.split(". ")
    lead = "%d customers fit this alert (%s) and each leads to the same decision." % (len(people), ids)
    rest = ". ".join(body[:2]).rstrip(".") + "."
    return lead + " " + rest
