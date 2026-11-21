"""Partial dates: parsing, agreement and contradiction (SPEC.md sections 3 and 4)."""
from __future__ import annotations

import calendar
import re
from typing import Optional, Tuple

from .model import BirthClaim, PartialDate

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_M = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"


def _make(y, m=None, d=None) -> Optional[PartialDate]:
    y = int(y)
    m = int(m) if m is not None else None
    d = int(d) if d is not None else None
    if not 1000 <= y <= 2999:
        return None
    if m is not None and not 1 <= m <= 12:
        return None
    if d is not None and (m is None or not 1 <= d <= calendar.monthrange(y, m)[1]):
        return None
    return PartialDate(y, m, d)


def parse(s) -> Optional[PartialDate]:
    """Parse one date as written; unknown parts stay None. Numeric d/m/y is day first."""
    if isinstance(s, PartialDate):
        return s
    if s is None:
        return None
    t = str(s).strip().lower().rstrip(".")
    if not t:
        return None
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[t ].*)?", t) or re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", t)
    if m:
        return _make(m.group(1), m.group(2), m.group(3))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m:
        return _make(m.group(1), m.group(2))
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return _make(m.group(1))
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
    if m:
        return _make(m.group(3), m.group(2), m.group(1))
    m = re.fullmatch(_M + r"\s+(\d{1,2}),?\s+(\d{4})", t)
    if m:
        return _make(m.group(3), MONTHS[m.group(1)], m.group(2))
    m = re.fullmatch(r"(\d{1,2})\s+" + _M + r",?\s+(\d{4})", t)
    if m:
        return _make(m.group(3), MONTHS[m.group(2)], m.group(1))
    m = re.fullmatch(_M + r",?\s+(\d{4})", t)
    if m:
        return _make(m.group(2), MONTHS[m.group(1)])
    return None


def same_in_shared_parts(a: Optional[PartialDate], b: Optional[PartialDate]) -> bool:
    """Equal in every part both give. A missing date fails nothing."""
    if a is None or b is None:
        return True
    for x, y in ((a.year, b.year), (a.month, b.month), (a.day, b.day)):
        if x is not None and y is not None and x != y:
            return False
    return True


def birth_agrees(customer: Optional[PartialDate], claim: BirthClaim) -> bool:
    """Customer year is one of the claim's years, and month and day equal wherever both give them."""
    if customer is None or customer.year is None or customer.year not in claim.years:
        return False
    if customer.month is not None and claim.month is not None and customer.month != claim.month:
        return False
    if customer.day is not None and claim.day is not None and customer.day != claim.day:
        return False
    return True


def birth_contradicted(customer: Optional[PartialDate], claim: BirthClaim) -> bool:
    """Year more than 1 outside every claimed year, or same year with differing month (or day)."""
    if customer is None or customer.year is None or not claim.years:
        return False
    if all(abs(customer.year - y) > 1 for y in claim.years):
        return True
    if customer.year in claim.years and customer.month is not None and claim.month is not None:
        if customer.month != claim.month:
            return True
        if customer.day is not None and claim.day is not None and customer.day != claim.day:
            return True
    return False


def _bounds(d: PartialDate) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Earliest and latest (y, m, d) a partial date can be."""
    lo_m, hi_m = (d.month, d.month) if d.month else (1, 12)
    lo_d = d.day or 1
    hi_d = d.day or calendar.monthrange(d.year, hi_m)[1]
    return (d.year, lo_m, lo_d), (d.year, hi_m, hi_d)


def younger_than(dob: Optional[PartialDate], at: Optional[PartialDate], years: int = 16) -> bool:
    """True only if certainly younger than `years` at `at` (oldest possible age is used)."""
    if dob is None or at is None or dob.year is None or at.year is None:
        return False
    born, _ = _bounds(dob)       # earliest possible birth
    _, when = _bounds(at)        # latest possible date of the event
    age = when[0] - born[0] - ((when[1], when[2]) < (born[1], born[2]))
    return age < years


def before(a: Optional[PartialDate], b: Optional[PartialDate]) -> Optional[bool]:
    """True if a is certainly before b, False if certainly not, None if it cannot be told."""
    if a is None or b is None or a.year is None or b.year is None:
        return None
    a_lo, a_hi = _bounds(a)
    b_lo, b_hi = _bounds(b)
    if a_hi < b_lo:
        return True
    if a_lo >= b_hi:
        return False
    return None
