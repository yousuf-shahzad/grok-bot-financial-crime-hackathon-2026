"""Customer note -> NoteFacts. Module B.

parse(note) -> NoteFacts. note is a raw notes.jsonl dict or a plain string.

resolve.py reads: verified, rejected, name, dob (PartialDate or str),
doc_country, lived_in (list), date. It stores the note_id itself as Fact.source.

verified is true only when the onboarding sentence is complete: a provider
validated or completed identity verification of NAME, with one born/DOB date
and one document country. A missing part stays unknown. A wrong verified name
can clear a hit.

rejected is true on rejected / could not verify / expired, and those fields
are not evidence. If success and failure both appear, both flags stay false.

lived_in is read either way ("used to live in", "moved from", "previously
lived in", "formerly lived in"). date is the note's created_at string.

Patterns follow the PLAN/SPEC shapes. This environment has no notes.jsonl,
so a differently worded unseen note stays unknown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .hitfacts import _find_date, _normalise
from .model import PartialDate


@dataclass
class NoteFacts:
    verified: bool = False
    rejected: bool = False
    name: Optional[str] = None
    dob: Optional[PartialDate] = None
    doc_country: Optional[str] = None
    lived_in: List[str] = field(default_factory=list)
    date: Optional[str] = None  # created_at; resolve parses it when it is not a PartialDate


_NAME_STOP = r"born|dob|d\.?o\.?b|date|document"
_VERIFY_NAME = re.compile(
    r"(?i)\b(?:validated|completed)\b(?:\s+[A-Za-z]+){0,6}?\s+"
    r"identity\s+verification\s+of\s+"
    r"(?P<name>[A-Za-z][A-Za-z'’\-]*"
    r"(?:\s+(?!(?:" + _NAME_STOP + r")\b)[A-Za-z][A-Za-z'’\-]*){0,5})"
)
_DOB_CUE = re.compile(
    r"(?i)\b(?:born(?:\s+on|\s+in)?|date\s+of\s+birth|birth\s+date|d\.?o\.?b\.?)"
    r"\s*[:\-]?\s*([^.;\n]{1,60})"
)
_DOC_COUNTRY = re.compile(
    r"(?i)\b(?:document\s+(?:issued\s+in|issued\s+by|from)|issued\s+in)\s+([^.;\n]{2,60})"
)
_HARD_FAILURE = re.compile(
    r"(?i)\bcould not verify\b|\bcouldn't verify\b|\bcould not be verified\b|\bunable to verify\b"
)
_SOFT_FAILURE = re.compile(r"(?i)\b(?:rejected|expired)\b")
_NEGATED = re.compile(r"(?i)\b(?:not|never|no)\b(?:\s+\w+){0,3}\s*$")
_LIVED = (
    re.compile(r"(?i)\bused to live in\s+([^.;\n]+)"),
    re.compile(r"(?i)\bpreviously lived in\s+([^.;\n]+)"),
    re.compile(r"(?i)\bformerly lived in\s+([^.;\n]+)"),
    re.compile(r"(?i)\bmoved from\s+([^.;\n]+)"),
)


def parse(note) -> NoteFacts:
    """Unknown unless the verification sentence or a failure wording is clear."""
    text, date = _text_and_date(note)
    lived = _lived_in(text)
    failure = _has_failure(text)
    name, dob, country = _verification(text)
    success = name is not None and dob is not None and country is not None
    if failure and success:
        return NoteFacts(lived_in=lived, date=date)
    if failure:
        return NoteFacts(rejected=True, lived_in=lived, date=date)
    if success:
        return NoteFacts(
            verified=True, name=name, dob=dob, doc_country=country,
            lived_in=lived, date=date)
    return NoteFacts(lived_in=lived, date=date)


def _has_failure(text):
    if _HARD_FAILURE.search(text):
        return True
    for match in _SOFT_FAILURE.finditer(text):
        window = text[max(0, match.start() - 40):match.start()]
        if _NEGATED.search(window):
            continue
        return True
    return False


def _text_and_date(note):
    if isinstance(note, str):
        return note, None
    if not isinstance(note, dict):
        return "", None
    text = "" if note.get("text") is None else str(note.get("text"))
    created = note.get("created_at")
    if created is None or not str(created).strip():
        return text, None
    return text, str(created).strip()


def _verification(text):
    names = []
    for match in _VERIFY_NAME.finditer(text):
        cleaned = " ".join(match.group("name").split()).strip(" .;,-")
        if cleaned and cleaned.casefold() not in [item.casefold() for item in names]:
            names.append(cleaned)
    if len(names) != 1:
        return None, None, None
    dobs = []
    for match in _DOB_CUE.finditer(text):
        parsed = _find_date(match.group(1))
        if parsed is None or parsed.year is None or parsed in dobs:
            continue
        dobs.append(parsed)
    countries = []
    for match in _DOC_COUNTRY.finditer(text):
        place = _clean_place(match.group(1))
        norm = _normalise(place) if place else None
        if norm and norm.casefold() not in [item.casefold() for item in countries]:
            countries.append(norm)
    dob = dobs[0] if len(dobs) == 1 else None
    country = countries[0] if len(countries) == 1 else None
    return names[0], dob, country


def _lived_in(text):
    found = []
    seen = []
    hits = []
    for pattern in _LIVED:
        for match in pattern.finditer(text):
            hits.append((match.start(), match.group(1)))
    hits.sort(key=lambda item: item[0])
    for _, fragment in hits:
        for piece in re.split(r"(?i)\s+to\s+", fragment.strip(), maxsplit=1):
            place = _clean_place(piece)
            norm = _normalise(place) if place else None
            if not norm or norm.casefold() in seen:
                continue
            seen.append(norm.casefold())
            found.append(norm)
    return found


def _clean_place(raw):
    text = " ".join(str(raw).split())
    text = re.split(r"(?i)\s+(?:until|before|after|during|while|in|on|from)\b", text, maxsplit=1)[0]
    text = re.sub(r"(?i)^(?:the|a)\s+", "", text).strip(" .;,-")
    words = text.split()
    if not words or len(words) > 6:
        return ""
    return " ".join(words)
