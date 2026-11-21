from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True, order=True)
class PartialDate:
    year: Optional[int] = None
    month: Optional[int] = None   # 1-12 or None if unknown
    day: Optional[int] = None     # 1-31 or None if unknown


@dataclass(frozen=True)
class Fact:
    value: object                 # str, PartialDate, ...
    source: str                   # record ID it came from: CUS-..., KYC-..., NOTE-..., SR-..., H-...
    kind: str = ""                # e.g. "full_name", "verified_name", "residence", "nationality", "doc_country", "lived_in"


@dataclass(frozen=True)
class BirthClaim:                 # one birth date the HIT gives
    years: Tuple[int, ...]        # possible years: (1973,) or (1973, 1974) from "aged 45 in March 2019"
    month: Optional[int]
    day: Optional[int]
    source: str                   # H-... (dobs or profile notes) or SR-...


@dataclass
class Person:                     # one real customer after merging records (SOP principle 3)
    person_id: str                # smallest record_id in the group (deterministic)
    record_ids: List[str]         # sorted
    entity_type: str              # "Individual" or "Company"
    names: List[Fact] = field(default_factory=list)       # full, preferred, login names from records
    verified_name: Optional[Fact] = None                  # latest approved KYC check or onboarding note
    dobs: List[Fact] = field(default_factory=list)        # PartialDate values from records (declared)
    verified_dob: Optional[Fact] = None                   # latest approved check
    countries: List[Fact] = field(default_factory=list)   # normalised names: residence, nationality, doc country, lived-in places
    path: List[str] = field(default_factory=list)         # IDs followed to get here (ACC-, APP-, ...), for the README and debugging


@dataclass
class Resolution:                 # what the resolver returns for one alert
    people: List[Person]          # 0 = nobody found, 1 = resolved, >1 = several people fit
    note: str = ""                # short human note: "joint account, screened dob picked CUS-...", "no link, 2 people fit"


@dataclass
class HitProfile:                 # one watchlist hit after fact extraction
    hit_id: str
    alert_id: str
    entity_type: str
    names: List[Fact] = field(default_factory=list)       # name + aliases, source = hit_id
    births: List[BirthClaim] = field(default_factory=list)
    countries: List[Fact] = field(default_factory=list)   # normalised; "International" / "Europe" dropped
    earliest_report: Optional[Fact] = None                # PartialDate of the earliest dated report
    deceased: Optional[Fact] = None                       # PartialDate
    incorporated: Optional[Fact] = None                   # companies only: PartialDate from dobs
    listing_kind: str = ""                                # "a sanctioned individual", "a politically exposed person", ...
    missing: List[str] = field(default_factory=list)      # known unknowns, e.g. "no date of birth in dobs, notes or search results"


@dataclass
class Decision:
    hit_id: str
    alert_id: str
    decision: str                 # DIFFERENT_ENTITY | SAME_ENTITY | REVIEW
    reason_code: str
    customer_record_id: Optional[str]   # record ID, "AMBIGUOUS", or None
    reason: str
    evidence: List[str]
