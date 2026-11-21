"""Module A loader: load(folder) -> Data (contract in docs/track2/PLAN.md section 5A).

Reads each table from the given folder only: `<name>.jsonl`, else `<name>.json`.
A file may be JSON Lines or one JSON array of rows (or an object wrapping one
list of rows). A UTF-8 BOM, blank lines and malformed lines are skipped
silently; a missing or unreadable file gives empty indexes. Rows stay raw
dicts exactly as read. Index keys are strings (numbers are turned into text),
and every list in every index is sorted by the row's own ID (stable, so file
order breaks ties) so iteration is deterministic. Standard library only.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional


def _text(v: Any) -> str:
    """Value as stripped text; whole floats lose '.0' (123.0 -> '123')."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        if v.is_integer():
            return str(int(v))
    if isinstance(v, (dict, list, tuple)):
        return ""
    return str(v).strip()


def as_list(v: Any) -> List[str]:
    """None -> []; list -> non-empty stripped strings; string -> split on ';'.

    Numbers become one-item lists of their text; nested lists are flattened.
    """
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        out: List[str] = []
        for x in v:
            if isinstance(x, (list, tuple)):
                out.extend(as_list(x))
            else:
                s = _text(x)
                if s:
                    out.append(s)
        return out
    if isinstance(v, str):
        return [s.strip() for s in v.split(";") if s.strip()]
    s = _text(v)
    return [s] if s else []


def digits(s: Any) -> str:
    """Keep only ASCII 0-9 ('+44 7700 900123' -> '447700900123'; 447700900123.0 too)."""
    return "".join(ch for ch in _text(s) if "0" <= ch <= "9")


_key = _text


def _low(v: Any) -> str:
    return _text(v).lower()


class Data:
    def __init__(self, folder: str) -> None:
        self.folder: str = folder
        self.customers: Dict[str, dict] = {}
        self.customers_by_email: Dict[str, List[str]] = {}
        self.customers_by_phone: Dict[str, List[str]] = {}
        self.accounts_by_id: Dict[str, List[dict]] = {}
        self.accounts_by_login: Dict[str, List[dict]] = {}
        self.accounts_by_customer: Dict[str, List[dict]] = {}
        self.onboarding_by_customer: Dict[str, List[dict]] = {}
        self.kyc_by_applicant: Dict[str, List[dict]] = {}
        self.kyc_by_docnum: Dict[str, List[dict]] = {}
        self.notes_by_email: Dict[str, List[dict]] = {}
        self.search_by_query: Dict[str, List[dict]] = {}
        self.hits: Dict[str, dict] = {}
        self.alerts: Dict[str, dict] = {}
        self.name_variants: Optional[Any] = None


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _rows_from(obj: Any) -> Optional[List[dict]]:
    """Rows from a parsed whole-file JSON value, or None if it is not a table."""
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        # {"rows": [{...}, ...]}: an object whose only value is the list of rows
        if len(obj) == 1:
            only = next(iter(obj.values()))
            if isinstance(only, list) and only and all(isinstance(r, dict) for r in only):
                return list(only)
        return [obj]  # a single row (one-line JSONL or a pretty-printed object)
    return None


def _parse_rows(text: str) -> List[dict]:
    body = text.strip()
    if body.startswith("[") or body.startswith("{"):
        # whole-file JSON first; multi-line JSONL fails here ("extra data") and is read per line
        try:
            rows = _rows_from(json.loads(body))
            if rows is not None:
                return rows
        except ValueError:
            pass
    rows: List[dict] = []
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff").rstrip(",")
        if not line or line in ("[", "]"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _table_path(folder: str, name: str) -> Optional[str]:
    for ext in (".jsonl", ".json"):
        path = os.path.join(folder, name + ext)
        if os.path.isfile(path):
            return path
    return None


def _read_table(folder: str, name: str) -> List[dict]:
    path = _table_path(folder, name)
    if path is None:
        return []
    text = _read_text(path)
    return _parse_rows(text) if text else []


def _index(rows: Iterable[dict], key: Callable[[dict], str]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for r in rows:
        k = key(r)
        if k:
            out.setdefault(k, []).append(r)
    return out


def _sort_lists(index: Dict[str, list], sort_key: Optional[Callable] = None) -> Dict[str, list]:
    return {k: sorted(v, key=sort_key) for k, v in sorted(index.items())}


def _by_id(rows: List[dict], id_field: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: _key(r.get(id_field))):
        k = _key(r.get(id_field))
        if k and k not in out:  # first row (in file order) wins on a duplicate ID
            out[k] = r
    return out


def _load_name_variants(folder: str) -> Optional[Any]:
    """Parsed name_variants.json (dict or list, any shape names.use_variants accepts) or None."""
    path = os.path.join(folder, "name_variants.json")
    if not os.path.isfile(path):
        return None
    text = _read_text(path)
    if not text or not text.strip():
        return None
    try:
        nv = json.loads(text)
    except ValueError:
        return None
    if isinstance(nv, (dict, list)) and nv:
        return nv
    return None


def load(folder: str) -> Data:
    d = Data(folder)

    customers = _read_table(folder, "customers")
    d.customers = _by_id(customers, "record_id")
    by_email: Dict[str, set] = {}
    by_phone: Dict[str, set] = {}
    for rid, r in d.customers.items():
        e = _low(r.get("email"))
        if e:
            by_email.setdefault(e, set()).add(rid)
        p = digits(r.get("phone"))
        if p:
            by_phone.setdefault(p, set()).add(rid)
    d.customers_by_email = {k: sorted(v) for k, v in sorted(by_email.items())}
    d.customers_by_phone = {k: sorted(v) for k, v in sorted(by_phone.items())}

    acc_sort = lambda r: (_key(r.get("account_id")), _key(r.get("customer_id")), _key(r.get("login_handle")))
    accounts = _read_table(folder, "accounts")
    d.accounts_by_id = _sort_lists(_index(accounts, lambda r: _key(r.get("account_id"))), acc_sort)
    d.accounts_by_login = _sort_lists(_index(accounts, lambda r: _low(r.get("login_handle"))), acc_sort)
    d.accounts_by_customer = _sort_lists(_index(accounts, lambda r: _key(r.get("customer_id"))), acc_sort)

    onboarding = _read_table(folder, "onboarding")
    d.onboarding_by_customer = _sort_lists(
        _index(onboarding, lambda r: _key(r.get("customer_id"))),
        lambda r: (_key(r.get("account_id")), _key(r.get("kyc_applicant_id")), _key(r.get("onboarded_at"))),
    )

    kyc_sort = lambda r: _key(r.get("check_id"))
    kyc = _read_table(folder, "kyc_checks")
    d.kyc_by_applicant = _sort_lists(_index(kyc, lambda r: _key(r.get("applicant_id"))), kyc_sort)
    approved = [r for r in kyc if _low(r.get("result")) == "approved"]
    d.kyc_by_docnum = _sort_lists(_index(approved, lambda r: _key(r.get("document_number")).upper()), kyc_sort)

    notes = _read_table(folder, "notes")
    d.notes_by_email = _sort_lists(
        _index(notes, lambda r: _low(r.get("requester_email"))), lambda r: _key(r.get("note_id"))
    )

    search = _read_table(folder, "search_results")
    d.search_by_query = _sort_lists(
        _index(search, lambda r: _low(r.get("query"))), lambda r: _key(r.get("result_id"))
    )

    d.hits = _by_id(_read_table(folder, "hits"), "hit_id")
    d.alerts = _by_id(_read_table(folder, "alerts"), "alert_id")
    d.name_variants = _load_name_variants(folder)
    return d