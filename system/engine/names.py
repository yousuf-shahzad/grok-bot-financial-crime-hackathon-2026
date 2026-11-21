"""SOP principle 8: name parts and name agreement. [C]

Stub with the final signatures from PLAN.md section 5C. Until the real
matcher lands, every comparison is "unknown": no parts, no agreement, and
0 real parts, so the judge can neither confirm nor clear on name (REVIEW).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

VARIANTS = []  # type: List[List[str]]
LEGAL_FORMS = []  # type: List[str]


def use_variants(name_variants: Optional[dict]) -> None:
    """Prefer the data folder's parsed name_variants.json (Data.name_variants)."""
    return None


def parts(name: Optional[str], company: bool = False) -> List[str]:
    return []


def parts_match(a: str, b: str) -> bool:
    return False


def names_agree(a: Optional[str], b: Optional[str], company: bool = False) -> bool:
    return False


def real_part_count(name: Optional[str], company: bool = False) -> int:
    return 0