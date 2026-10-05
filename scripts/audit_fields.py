#!/usr/bin/env python3
"""Count field-content defects in a directory of .loc15.json records. Read-only; no API calls.

Checks what app/field_validation.py enforces (docs/DECISIONS.md D-014): person-name values that are
not exactly one name, place stored as a semicolon-joined string, place tokens absent from the
approved FAST list, and model-supplied `type` values. Run it before and after
`python3 -m app.main --rebuild-from-existing` to see what a rebuild will change.

    python3 scripts/audit_fields.py --out-dir out_batch
    python3 scripts/audit_fields.py --out-dir out_batch --list
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.field_validation import summarize  # noqa: E402
from app.main import _load_controlled_list  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="./out_batch")
    parser.add_argument("--approved-places", default="./vocab/fast_places.txt")
    parser.add_argument("--list", action="store_true", help="Print every defect, not just counts")
    args = parser.parse_args()

    approved = _load_controlled_list(args.approved_places)
    files = sorted(Path(args.out_dir).glob("*.loc15.json"))
    if not files:
        sys.exit(f"no .loc15.json files in {args.out_dir}")

    name_problems, unapproved, types = [], Counter(), Counter()
    string_places = items_with_names = items_with_unapproved = 0
    pending_names = pending_places = 0
    for path in files:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        md, context = envelope.get("metadata", envelope), envelope.get("context", {})
        found = summarize(md, approved)
        item = path.name.replace(".loc15.json", "")
        name_problems += [(item, *problem) for problem in found["name_problems"]]
        items_with_names += bool(found["name_problems"])
        string_places += found["place_is_string"]
        unapproved.update(found["places_not_approved"])
        items_with_unapproved += bool(found["places_not_approved"])
        if found["type"]:
            types[found["type"]] += 1
        # Values already removed by validation and waiting in the review trail.
        pending_names += sum(len(v) for v in (context.get("rejected_names") or {}).values())
        pending_places += any(n.startswith("Place tokens absent") for n in context.get("policy_notes") or [])

    print(f"{len(files)} records in {args.out_dir}")
    print(f"  name values not exactly one name : {len(name_problems)} in {items_with_names} records")
    print(f"  place stored as a string         : {string_places}")
    print(f"  place tokens not in approved list: {sum(unapproved.values())} "
          f"({len(unapproved)} distinct) in {items_with_unapproved} records")
    print(f"  model-supplied type values       : {sum(types.values())} {dict(types) or ''}")
    print(f"  in review trail: {pending_names} rejected names; {pending_places} records with rejected places")
    if args.list:
        for item, field, value, problem in name_problems:
            print(f"  NAME  {item:20} {field:15} {problem}: {value}")
        for token, count in unapproved.most_common():
            print(f"  PLACE {token} x{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
