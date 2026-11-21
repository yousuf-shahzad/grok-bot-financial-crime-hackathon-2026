"""Hit row -> HitProfile (SOP principle 5). Module B.

Stub. Returns the hit's own ids and entity type, and no extracted facts.
A missing fact is not a mismatch: empty births, countries and dates cannot
clear or confirm a hit. The real parser replaces this function in place;
the signature stays `extract(hit, data) -> HitProfile`.
"""
from __future__ import annotations

from .model import HitProfile


def extract(hit: dict, data) -> HitProfile:
    """Neutral profile for one raw hits.jsonl row.

    `hit` is the row dict. `data` is the loader result (unused until the
    real parser reads search_by_query). Never raises on a missing field.
    """
    row = hit if isinstance(hit, dict) else {}
    return HitProfile(
        hit_id=str(row.get("hit_id") or ""),
        alert_id=str(row.get("alert_id") or ""),
        entity_type=str(row.get("entity_type") or ""),
        missing=["no date of birth in dobs, notes or search results"],
    )
