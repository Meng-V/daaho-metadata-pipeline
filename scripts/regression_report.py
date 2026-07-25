#!/usr/bin/env python3
"""Score current pipeline output against the human review fixture.

The fixture (tests/fixtures/jinming_review_2026-04.json) is the only human verification this
collection has, and no further review passes are available. This script turns it into a
measurement: after any prompt or pipeline change, re-run the 19 pilot images and see which
findings are actually resolved.

Usage:
    python3 scripts/regression_report.py
    python3 scripts/regression_report.py --out-dir ./out --by-type

What it can and cannot decide
-----------------------------
AUTO-CHECKABLE  findings whose `correction` is a concrete string: the corrected text should be
                present in the field, and the flagged `ai_output` text should be gone.
NEEDS-HUMAN     `provenance_unverifiable` and `omission` findings, and any finding with no
                concrete correction. A machine cannot tell whether a value is now *justified*,
                only whether it changed.

So a clean AUTO run is necessary but not sufficient. Per docs/DECISIONS.md D-004, output still
needs human review before publication.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

FIXTURE = Path("tests/fixtures/jinming_review_2026-04.json")
NEEDS_HUMAN_TYPES = {"provenance_unverifiable", "omission"}


def distinguishing_tokens(ai_output: str, correction: str):
    """The words that actually differ between the AI text and the human correction.

    Findings were recorded against line-broken transcripts; the v4 prompt requires reflowing
    paragraphs, so whole-sentence matching fails even when the substantive fix landed. Comparing
    only the differing words survives reflow.

    Returns (wanted, unwanted): words present only in the correction, and only in the AI output.
    Bracket markers are kept, since [illegible]/[unclear] are often the whole point of a finding.
    """
    def words(text: str):
        return re.findall(r"\[[a-z ]+\]|[\w''-]+", (text or "").lower())

    ai_words, fix_words = words(ai_output), words(correction)
    ai_set, fix_set = set(ai_words), set(fix_words)
    wanted = [w for w in fix_words if w not in ai_set and len(w) > 2]
    unwanted = [w for w in ai_words if w not in fix_set and len(w) > 2]
    return wanted, unwanted


def field_text(metadata: dict, field: str) -> str:
    """Flatten a metadata field to searchable text. Handles the CSV/JSON field-name drift."""
    aliases = {"place": ["place", "location"], "location": ["place", "location"]}
    for name in aliases.get(field, [field]):
        if name in metadata:
            value = metadata[name]
            if isinstance(value, list):
                return "; ".join(str(v) for v in value)
            if value is not None:
                return str(value)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--by-type", action="store_true", help="Break results down by error_type")
    args = parser.parse_args()

    if not args.fixture.exists():
        sys.exit(f"fixture not found: {args.fixture}")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)

    resolved, still_present, ambiguous, needs_human = [], [], [], []
    superseded = deferred = no_review = 0
    by_type = Counter()
    missing_outputs = []

    for item in fixture["items"]:
        item_id = item["item_id"]
        if item.get("human_review") == "none":
            no_review += 1
        deferred += len(item.get("open_questions", []))

        path = out_dir / f"{item_id}.loc15.json"
        if not path.exists():
            if item["findings"]:
                missing_outputs.append(item_id)
            continue
        metadata = json.loads(path.read_text(encoding="utf-8")).get("metadata", {})

        for finding in item["findings"]:
            status = finding.get("status")
            if status == "superseded_by_decision":
                superseded += 1
                continue
            if status == "deferred_no_human_decision":
                deferred += 1
                continue

            error_type = finding.get("error_type", "?")
            by_type[error_type] += 1
            record = (item_id, finding["id"], error_type, finding["field"])

            correction = finding.get("correction")
            ai_output = finding.get("ai_output")
            text = field_text(metadata, finding["field"])

            if error_type in NEEDS_HUMAN_TYPES or not correction or len(correction) > 200:
                needs_human.append(record)
                continue

            # Fast path: the exact strings still match (no reflow interference).
            if correction in text and not (ai_output and ai_output in text):
                resolved.append(record)
                continue
            if ai_output and ai_output in text:
                still_present.append(record)
                continue

            # Reflow-tolerant path: check only the words that distinguish the two readings.
            wanted, unwanted = distinguishing_tokens(ai_output or "", correction)
            lowered = text.lower()
            if not wanted and not unwanted:
                ambiguous.append(record)
                continue
            got_fix = all(w in lowered for w in wanted) if wanted else False
            kept_old = any(w in lowered for w in unwanted) if unwanted else False
            if got_fix and not kept_old:
                resolved.append(record)
            elif kept_old and not got_fix:
                still_present.append(record)
            else:
                ambiguous.append(record)

    auto_total = len(resolved) + len(still_present) + len(ambiguous)
    print(f"fixture:  {args.fixture}")
    print(f"output:   {out_dir}")
    print(f"reviewer: {fixture['provenance']['reviewer'].split(',')[0]}")
    print()
    print(f"AUTO-CHECKABLE findings: {auto_total}")
    if auto_total:
        print(f"  resolved       {len(resolved):3}   ({len(resolved) / auto_total:.0%})")
        print(f"  still present  {len(still_present):3}")
        print(f"  ambiguous      {len(ambiguous):3}   (neither old nor corrected text found)")
    print(f"\nNEEDS-HUMAN findings:    {len(needs_human)}   (machine cannot decide; see D-004)")
    print(f"superseded by decision:  {superseded}")
    print(f"deferred, no decision:   {deferred}   (see D-005 -- must not count as passing)")
    print(f"items with no review:    {no_review}")
    if missing_outputs:
        print(f"\nMISSING OUTPUT for reviewed items: {', '.join(missing_outputs)}")

    if still_present:
        print(f"\n--- still present ({len(still_present)}) ---")
        for item_id, fid, etype, field in still_present:
            print(f"  {fid:9} {item_id:16} {field:15} {etype}")
    if ambiguous:
        print(f"\n--- ambiguous ({len(ambiguous)}) ---")
        for item_id, fid, etype, field in ambiguous:
            print(f"  {fid:9} {item_id:16} {field:15} {etype}")

    if args.by_type:
        print("\n--- open findings by error_type ---")
        for etype, count in by_type.most_common():
            print(f"  {count:3}  {etype}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
