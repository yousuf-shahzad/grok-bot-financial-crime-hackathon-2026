"""Customer note -> NoteFacts. Module B.

Stub. `verified` and `rejected` are both false: the note is unknown, so it
is not an approved identity check and not a rejection. Rejected or expired
checks are never evidence; this stub does not invent either one.

NoteFacts is owned here (it is not in model.py). Resolver (module A) should
read these fields and ignore a note unless `verified` is true.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .model import PartialDate


@dataclass
class NoteFacts:
    verified: bool = False
    rejected: bool = False
    name: Optional[str] = None
    dob: Optional[PartialDate] = None
    doc_country: Optional[str] = None
    lived_in: List[str] = field(default_factory=list)
    date: Optional[str] = None  # note created_at, for "most recent approved"


def parse(note) -> NoteFacts:
    """Unknown note. `note` may be a notes.jsonl row or a text string.

    The real parser fills the fields in place; this signature stays.
    """
    return NoteFacts()
