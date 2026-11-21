"""SOP principles 3, 6, 7: one decision per hit. [D]

decide(hit, res, alert) -> Decision. Per person, the first rule that fires wins (PLAN.md 5D):
 1 no usable facts -> REVIEW/INSUFFICIENT_DATA      6 every birth claim contradicted -> DOB_MISMATCH
 2 entity types differ -> ENTITY_TYPE_MISMATCH      7 verified name agrees with no hit name -> NAME_MISMATCH_VERIFIED
 3 died before screening -> DECEASED                8 no shared country -> LOCATION_MISMATCH (REVIEW if name+dob agree)
 4 too young / not incorporated -> TEMPORAL_...     9 agreement -> SAME_ENTITY
 5 compute name_ok, dob_ok, shared_country         10 otherwise REVIEW/INSUFFICIENT_DATA
Clearing needs a certain contradiction: anything unknown makes a rule not fire.
Matchers come from names.py and dates.py (module C); while they are missing only rules 1 and 2 run.
"""
from __future__ import annotations

from typing import List, Optional

from .model import BirthClaim, Decision, Fact, HitProfile, PartialDate, Person, Resolution
from . import explain

try:
    from . import names, dates
except ImportError:  # module C not merged yet
    names = dates = None  # type: ignore

DIFF, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"


def _etype(v) -> str:
    s = str(v or "").strip().lower()
    if s.startswith("indiv") or s == "person":
        return "individual"
    if s.startswith("comp") or s in ("organisation", "organization", "entity"):
        return "company"
    return s


def _is_company(t: str) -> bool:
    return _etype(t) == "company"


def _screened(alert: dict) -> Optional[PartialDate]:
    if dates is None:
        return None
    return dates.parse(str(alert.get("screened_at") or "")[:10]) if alert.get("screened_at") else None


def _cust_dobs(p: Person) -> List[Fact]:
    """Verified beats declared: the approved check's dob if there is one, else every declared dob."""
    if p.verified_dob is not None and isinstance(p.verified_dob.value, PartialDate) and p.verified_dob.value.year:
        return [p.verified_dob]
    return [f for f in p.dobs if isinstance(f.value, PartialDate) and f.value.year]


def _cust_names(p: Person) -> List[Fact]:
    if p.verified_name is not None and str(p.verified_name.value or "").strip():
        return [p.verified_name]
    return [f for f in p.names if str(f.value or "").strip()]


def _hit_births(hit: HitProfile) -> List[BirthClaim]:
    if hit.births:
        return list(hit.births)
    if _is_company(hit.entity_type) and hit.incorporated is not None:
        v = hit.incorporated.value
        if isinstance(v, PartialDate) and v.year:
            return [BirthClaim(years=(v.year,), month=v.month, day=v.day, source=hit.incorporated.source)]
    return []


def _norm_country(v) -> str:
    return str(v or "").strip().lower()


def _has_facts(p: Person) -> bool:
    return bool(p.names or p.dobs or p.countries or p.verified_name or p.verified_dob)


def _ctx(**kw) -> dict:
    return kw


def decide_one(hit: HitProfile, person: Person, alert: dict) -> Decision:
    company = _is_company(hit.entity_type)
    cid = person.person_id

    # 1. nothing to compare
    if not _has_facts(person):
        return explain.make(hit, REVIEW, "INSUFFICIENT_DATA", cid, [person],
                            _ctx(why="no_customer_facts"))

    # 2. person vs company
    ht, pt = _etype(hit.entity_type), _etype(person.entity_type)
    if ht and pt and ht != pt:
        return explain.make(hit, DIFF, "ENTITY_TYPE_MISMATCH", cid, [person],
                            _ctx(hit_type=ht, cust_type=pt))

    if names is None or dates is None:
        return explain.make(hit, REVIEW, "INSUFFICIENT_DATA", cid, [person], _ctx(why="matchers_missing"))

    # 3. died before the customer was screened
    screened = _screened(alert)
    if hit.deceased is not None and screened is not None and isinstance(hit.deceased.value, PartialDate):
        if dates.before(hit.deceased.value, screened) is True:
            return explain.make(hit, DIFF, "DECEASED", cid, [person],
                                _ctx(deceased=hit.deceased, screened=screened))

    cdobs = _cust_dobs(person)

    # 4. too young (or not yet incorporated) at the earliest dated report: must hold for every customer dob
    rep = hit.earliest_report
    if rep is not None and isinstance(rep.value, PartialDate) and rep.value.year and cdobs:
        if company:
            fired = all(dates.before(rep.value, f.value) is True for f in cdobs)
        else:
            fired = all(dates.younger_than(f.value, rep.value, 16) for f in cdobs)
        if fired:
            return explain.make(hit, DIFF, "TEMPORAL_IMPOSSIBILITY", cid, [person],
                                _ctx(dob=cdobs[0], report=rep, company=company))

    # 5. agreement facts
    hnames = [f for f in hit.names if str(f.value or "").strip()]
    cnames = _cust_names(person)
    name_fact = hit_name_fact = None
    for cf in cnames:
        cparts = names.real_part_count(str(cf.value))
        for hf in hnames:
            if not company and cparts < 2 and names.real_part_count(str(hf.value)) != 1:
                continue  # too few real parts: only a single-part hit alias can agree
            if names.names_agree(str(cf.value), str(hf.value), company):
                name_fact, hit_name_fact = cf, hf
                break
        if name_fact is not None:
            break
    name_ok = name_fact is not None

    births = _hit_births(hit)
    dob_fact = claim_fact = None
    for df in cdobs:
        for bc in births:
            if dates.birth_agrees(df.value, bc):
                dob_fact, claim_fact = df, bc
                break
        if dob_fact is not None:
            break
    dob_ok = dob_fact is not None

    ccountries = {}
    for f in person.countries:
        k = _norm_country(f.value)
        if k:
            ccountries.setdefault(k, []).append(f)
    hcountries = {}
    for f in hit.countries:
        k = _norm_country(f.value)
        if k:
            hcountries.setdefault(k, []).append(f)
    shared = sorted(set(ccountries) & set(hcountries))

    base = _ctx(name=name_fact, hit_name=hit_name_fact, dob=dob_fact, claim=claim_fact,
                shared=[ccountries[k][0] for k in shared], cdobs=cdobs, births=births,
                ccountries=[v[0] for k, v in sorted(ccountries.items())],
                hcountries=[v[0] for k, v in sorted(hcountries.items())],
                hit_names=hnames, cust_names=cnames, name_ok=name_ok, dob_ok=dob_ok)

    # 6. every birth claim contradicted, by every customer dob
    if births and cdobs and not dob_ok:
        if all(dates.birth_contradicted(df.value, bc) for df in cdobs for bc in births):
            return explain.make(hit, DIFF, "DOB_MISMATCH", cid, [person], dict(base, dob=cdobs[0]))

    # 7. the verified legal name agrees with none of the hit's names
    vn = person.verified_name
    if vn is not None and hnames and names.real_part_count(str(vn.value)) >= 2:
        if not any(names.names_agree(str(vn.value), str(hf.value), company) for hf in hnames):
            return explain.make(hit, DIFF, "NAME_MISMATCH_VERIFIED", cid, [person], dict(base, verified=vn))

    # 8. no shared country (exception: name and dob agree -> REVIEW)
    if ccountries and hcountries and not shared:
        if name_ok and dob_ok:
            return explain.make(hit, REVIEW, "INSUFFICIENT_DATA", cid, [person],
                                dict(base, why="countries_differ_name_dob_agree"))
        return explain.make(hit, DIFF, "LOCATION_MISMATCH", cid, [person], base)

    # 9. confirm on agreement
    if not company and name_ok and dob_ok:
        code = "NAME_DOB_LOCATION_MATCH" if shared else "NAME_DOB_MATCH"
        return explain.make(hit, SAME, code, cid, [person], base)
    if company and name_ok and shared:
        return explain.make(hit, SAME, "NAME_LOCATION_MATCH", cid, [person], base)

    # 10. nothing settles it
    return explain.make(hit, REVIEW, "INSUFFICIENT_DATA", cid, [person], dict(base, why="not_enough"))


def decide(hit: HitProfile, res: Resolution, alert: dict) -> Decision:
    people = sorted(res.people or [], key=lambda p: p.person_id)

    if not people:
        # we cannot know the customer: only the screened entity type can clear
        at, ht = _etype(alert.get("entity_type")), _etype(hit.entity_type)
        if at and ht and at != ht:
            return explain.make(hit, DIFF, "ENTITY_TYPE_MISMATCH", None, [],
                                _ctx(hit_type=ht, cust_type=at, screened_only=True))
        return explain.make(hit, REVIEW, "INSUFFICIENT_DATA", None, [], _ctx(why="no_customer", note=res.note))

    if len(people) == 1:
        return decide_one(hit, people[0], alert)

    each = [decide_one(hit, p, alert) for p in people]
    if len({d.decision for d in each}) == 1:
        first = each[0]
        ev = sorted({e for d in each for e in d.evidence})
        return Decision(hit_id=hit.hit_id, alert_id=hit.alert_id, decision=first.decision,
                        reason_code=first.reason_code, customer_record_id="AMBIGUOUS",
                        reason=explain.ambiguous_same(first, people), evidence=ev)
    return explain.make(hit, REVIEW, "AMBIGUOUS_CUSTOMER_RECORD", "AMBIGUOUS", people,
                        _ctx(each=each))
