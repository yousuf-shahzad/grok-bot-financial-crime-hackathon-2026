"""Reason text (2 to 4 sentences) and evidence selection. [D]

Stub: generic REVIEW reason until the templates land.
"""
from __future__ import annotations

from typing import List, Optional

from .model import Decision, HitProfile, Person


def build(hit: HitProfile, decision: str, code: str, customer_record_id: Optional[str],
          people: List[Person], sources: Optional[List[str]] = None) -> Decision:
    evidence = set(sources or [])
    for p in people:
        evidence.update(p.record_ids)
    reason = ("The checks for this hit are not implemented yet. "
              "It is sent to an analyst for review.")
    return Decision(hit_id=hit.hit_id, alert_id=hit.alert_id, decision=decision,
                    reason_code=code, customer_record_id=customer_record_id,
                    reason=reason, evidence=sorted(evidence))
