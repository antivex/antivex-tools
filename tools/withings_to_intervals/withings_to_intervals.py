#!/usr/bin/env python3
"""Turn a Withings data export (weight and blood pressure) into intervals.icu wellness data.

Reads the export you download from Withings (the zip, the extracted folder or single CSV
files), keeps the last measurement of each day, and either prints it (default), writes a
clean CSV (--out) or sends it to intervals.icu (--send). Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

LB_PER_KG = 2.20462262185
BASE_URL = "https://intervals.icu/api/v1"
CHUNK_SIZE = 100  # days per request
OUT_FIELDS = ["data", "peso_kg", "grasso_pct", "sistolica", "diastolica", "battito"]
MAX_ZIP_MEMBER = 100 * 1024 * 1024


def _norm(name: str) -> str:
    return " ".join(name.replace("﻿", "").strip().lower().split())


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(text: str) -> tuple[str, str] | None:
    """Return (day, full timestamp) as ISO strings, or None if the text is not a date."""
    text = text.strip().strip('"')[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            when = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return when.date().isoformat(), when.isoformat()
    return None


def _find(header: dict[str, str], *needles: str) -> str | None:
    """First column whose normalised name contains all the needles."""
    for key, original in header.items():
        if all(n in key for n in needles):
            return original
    return None


def _mass(row: dict, column: str | None) -> float | None:
    """Value of a mass column in kg (the unit is read from the column name)."""
    if column is None:
        return None
    value = _number(row.get(column))
    if value is None:
        return None
    return value / LB_PER_KG if "lb" in _norm(column) else value


def read_weight(rows: list[dict]) -> dict[str, dict]:
    """Per-day last weight measurement: {day: {"when", "weight", "fat_pct"}}."""
    if not rows:
        return {}
    header = {_norm(k): k for k in rows[0] if k}
    date_col = _find(header, "date")
    weight_col = _find(header, "weight")
    fat_pct_col = _find(header, "fat", "%")
    fat_col = None if fat_pct_col else _find(header, "fat")
    if date_col is None or weight_col is None:
        return {}
    days: dict[str, dict] = {}
    for row in rows:
        parsed = _parse_date(row.get(date_col) or "")
        weight = _mass(row, weight_col)
        if parsed is None or weight is None or weight <= 0:
            continue
        day, when = parsed
        if day in days and days[day]["when"] > when:
            continue
        fat_pct = None
        if fat_pct_col is not None:
            fat_pct = _number(row.get(fat_pct_col))
        else:
            fat = _mass(row, fat_col)
            if fat is not None and fat > 0:
                fat_pct = fat / weight * 100
        days[day] = {"when": when, "weight": weight, "fat_pct": fat_pct}
    return days


def read_bp(rows: list[dict]) -> dict[str, dict]:
    """Per-day last blood pressure measurement: {day: {"when", "systolic", "diastolic", "hr"}}."""
    if not rows:
        return {}
    header = {_norm(k): k for k in rows[0] if k}
    date_col = _find(header, "date")
    sys_col = _find(header, "systolic")
    dia_col = _find(header, "diastolic")
    hr_col = _find(header, "heart") or _find(header, "pulse")
    if date_col is None or sys_col is None or dia_col is None:
        return {}
    days: dict[str, dict] = {}
    for row in rows:
        parsed = _parse_date(row.get(date_col) or "")
        systolic = _number(row.get(sys_col))
        diastolic = _number(row.get(dia_col))
        if parsed is None or systolic is None or diastolic is None:
            continue
        day, when = parsed
        if day in days and days[day]["when"] > when:
            continue
        days[day] = {
            "when": when,
            "systolic": systolic,
            "diastolic": diastolic,
            "hr": _number(row.get(hr_col)) if hr_col else None,
        }
    return days


def _csv_rows(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    rows = csv.DictReader(io.StringIO(text))
    return [r for r in rows if any((v or "").strip() for v in r.values() if isinstance(v, str))]


def _kind(name: str) -> str | None:
    base = os.path.basename(name).lower()
    if not base.endswith(".csv"):
        return None
    if "weight" in base:
        return "weight"
    if base.startswith("bp") or "blood" in base or "pressure" in base:
        return "bp"
    return None


def load_export(paths: list[str]) -> tuple[list[dict], list[dict]]:
    """Read weight and blood pressure rows from zips, folders and CSV files."""
    weight_rows: list[dict] = []
    bp_rows: list[dict] = []

    def add(name: str, data: bytes) -> None:
        kind = _kind(name)
        if kind == "weight":
            weight_rows.extend(_csv_rows(data))
        elif kind == "bp":
            bp_rows.extend(_csv_rows(data))

    for path in paths:
        if os.path.isdir(path):
            for folder, _dirs, files in os.walk(path):
                for name in sorted(files):
                    full = os.path.join(folder, name)
                    if name.lower().endswith(".zip"):
                        _add_zip(full, add)
                    else:
                        with open(full, "rb") as handle:
                            add(name, handle.read())
        elif path.lower().endswith(".zip"):
            _add_zip(path, add)
        else:
            with open(path, "rb") as handle:
                add(path, handle.read())
    return weight_rows, bp_rows


def _add_zip(path: str, add) -> None:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.is_dir() and info.file_size < MAX_ZIP_MEMBER:
                add(info.filename, archive.read(info))


def merge(weight: dict[str, dict], bp: dict[str, dict], since: str | None = None) -> list[dict]:
    """One record per day, sorted. Fields: date, weight, fat_pct, systolic, diastolic, hr."""
    records = []
    for day in sorted(set(weight) | set(bp)):
        if since and day < since:
            continue
        w = weight.get(day, {})
        b = bp.get(day, {})
        records.append(
            {
                "date": day,
                "weight": w.get("weight"),
                "fat_pct": w.get("fat_pct"),
                "systolic": b.get("systolic"),
                "diastolic": b.get("diastolic"),
                "hr": b.get("hr"),
            }
        )
    return records


def _round(value: float | None, digits: int) -> float | int | None:
    if value is None:
        return None
    value = round(value, digits)
    return int(value) if digits == 0 else value


def to_wellness(records: list[dict]) -> list[dict]:
    """intervals.icu wellness body. The pulse is left out: a pulse taken with the blood
    pressure cuff is not a resting heart rate, so we do not claim it is."""
    body = []
    for rec in records:
        item: dict = {"id": rec["date"]}
        if rec["weight"] is not None:
            item["weight"] = _round(rec["weight"], 2)
        if rec["fat_pct"] is not None:
            item["bodyFat"] = _round(rec["fat_pct"], 1)
        if rec["systolic"] is not None:
            item["systolic"] = _round(rec["systolic"], 0)
        if rec["diastolic"] is not None:
            item["diastolic"] = _round(rec["diastolic"], 0)
        if len(item) > 1:
            body.append(item)
    return body


def format_table(records: list[dict]) -> str:
    def cell(value, digits):
        return "-" if value is None else f"{value:.{digits}f}"

    lines = [f"{'date':<12}{'weight_kg':>10}{'fat_%':>8}{'sys':>6}{'dia':>6}{'pulse':>7}"]
    for rec in records:
        lines.append(
            f"{rec['date']:<12}{cell(rec['weight'], 1):>10}{cell(rec['fat_pct'], 1):>8}"
            f"{cell(rec['systolic'], 0):>6}{cell(rec['diastolic'], 0):>6}{cell(rec['hr'], 0):>7}"
        )
    return "\n".join(lines)


def write_csv(path: str, records: list[dict]) -> None:
    def blank(value):
        return "" if value is None else value

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUT_FIELDS)
        for rec in records:
            writer.writerow(
                [
                    rec["date"],
                    blank(_round(rec["weight"], 2)),
                    blank(_round(rec["fat_pct"], 1)),
                    blank(_round(rec["systolic"], 0)),
                    blank(_round(rec["diastolic"], 0)),
                    blank(_round(rec["hr"], 0)),
                ]
            )


def send_wellness(body: list[dict], athlete_id: str, api_key: str, put=None) -> int:
    """Send the records to intervals.icu, CHUNK_SIZE days per request. Returns requests made."""
    put = put or _http_put
    url = f"{BASE_URL}/athlete/{athlete_id}/wellness-bulk"
    requests = 0
    for i in range(0, len(body), CHUNK_SIZE):
        put(url, body[i : i + CHUNK_SIZE], api_key)
        requests += 1
    return requests


def _http_put(url: str, chunk: list[dict], api_key: str) -> None:
    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    request = urllib.request.Request(
        url,
        data=json.dumps(chunk).encode(),
        method="PUT",
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60):
            return
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise SystemExit(f"intervals.icu refused the request (HTTP {err.code}). Check the API key and athlete id.")
        if err.code == 404:
            raise SystemExit("intervals.icu athlete not found (HTTP 404). Check --athlete-id.")
        if err.code == 429:
            raise SystemExit("intervals.icu rate limit reached (HTTP 429). Try again later.")
        raise SystemExit(f"intervals.icu error HTTP {err.code}.")
    except urllib.error.URLError as err:
        raise SystemExit(f"Could not reach intervals.icu: {err.reason}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Turn a Withings export (weight, body fat, blood pressure) into intervals.icu wellness data. "
        "By default nothing is sent: it prints a table of what would be sent.",
    )
    parser.add_argument("export", nargs="+", help="Withings export: the .zip, the extracted folder, or weight.csv / bp.csv files")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="only days from this date on")
    parser.add_argument("--out", metavar="FILE", help="also write a clean CSV (date, kg, body fat %%, blood pressure, pulse)")
    parser.add_argument("--send", action="store_true", help="really send the data to intervals.icu (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="print the table and send nothing (this is the default)")
    parser.add_argument("--athlete-id", metavar="i12345", help="intervals.icu athlete id (needed with --send)")
    parser.add_argument("--api-key", help="intervals.icu API key; or set INTERVALS_API_KEY (never printed)")
    return parser


def main(argv: list[str] | None = None, put=None) -> int:
    args = build_parser().parse_args(argv)
    if args.since and _parse_date(args.since) is None:
        print("--since must look like 2026-10-01", file=sys.stderr)
        return 2
    if args.send and args.dry_run:
        print("Use either --send or --dry-run, not both.", file=sys.stderr)
        return 2
    api_key = args.api_key or os.environ.get("INTERVALS_API_KEY")
    if args.send and not (args.athlete_id and api_key):
        print("--send needs --athlete-id and an API key (--api-key or INTERVALS_API_KEY).", file=sys.stderr)
        return 2
    try:
        weight_rows, bp_rows = load_export(args.export)
    except (OSError, zipfile.BadZipFile) as err:
        print(f"Cannot read the export: {err}", file=sys.stderr)
        return 1
    records = merge(read_weight(weight_rows), read_bp(bp_rows), args.since)
    if not records:
        print(
            "No weight or blood pressure measurements found. Expected weight.csv and/or bp.csv from the Withings export.",
            file=sys.stderr,
        )
        return 1
    print(format_table(records))
    if args.out:
        write_csv(args.out, records)
        print(f"Clean CSV written to {args.out}")
    body = to_wellness(records)
    if args.send:
        count = send_wellness(body, args.athlete_id, api_key, put)
        print(f"Sent {len(body)} days to intervals.icu in {count} request(s).")
    else:
        print(f"Dry run: {len(body)} days would be sent. Nothing was sent. Add --send to upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
