"""Raw file readers: CSV / JSON / XLSX -> uniform records.

Returns (records, total) where each record is a dict:
  {"row_number": int, "fields": list[str], "raw": str}
row_number is the 1-based file line (CSV) or item index+1 (JSON/XLSX sheet row).
Blank CSV lines are skipped entirely (not counted).
"""
import csv
import json
from pathlib import Path

from .rules import HEADER, N_COLS


def read_csv(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty file: no header row")
    records = []
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("empty file: no header row")
    if [h.strip() for h in header] != HEADER:
        raise ValueError(f"unexpected header: {header!r}")
    for lineno, row in enumerate(reader, start=2):
        if not row or all(c.strip() == "" for c in row):
            continue  # skip blank lines
        records.append({"row_number": lineno, "fields": list(row),
                        "raw": lines[lineno - 1]})
    return records


def read_json(path: Path):
    items = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(items, list):
        raise ValueError("JSON root must be an array of row objects")
    records = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"JSON item {i} is not an object")
        fields = [str(item.get(col, "") if item.get(col, "") is not None else "")
                  for col in HEADER]
        records.append({"row_number": i, "fields": fields,
                        "raw": json.dumps(item, ensure_ascii=False)})
    return records


def read_xlsx(path: Path):
    try:
        import openpyxl
    except ImportError as e:
        raise ValueError("xlsx support needs openpyxl installed") from e
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("empty workbook")
    header = [(c if c is not None else "") for c in rows[0]]
    if [str(h).strip() for h in header] != HEADER:
        raise ValueError(f"unexpected header: {header!r}")
    records = []
    for idx, row in enumerate(rows[1:], start=2):
        vals = [( "" if c is None else str(c)) for c in row]
        if all(v.strip() == "" for v in vals):
            continue
        records.append({"row_number": idx, "fields": vals,
                        "raw": "|".join(vals)})
    return records


def read_any(path: Path):
    suffix = path.suffix.lower()
    # Uploaded names look like <jobid>_<orig>; strip the job prefix for type sniff.
    name = path.name
    if "_" in name:
        name = name.split("_", 1)[1]
    low = name.lower()
    if low.endswith(".json") or suffix == ".json":
        return read_json(path)
    if low.endswith(".xlsx") or suffix == ".xlsx":
        return read_xlsx(path)
    return read_csv(path)
