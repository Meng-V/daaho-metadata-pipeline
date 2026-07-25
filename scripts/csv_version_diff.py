#!/usr/bin/env python3
"""Cell-level diff between two metadata CSV versions, keyed on Identifier.

Written to recover the BC-0688..BC-0713 diff that was promised to the review assistant in
April 2026 and never delivered. Both students have since departed; this makes the comparison
reproducible instead of depending on anyone's memory.

Usage:
    python3 scripts/csv_version_diff.py OLD.csv NEW.csv
    python3 scripts/csv_version_diff.py OLD.csv NEW.csv --fields Creator,Title,Location
    python3 scripts/csv_version_diff.py OLD.csv NEW.csv --max-width 60

Caveat: the sheet the review assistant actually used for BC-0688..BC-0713 (an Apr 21 Google
Sheet) is NOT in this repo. `final_metadata.csv` is an earlier January version. So this diff
shows pipeline drift between the versions that survive, not exactly what she saw.
"""

import argparse
import csv
import sys
from pathlib import Path

KEY = "Identifier"
# Long free-text fields are summarized rather than printed in full.
BULKY = {"Transcript", "Summary"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or KEY not in rows[0]:
        sys.exit(f"{path}: no '{KEY}' column found")
    return {(row.get(KEY) or "").strip(): row for row in rows if (row.get(KEY) or "").strip()}


def summarize(value: str, max_width: int) -> str:
    value = (value or "").replace("\n", "\\n").replace("\r", "")
    if not value:
        return "(empty)"
    if len(value) <= max_width:
        return value
    return f"{value[:max_width]}... [{len(value)} chars]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old_csv", type=Path)
    parser.add_argument("new_csv", type=Path)
    parser.add_argument("--fields", default="", help="Comma-separated field allowlist (default: all)")
    parser.add_argument("--max-width", type=int, default=48, help="Truncate values wider than this")
    args = parser.parse_args()

    old, new = load(args.old_csv), load(args.new_csv)
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))

    allowlist = [f.strip() for f in args.fields.split(",") if f.strip()]
    fields = allowlist or [f for f in (list(old.values())[0] or {}) if f != KEY]

    print(f"OLD: {args.old_csv}  ({len(old)} rows)")
    print(f"NEW: {args.new_csv}  ({len(new)} rows)")
    if only_old:
        print(f"\nRows only in OLD: {', '.join(only_old)}")
    if only_new:
        print(f"\nRows only in NEW: {', '.join(only_new)}")

    changed_cells = 0
    regressions = []   # had a value, now empty
    additions = []     # was empty, now has a value

    for item_id in sorted(set(old) & set(new)):
        deltas = []
        for field in fields:
            before, after = (old[item_id].get(field) or "").strip(), (new[item_id].get(field) or "").strip()
            if before == after:
                continue
            changed_cells += 1
            if before and not after:
                regressions.append((item_id, field, before))
            elif after and not before:
                additions.append((item_id, field))
            if field in BULKY:
                deltas.append(f"    {field}: changed ({len(before)} -> {len(after)} chars)")
            else:
                deltas.append(f"    {field}:")
                deltas.append(f"      OLD: {summarize(before, args.max_width)}")
                deltas.append(f"      NEW: {summarize(after, args.max_width)}")
        if deltas:
            print(f"\n{item_id}")
            print("\n".join(deltas))

    print(f"\n{'=' * 60}")
    print(f"changed cells: {changed_cells}")

    if regressions:
        print(f"\nREGRESSIONS -- value present in OLD, empty in NEW ({len(regressions)}):")
        for item_id, field, before in regressions:
            print(f"  {item_id:18} {field:16} lost: {summarize(before, args.max_width)}")

    if additions:
        print(f"\nNewly populated in NEW ({len(additions)}):")
        for item_id, field in additions:
            print(f"  {item_id:18} {field}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
