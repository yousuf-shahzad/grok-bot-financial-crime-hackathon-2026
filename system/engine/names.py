"""SOP principle 8: name parts and name agreement. [C]

Public API (PLAN.md section 5C):
    parts(name, company=False) -> List[str]
    parts_match(a, b) -> bool
    names_agree(a, b, company=False) -> bool
    real_part_count(name, company=False) -> int
    variant_forms(part) -> List[str]   # active variant group members, for blocking
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
_variant_groups = []  # type: List[Tuple[str, ...]]
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

_CATEGORY_WORDS = frozenset([
    "variant", "variants", "group", "groups", "name", "names", "nickname", "nicknames", "given",
    "surname", "surnames", "first", "last", "alias", "aliases", "forename", "forenames", "family",
    "equivalents", "spellings", "transliterations", "individual", "individuals", "person", "people",
])
_LEGAL_WORDS = ("legal", "suffix", "company_form", "entity_form", "business_form")


def _is_legal_key(key: str) -> bool:
    k = key.lower()
    return any(w in k for w in _LEGAL_WORDS) or k in ("company", "companies", "forms")


def _is_label_key(key: str) -> bool:
    """A key that names a category or numbers a group, not a name in the group."""
    k = key.strip().lower()
    if not k or not any(ch.isalpha() for ch in k):
        return True
    words = [w for w in re.split(r"[^a-z]+", k) if w]
    return any(w in _CATEGORY_WORDS for w in words) or bool(re.fullmatch(r"(group|g)?[\s_-]*\d+", k))


def _split(s: str) -> List[str]:
    return [p.strip() for p in re.split(r"[,;|/]", s) if p.strip()]


def _atoms(v: object, depth: int = 0) -> List[str]:
    """Every string inside v (strings split on , ; | /), in order."""
    if depth > 6 or v is None or isinstance(v, bool):
        return []
    if isinstance(v, str):
        return _split(v)
    if isinstance(v, dict):
        out = []  # type: List[str]
        for k in sorted(v, key=lambda x: str(x)):
            out.extend(_atoms(v[k], depth + 1))
        return out
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            out.extend(_atoms(x, depth + 1))
        return out
    return []


def _is_flat_group(v: object) -> bool:
    """A list of plain names (no nested lists, no comma-joined strings) is ONE group."""
    return (isinstance(v, (list, tuple)) and len(v) > 0
            and all(isinstance(x, str) and not re.search(r"[,;|]", x) for x in v))


def _groups_in(obj: object, key: Optional[str] = None, depth: int = 0) -> List[List[str]]:
    """Variant groups from any plausible name_variants.json shape:
    list of lists, list of comma-joined strings, {name: [variants]},
    {group_id: [names]}, {category: <any of these>}, [{"names": [...]}, ...]."""
    if depth > 6 or obj is None or isinstance(obj, bool):
        return []
    if isinstance(obj, str):
        members = _split(obj)
        if key is not None and not _is_label_key(key):
            members = [key] + members
        return [members]
    if isinstance(obj, dict):
        for k in ("names", "variants", "members", "group", "forms"):
            if k in obj and _is_flat_group(obj[k]) and len(obj) <= 3:
                return [list(obj[k])]          # one group written as an object
        groups = []  # type: List[List[str]]
        for k in sorted(obj, key=lambda x: str(x)):
            ks = str(k)
            if _is_legal_key(ks):
                continue
            groups.extend(_groups_in(obj[k], ks, depth + 1))
        return groups
    if isinstance(obj, (list, tuple)):
        if key is not None and _is_flat_group(obj):
            members = list(obj)
            if not _is_label_key(key):
                members = [key] + members
            return [members]
        groups = []
        for g in obj:
            if isinstance(g, str):
                groups.append(_split(g))
            elif isinstance(g, (list, tuple)):
                groups.append(_atoms(g, depth + 1))
            elif isinstance(g, dict):
                groups.extend(_groups_in(g, None, depth + 1))
        return groups
    return []


def _clean_groups(groups: Iterable[Iterable[str]]) -> List[List[str]]:
    """Keep groups with at least two distinct real names."""
    out = []  # type: List[List[str]]
    for g in groups:
        keys = []  # type: List[str]
        for w in g:
            if not isinstance(w, str) or not any(ch.isalpha() for ch in w):
                continue
            k = _key(w)
            if k and k not in keys:
                keys.append(k)
        if len(keys) >= 2:
            out.append(keys)
    return out


def _legal_in(obj: object) -> List[str]:
    if not isinstance(obj, dict):
        return []
    out = []  # type: List[str]
    for k in sorted(obj, key=lambda x: str(x)):
        if _is_legal_key(str(k)):
            out.extend(_atoms(obj[k]))
    return [w for w in out if any(ch.isalpha() for ch in w)]


def _build(groups: Iterable[Iterable[str]], legal: Iterable[str]) -> None:
    global _variant_index, _legal_forms, _variant_groups
    index = {}  # type: Dict[str, set]
    members = []  # type: List[Tuple[str, ...]]
    for gid, group in enumerate(groups):
        keys = []  # type: List[str]
        for word in group:
            k = _key(word)
            if k:
                index.setdefault(k, set()).add(gid)
                if k not in keys:
                    keys.append(k)
        members.append(tuple(sorted(keys)))
    _variant_groups = members
    _variant_index = {k: frozenset(v) for k, v in index.items()}
    _legal_forms = frozenset(k for k in (_key(w) for w in legal) if k)
    _parts_cached.cache_clear()
    _match_cached.cache_clear()
    _agree_cached.cache_clear()


def use_variants(name_variants: Optional[object]) -> None:
    """Install name_variants.json (as parsed by load.py, Data.name_variants).

    Accepts a list of lists, a list of comma-joined strings, a dict of groups
    ({name: [variants]} or {id: [names]}), category dicts, and a dict with
    groups plus legal-form keys ("legal_forms", "company_suffixes", ...).
    Variant groups found in the file replace the built-in VARIANTS; legal forms
    found replace LEGAL_FORMS. Anything unrecognised or broken (no group with
    two real names) falls back to the built-in tables, never raises.
    """
    groups = []  # type: List[List[str]]
    legal = []   # type: List[str]
    if name_variants:
        try:
            groups = _clean_groups(_groups_in(name_variants))
            legal = _legal_in(name_variants)
        except Exception:  # unreadable shape: built-ins
            groups, legal = [], []
    _build(groups if groups else VARIANTS, legal if legal else LEGAL_FORMS)


def variant_forms(part: str) -> List[str]:
    """The part plus every member of every active variant group that lists it,
    normalised and sorted (for blocking indexes in resolve.py)."""
    k = _key(part or "")
    if not k:
        return []
    forms = {k}
    for gid in sorted(_variant_index.get(k, ())):
        forms.update(_variant_groups[gid])
    return sorted(forms)


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