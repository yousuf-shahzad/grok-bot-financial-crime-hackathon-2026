"""SOP principles 3, 6, 7: one decision per hit. [D]

Stub: every hit goes to REVIEW / INSUFFICIENT_DATA until the full rules land.
"""
from __future__ import annotations

from .model import Decision, HitProfile, Person, Resolution
from . import explain


def decide_one(hit: HitProfile, person: Person, alert: dict) -> Decision:
    return explain.build(hit, "REVIEW", "INSUFFICIENT_DATA", person.person_id, [person])


def decide(hit: HitProfile, res: Resolution, alert: dict) -> Decision:
    people = list(res.people or [])
    cid = None if not people else (people[0].person_id if len(people) == 1 else "AMBIGUOUS")
    return explain.build(hit, "REVIEW", "INSUFFICIENT_DATA", cid, people)
