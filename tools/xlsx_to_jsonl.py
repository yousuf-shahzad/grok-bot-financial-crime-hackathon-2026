#!/usr/bin/env python3
"""Convert the Track 2 browse workbook into JSON Lines, one file per sheet.

Standard library only. Reads the workbook you downloaded, writes into an output
folder (default data/dev/). Both live in gitignored folders: never commit them.

    python tools/xlsx_to_jsonl.py data/ScreeningDevSet-browse.xlsx data/dev

IMPORTANT: this is an APPROXIMATION of the real dev/ JSON Lines files. The workbook
flattens lists to "a; b; c", cuts long text at 32,000 characters and turns empty
values into blanks. Values here are kept as plain strings (blank -> null). Use the
official dev/ files from the event data room as the source of truth when you have them.
"""
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
M = "{%s}" % NS["m"]
DATA_SHEETS = {
    "Alerts": "alerts", "Hits": "hits", "Customers": "customers", "Accounts": "accounts",
    "Onboarding": "onboarding", "KYC checks": "kyc_checks", "Notes": "notes",
    "Search results": "search_results", "Practice labels": "practice_labels",
}
TEXT_SHEETS = {"Start here": "start_here.txt", "Policy": "policy_sheet.txt"}


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def open_book(path):
    z = zipfile.ZipFile(path)
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.parse(z.open("xl/sharedStrings.xml")).getroot().findall("m:si", NS):
            strings.append("".join(t.text or "" for t in si.iter(M + "t")))
    wb = ET.parse(z.open("xl/workbook.xml")).getroot()
    rels = {r.get("Id"): r.get("Target") for r in ET.parse(z.open("xl/_rels/workbook.xml.rels")).getroot()}
    sheets = {}
    for s in wb.find("m:sheets", NS):
        target = rels[s.get("{%s}id" % NS["r"])].lstrip("/")
        sheets[s.get("name")] = target if target.startswith("xl/") else "xl/" + target
    return z, strings, sheets


def iter_rows(z, strings, target):
    """Yield each row as a list of cell strings (None for empty cells)."""
    for _, row in ET.iterparse(z.open(target), events=("end",)):
        if row.tag != M + "row":
            continue
        cells = {}
        for c in row.findall("m:c", NS):
            v = c.find("m:v", NS)
            t = c.get("t")
            if t == "s" and v is not None:
                val = strings[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(M + "t"))
            else:
                val = v.text if v is not None else None
            if val == "":
                val = None
            cells[col_index(c.get("r"))] = val
        row.clear()
        if cells:
            yield [cells.get(i) for i in range(max(cells) + 1)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("data", "dev")
    os.makedirs(out, exist_ok=True)
    z, strings, sheets = open_book(src)
    for sheet, stem in DATA_SHEETS.items():
        rows = iter_rows(z, strings, sheets[sheet])
        header = next(rows)
        n = 0
        with open(os.path.join(out, stem + ".jsonl"), "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                if not any(v is not None for v in r):
                    continue
                r = r + [None] * (len(header) - len(r))
                f.write(json.dumps(dict(zip(header, r)), ensure_ascii=False) + "\n")
                n += 1
        print("%-16s %7d rows -> %s.jsonl" % (sheet, n, stem))
    for sheet, fname in TEXT_SHEETS.items():
        with open(os.path.join(out, fname), "w", encoding="utf-8", newline="\n") as f:
            for r in iter_rows(z, strings, sheets[sheet]):
                f.write("\t".join(v for v in r if v is not None) + "\n")
        print("%-16s -> %s" % (sheet, fname))


if __name__ == "__main__":
    main()
