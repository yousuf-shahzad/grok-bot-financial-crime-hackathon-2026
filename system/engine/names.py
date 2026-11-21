"""SOP principle 8: name parts and name agreement. [C]

Public API (PLAN.md section 5C):
    parts(name, company=False) -> List[str]
    parts_match(a, b) -> bool
    names_agree(a, b, company=False) -> bool
    real_part_count(name, company=False) -> int
    use_variants(name_variants)        # Data.name_variants (parsed name_variants.json) or None
    names_contradict(verified, others, company=False) -> bool   # safe NAME_MISMATCH_VERIFIED test

Rules (SPEC.md section 5):
- Parts ignore case, accents, punctuation and anything in brackets. Single
  letters are initials, not parts. Placeholders (na, n/a, test, unknown, xxx,
  none, digits, ...) are not parts. For companies the legal forms are not parts.
  Each distinct part counts once.
- Two parts match when identical, listed in the same variant group, or within
  1 edit (shorter part 4 to 6 letters) or 2 edits (7+ letters). Parts under 4
  letters must be identical. Plain Levenshtein: a swap is 2 edits.
- Parts written together or apart ("abdulsalam" / "abdul salam") match as ONE part.
- Names agree when at least two parts match, or every part of the shorter name
  matches. A name with no real parts agrees with nothing (unknown, never a
  contradiction on its own: see names_contradict).

Standard library only, deterministic (no set iteration in results).
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Built-in tables (general knowledge; name_variants.json from the data folder
# replaces them when main/load passes it to use_variants()).
# ---------------------------------------------------------------------------

LEGAL_FORMS = [
    "ab", "ag", "as", "asa", "bv", "co", "company", "corp", "corporation", "gmbh",
    "inc", "kg", "limited", "llc", "llp", "lp", "ltd", "na", "nv", "oy", "oyj",
    "plc", "sa", "sarl", "sas", "se", "sf", "sl", "spa", "srl",
]

VARIANTS = [
    # Arabic and Turkic given names and transliterations
    ["muhammad", "mohammed", "mohammad", "mohamed", "muhammed", "mohamad", "mohamud",
     "mehmet", "mehmed", "muhamad", "mohd", "md"],
    ["ahmed", "ahmad", "ahmet", "ahmd"],
    ["abdul", "abdel", "abdal", "abd", "abdoul", "abdoul"],
    ["abdullah", "abdallah", "abdulla", "abdollah"],
    ["hussein", "husein", "hussain", "husain", "husayn", "hossein", "huseyin"],
    ["hassan", "hasan", "hasson"],
    ["hasanov", "hassanov"],
    ["yusuf", "yousuf", "yousef", "youssef", "yusef", "yosef", "yousif"],
    ["ibrahim", "ebrahim", "ibraheem", "brahim"],
    ["ismail", "ismael", "ismayil", "esmail"],
    ["khalid", "khaled", "halid"],
    ["mustafa", "mostafa", "moustafa", "mustapha"],
    ["mahmoud", "mahmud", "mahmood", "mehmood"],
    ["omar", "umar", "omer"],
    ["osama", "usama", "usamah"],
    ["said", "saeed", "sayed", "sayyid", "saied"],
    ["rashid", "rasheed", "rachid"],
    ["hamid", "hamed", "hameed"],
    ["jamal", "gamal", "jamaal"],
    ["karim", "kareem", "kareem"],
    ["nasser", "nasir", "naser", "nassir"],
    ["salah", "saleh", "salih"],
    ["suleiman", "sulaiman", "suleyman", "sulayman", "soliman"],
    ["walid", "waleed"],
    ["yasser", "yasir", "yaser"],
    ["fatima", "fatma", "fatimah"],
    ["aisha", "ayesha", "aysha", "aicha"],
    ["hussam", "hosam", "husam"],
    # Slavic given names and transliterations
    ["aleksandr", "alexander", "aleksander", "alexandre", "alessandro", "alejandro",
     "alex", "sasha", "sascha", "alexandr", "oleksandr"],
    ["alexandra", "aleksandra", "alex", "sasha", "sandra", "alessandra", "alejandra"],
    ["alexei", "aleksei", "alexey", "aleksey", "oleksiy", "oleksii"],
    ["dmitri", "dmitry", "dmitriy", "dimitri", "dimitry", "dmytro"],
    ["sergei", "sergey", "serguei", "serhiy", "serhii", "sergiy"],
    ["yevgeny", "evgeny", "evgeni", "yevgeni", "evgenii", "yevhen", "eugene"],
    ["yuri", "yury", "yuriy", "iurii", "jurij", "yurii"],
    ["vladimir", "volodymyr", "wladimir", "vova", "volodya"],
    ["nikolai", "nikolay", "mykola", "nicolai", "nikola"],
    ["mikhail", "mykhailo", "michail", "misha"],
    ["andrei", "andrey", "andriy", "andrii"],
    ["pyotr", "petr", "petro", "pavlo"],
    ["ivan", "ivano", "vanya"],
    ["igor", "ihor"],
    ["olga", "olha"],
    ["natalia", "natalya", "nataliya", "natasha", "natalie"],
    ["tatiana", "tatyana", "tetiana", "tanya"],
    ["yelena", "elena", "olena", "helen", "helena"],
    ["yekaterina", "ekaterina", "katerina", "kateryna", "katya"],
    # English and European given names with nicknames
    ["thomas", "tom", "tommy", "thom", "tomas", "tommaso"],
    ["william", "will", "bill", "billy", "willy", "liam", "wilhelm", "guillaume"],
    ["robert", "rob", "bob", "bobby", "robbie", "bert", "roberto"],
    ["richard", "rick", "ricky", "dick", "rich", "richie", "ricardo"],
    ["james", "jim", "jimmy", "jamie", "jaime", "diego"],
    ["john", "jon", "johnny", "jack", "jonny", "johann", "johannes", "juan", "jean",
     "giovanni", "ioannis", "jan", "sean", "shaun", "ian"],
    ["joseph", "joe", "joey", "jose", "giuseppe", "josef", "jozef", "yosef"],
    ["michael", "mike", "mick", "mickey", "michel", "miguel", "michele", "mikhail",
     "michal", "mikael"],
    ["christopher", "chris", "kristopher", "christoph", "cristobal", "kit"],
    ["charles", "charlie", "chuck", "carlos", "carlo", "karl", "carl"],
    ["edward", "ed", "eddie", "ted", "teddy", "ned", "eduardo", "edouard"],
    ["anthony", "tony", "antony", "antonio", "anton", "antoine"],
    ["daniel", "dan", "danny", "daniele"],
    ["david", "dave", "davey", "davide", "dawid"],
    ["nicholas", "nick", "nicky", "nicolas", "nikolaos", "niccolo", "nicola"],
    ["peter", "pete", "pierre", "pietro", "pedro", "piotr", "pyotr"],
    ["samuel", "sam", "sammy", "samuele"],
    ["stephen", "steven", "steve", "stefan", "stephan", "esteban", "stefano", "etienne"],
    ["andrew", "andy", "drew", "andreas", "andre", "andres", "andrea", "andrei"],
    ["benjamin", "ben", "benny", "benjy"],
    ["matthew", "matt", "matthias", "mathieu", "matteo", "mateo"],
    ["patrick", "pat", "paddy", "patricio"],
    ["francis", "frank", "francisco", "francois", "francesco", "franz", "paco"],
    ["henry", "harry", "hank", "henri", "heinrich", "enrique", "enrico"],
    ["george", "georgios", "jorge", "giorgio", "georg", "yuri"],
    ["paul", "paulo", "paolo", "pablo", "pavel"],
    ["jacob", "jake", "jakob", "yakov", "jacques", "giacomo"],
    ["gregory", "greg", "grigory", "gregor"],
    ["timothy", "tim", "timmy"],
    ["jonathan", "jon", "jonny", "johnathan"],
    ["elizabeth", "liz", "lizzie", "beth", "betty", "eliza", "elisabeth", "isabel",
     "elisa", "lisa", "elsa"],
    ["katherine", "catherine", "kathryn", "katharine", "kate", "katie", "kathy",
     "cathy", "catarina", "caterina", "katarina", "katrin"],
    ["margaret", "maggie", "meg", "peggy", "margarita", "marguerite", "greta"],
    ["jennifer", "jen", "jenny"],
    ["patricia", "pat", "patty", "trish", "tricia"],
    ["susan", "sue", "susie", "suzanne", "susanna"],
    ["deborah", "debra", "debbie", "deb"],
    ["rebecca", "becky", "becca"],
    ["victoria", "vicky", "tori", "viktoria"],
    ["maria", "mary", "marie", "mariya", "maryam", "miriam", "mariam"],
    ["anna", "ann", "anne", "annie", "hanna", "hannah", "ana"],
    ["joanna", "joanne", "jo", "johanna", "ioana"],
    ["sophia", "sofia", "sophie", "sofiya"],
    ["juliet", "julia", "julie", "giulia", "yulia", "yuliya"],
    # Chinese and other common transliteration pairs
    ["li", "lee"],
    ["zhou", "chow", "chou"],
    ["wang", "wong"],
    ["huang", "wong", "hwang"],
    ["chen", "chan", "tan"],
    ["zhang", "cheung", "chang"],
]

PLACEHOLDERS = frozenset([
    "na", "n/a", "nan", "test", "tests", "testing", "unknown", "unk", "xxx", "xx",
    "none", "null", "nil", "tbd", "tba", "dummy", "sample", "noname", "anonymous",
    "notapplicable", "notknown",
])

# Courtesy titles carry no identity. Dropping them for individuals is the safe
# direction: "Mr Smith" then has 1 real part and can never clear on name.
HONORIFICS = frozenset([
    "mr", "mrs", "ms", "mx", "miss", "mme", "mlle", "dr", "prof", "sir", "dame",
])

# Letters NFKD does not decompose into a base letter plus accent.
_FOLD = {
    "\u00df": "ss", "\u00e6": "ae", "\u0153": "oe", "\u00f8": "o", "\u0142": "l",
    "\u0111": "d", "\u00f0": "d", "\u00fe": "th", "\u0131": "i", "\u0127": "h",
    "\u0138": "k", "\u014b": "n", "\u0167": "t",
}
_APOSTROPHES = "'\u2019\u2018\u02bc\u02bb`\u00b4"
_BRACKETS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")
_UNCLOSED = re.compile(r"[(\[{].*$")
_MAX_JOIN = 3      # a part written together can cover up to 3 parts written apart
_MAX_PARTS = 16    # bitmask search bound; longer names keep their first parts

_variant_index = {}   # type: Dict[str, FrozenSet[int]]
_legal_forms = frozenset()  # type: FrozenSet[str]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _fold(text: str) -> str:
    """Lowercase, strip accents, fold special letters."""
    s = unicodedata.normalize("NFKD", text.lower())
    out = []
    for ch in s:
        if unicodedata.combining(ch):
            continue
        out.append(_FOLD.get(ch, ch))
    return "".join(out)


def _tokens(name: object) -> List[str]:
    """Raw lowercase tokens: accents, brackets and punctuation removed, in order."""
    if name is None:
        return []
    s = name if isinstance(name, str) else str(name)
    s = _fold(s)
    prev = None
    while prev != s:              # nested brackets, innermost first
        prev = s
        s = _BRACKETS.sub(" ", s)
    s = _UNCLOSED.sub(" ", s)     # "Name (alias" with no closing bracket
    for ch in _APOSTROPHES:       # O'Brien -> obrien
        s = s.replace(ch, "")
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return s.split()


def _is_placeholder(tok: str) -> bool:
    if tok in PLACEHOLDERS:
        return True
    if any(ch.isdigit() for ch in tok):
        return True
    if len(tok) >= 2 and set(tok) == {"x"}:
        return True
    return False


def _key(word: str) -> str:
    """Normalised single-string form of one variant or legal-form entry."""
    return "".join(_tokens(word))


@lru_cache(maxsize=200000)
def _parts_cached(name: str, company: bool) -> Tuple[str, ...]:
    seen = []
    for tok in _tokens(name):
        if len(tok) < 2:
            continue                      # initials
        if _is_placeholder(tok):
            continue
        if company and tok in _legal_forms:
            continue
        if not company and tok in HONORIFICS:
            continue
        if tok not in seen:
            seen.append(tok)
    return tuple(seen)


def parts(name: Optional[str], company: bool = False) -> List[str]:
    """Real name parts, lowercase and accent-free, distinct, in written order."""
    if name is None:
        return []
    if not isinstance(name, str):
        name = str(name)
    return list(_parts_cached(name, bool(company)))


def real_part_count(name: Optional[str], company: bool = False) -> int:
    """Number of real name parts. Individuals with fewer than 2 can be neither
    confirmed nor cleared on name."""
    return len(parts(name, company))


# ---------------------------------------------------------------------------
# Variant tables
# ---------------------------------------------------------------------------

def _as_groups(obj: object) -> List[List[str]]:
    """Accept the shapes name_variants.json might use: list of lists, list of
    comma-joined strings, dict name -> list, or dict group-id -> list."""
    groups = []  # type: List[List[str]]
    if isinstance(obj, dict):
        for k in sorted(obj, key=lambda x: str(x)):
            v = obj[k]
            members = _as_list(v)
            if not members:
                continue
            key = str(k)
            if not key.isdigit() and not key.lower().startswith("group"):
                members = [key] + members
            groups.append(members)
    elif isinstance(obj, (list, tuple)):
        for g in obj:
            members = _as_list(g)
            if members:
                groups.append(members)
    return groups


def _as_list(v: object) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [p.strip() for p in re.split(r"[,;|]", v) if p.strip()]
    if isinstance(v, dict):
        for key in ("names", "variants", "members", "group"):
            if key in v:
                return _as_list(v[key])
        return []
    if isinstance(v, (list, tuple)):
        out = []  # type: List[str]
        for x in v:
            out.extend(_as_list(x))
        return out
    return [str(v)]


def _build(groups: Iterable[Iterable[str]], legal: Iterable[str]) -> None:
    global _variant_index, _legal_forms
    index = {}  # type: Dict[str, set]
    for gid, group in enumerate(groups):
        for word in group:
            k = _key(word)
            if k:
                index.setdefault(k, set()).add(gid)
    _variant_index = {k: frozenset(v) for k, v in index.items()}
    _legal_forms = frozenset(k for k in (_key(w) for w in legal) if k)
    _parts_cached.cache_clear()
    _match_cached.cache_clear()
    _agree_cached.cache_clear()


def use_variants(name_variants: Optional[object]) -> None:
    """Install name_variants.json (as parsed by load.py, Data.name_variants).

    None or an unreadable shape keeps the built-in tables. Variant groups from
    the file replace the built-in VARIANTS; legal forms from the file replace
    LEGAL_FORMS when the file lists them.
    """
    if not name_variants:
        _build(VARIANTS, LEGAL_FORMS)
        return
    variants_obj = name_variants   # type: object
    legal_obj = None               # type: object
    if isinstance(name_variants, dict):
        lower = {str(k).lower(): k for k in name_variants}
        legal_key = next((lower[k] for k in sorted(lower) if "legal" in k or "company" in k
                          or "suffix" in k), None)
        var_key = next((lower[k] for k in sorted(lower) if "variant" in k or "group" in k
                        or k in ("names", "given_names", "nicknames")), None)
        if legal_key is not None:
            legal_obj = name_variants[legal_key]
        if var_key is not None:
            variants_obj = name_variants[var_key]
        elif legal_key is not None:
            variants_obj = {k: v for k, v in name_variants.items() if k != legal_key}
    groups = _as_groups(variants_obj)
    legal = _as_list(legal_obj) if legal_obj is not None else []
    _build(groups if groups else VARIANTS, legal if legal else LEGAL_FORMS)


# ---------------------------------------------------------------------------
# Part matching
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str, limit: int) -> int:
    """Plain Levenshtein (a swap is 2 edits); returns limit + 1 once over limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = i
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if cur[j] < best:
                best = cur[j]
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def _allowance(shorter_len: int) -> int:
    if shorter_len < 4:
        return 0
    if shorter_len <= 6:
        return 1
    return 2


@lru_cache(maxsize=500000)
def _match_cached(a: str, b: str) -> bool:
    if a == b:
        return True
    ga, gb = _variant_index.get(a), _variant_index.get(b)
    if ga and gb and not ga.isdisjoint(gb):
        return True
    limit = _allowance(min(len(a), len(b)))
    if limit == 0:
        return False
    return _levenshtein(a, b, limit) <= limit


def parts_match(a: str, b: str) -> bool:
    """Do two single name parts match (identical, variant group, or edit allowance)?"""
    ka, kb = _key(a or ""), _key(b or "")
    if not ka or not kb:
        return False
    if ka > kb:
        ka, kb = kb, ka
    return _match_cached(ka, kb)


# ---------------------------------------------------------------------------
# Name agreement
# ---------------------------------------------------------------------------

def _units(p: Tuple[str, ...]) -> List[Tuple[int, int, str]]:
    """(start, length, text) for every single part and every run of up to
    _MAX_JOIN adjacent parts written together."""
    out = []
    for i in range(len(p)):
        for k in range(1, _MAX_JOIN + 1):
            if i + k <= len(p):
                out.append((i, k, "".join(p[i:i + k])))
    return out


def _pm(a: str, b: str) -> bool:
    if a > b:
        a, b = b, a
    return _match_cached(a, b)


def _agree_parts(pa: Tuple[str, ...], pb: Tuple[str, ...]) -> bool:
    if not pa or not pb:
        return False
    pa, pb = pa[:_MAX_PARTS], pb[:_MAX_PARTS]
    na, nb = len(pa), len(pb)
    full_b = (1 << nb) - 1
    units_b = _units(pb)
    # Options at A position i: (len consumed in A, bitmask consumed in B).
    # One side is a single part; the other may be a run written together.
    options = []  # type: List[List[Tuple[int, int]]]
    for i in range(na):
        opts = []
        for ka in range(1, _MAX_JOIN + 1):
            if i + ka > na:
                break
            joined_a = "".join(pa[i:i + ka])
            for (j, kb, text_b) in units_b:
                if ka > 1 and kb > 1:
                    continue
                if _pm(joined_a, text_b):
                    opts.append((ka, ((1 << kb) - 1) << j))
        options.append(opts)

    memo = {}  # type: Dict[Tuple[int, int], FrozenSet[Tuple[int, bool, int]]]

    def search(i: int, used_b: int) -> FrozenSet[Tuple[int, bool, int]]:
        # outcomes: (matched units capped at 2, every A part covered, B mask used)
        key = (i, used_b)
        if key in memo:
            return memo[key]
        if i >= na:
            res = frozenset([(0, True, used_b)])
            memo[key] = res
            return res
        acc = set()
        for (c, _all, m) in search(i + 1, used_b):
            acc.add((c, False, m))
        for (ka, mask) in options[i]:
            if used_b & mask:
                continue
            for (c, all_a, m) in search(i + ka, used_b | mask):
                acc.add((min(c + 1, 2), all_a, m))
        res = frozenset(acc)
        memo[key] = res
        return res

    for (c, all_a, m) in search(0, 0):
        if c >= 2:
            return True
        if c >= 1 and na <= nb and all_a:
            return True
        if c >= 1 and nb <= na and m == full_b:
            return True
    return False


@lru_cache(maxsize=200000)
def _agree_cached(a: str, b: str, company: bool) -> bool:
    return _agree_parts(_parts_cached(a, company), _parts_cached(b, company))


def names_agree(a: Optional[str], b: Optional[str], company: bool = False) -> bool:
    """SOP names agree: at least two parts match, or every part of the shorter
    name matches. False when either side has no real parts (unknown)."""
    if a is None or b is None:
        return False
    a, b = str(a), str(b)
    if a > b:
        a, b = b, a
    return _agree_cached(a, b, bool(company))


def names_contradict(verified: Optional[str], others: Iterable[Optional[str]],
                     company: bool = False) -> bool:
    """Safe NAME_MISMATCH_VERIFIED test: True only when the verified name has at
    least 2 real parts, at least one other name has a real part, and the
    verified name agrees with none of them. Names with no real parts
    (placeholders, initials only) are unknown and are skipped, never mismatches."""
    if real_part_count(verified, company) < 2:
        return False
    usable = [o for o in others if real_part_count(o, company) >= 1]
    if not usable:
        return False
    return not any(names_agree(verified, o, company) for o in usable)


_build(VARIANTS, LEGAL_FORMS)