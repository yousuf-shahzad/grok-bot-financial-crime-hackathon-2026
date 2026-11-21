"""Module A loader: load(folder) -> Data (contract in docs/track2/PLAN.md section 5A).

Reads every *.jsonl in the given folder (a missing file gives empty indexes).
Rows stay raw dicts exactly as read. Every list in every index is sorted by the
row's own ID so iteration is deterministic. Standard library only.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional


def as_list(v: Any) -> List[str]:
    """None -> []; list -> non-empty stripped strings; string -> split on ';'."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = str(v).split(";")
    out = []
    for x in items:
        if x is None:
            continue
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def digits(s: Any) -> str:
    """Keep only ASCII 0-9 ('+44 7700 900123' -> '447700900123')."""
    if s is None:
        return ""
    return "".join(ch for ch in str(s) if "0" <= ch <= "9")


def _key(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _low(v: Any) -> str:
    return _key(v).lower()


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
        self.name_variants: Optional[dict] = None


def _read_jsonl(folder: str, name: str) -> List[dict]:
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        return []
    rows: List[dict] = []
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


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
        if k and k not in out:  # first row wins on a duplicate ID
            out[k] = r
    return out


def load(folder: str) -> Data:
    d = Data(folder)

    customers = _read_jsonl(folder, "customers.jsonl")
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
    accounts = _read_jsonl(folder, "accounts.jsonl")
    d.accounts_by_id = _sort_lists(_index(accounts, lambda r: _key(r.get("account_id"))), acc_sort)
    d.accounts_by_login = _sort_lists(_index(accounts, lambda r: _low(r.get("login_handle"))), acc_sort)
    d.accounts_by_customer = _sort_lists(_index(accounts, lambda r: _key(r.get("customer_id"))), acc_sort)

    onboarding = _read_jsonl(folder, "onboarding.jsonl")
    d.onboarding_by_customer = _sort_lists(
        _index(onboarding, lambda r: _key(r.get("customer_id"))),
        lambda r: (_key(r.get("account_id")), _key(r.get("kyc_applicant_id")), _key(r.get("onboarded_at"))),
    )

    kyc_sort = lambda r: _key(r.get("check_id"))
    kyc = _read_jsonl(folder, "kyc_checks.jsonl")
    d.kyc_by_applicant = _sort_lists(_index(kyc, lambda r: _key(r.get("applicant_id"))), kyc_sort)
    approved = [r for r in kyc if _low(r.get("result")) == "approved"]
    d.kyc_by_docnum = _sort_lists(_index(approved, lambda r: _key(r.get("document_number")).upper()), kyc_sort)

    notes = _read_jsonl(folder, "notes.jsonl")
    d.notes_by_email = _sort_lists(
        _index(notes, lambda r: _low(r.get("requester_email"))), lambda r: _key(r.get("note_id"))
    )

    search = _read_jsonl(folder, "search_results.jsonl")
    d.search_by_query = _sort_lists(
        _index(search, lambda r: _low(r.get("query"))), lambda r: _key(r.get("result_id"))
    )

    d.hits = _by_id(_read_jsonl(folder, "hits.jsonl"), "hit_id")
    d.alerts = _by_id(_read_jsonl(folder, "alerts.jsonl"), "alert_id")

    nv_path = os.path.join(folder, "name_variants.json")
    if os.path.isfile(nv_path):
        with open(nv_path, encoding="utf-8-sig") as fh:
            nv = json.load(fh)
        d.name_variants = nv

    return d