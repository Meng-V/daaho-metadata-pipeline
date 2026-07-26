#!/usr/bin/env python3
"""Produce two reader-friendly cost CSVs to accompany a metadata handoff.

`scripts/cost_report.py` is the engineering view -- tokens, call types, tiers. This is the version
you send to a colleague: plain column names, one row per catalog record, and a summary that
separates what the delivered batch cost from what the whole effort cost including the runs that were
thrown away.

Usage:
    python3 scripts/cost_deliverable.py                       # defaults to out_batch
    python3 scripts/cost_deliverable.py --out-dir out_batch --all-ledgers "out*/cost_ledger.jsonl"
"""

import argparse
import csv
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.cost import PRICING_SOURCE, PRICING_VERIFIED_ON, TIERS, load_ledger  # noqa: E402

# Runs other than the delivered batch, with what each was for. Anything not listed still appears in
# the summary, just without a description.
RUN_NOTES = {
    "out": "Jan-Apr 2026 baseline (gpt-4o), produced before this effort - no cost recorded",
    "out_probe": "Single-image probe to measure real token cost before committing to a batch",
    "out_v4": "19 pilot images, first configuration (no image size cap, OCR fallback on)",
    "out_v4b": "19 pilot images, corrected configuration",
    "out_v4_sol": "Diagnosis: tested whether a stronger model fixed a fabricated transcript",
    "out_cap24": "Diagnosis: 24 megapixel image cap",
    "out_cap15": "Diagnosis: 15 megapixel image cap (the fix)",
    "out_fix": "Diagnosis: 15 megapixel cap with the OCR fallback disabled",
    "out_batch": "THE DELIVERED BATCH - 128 records covering 316 images",
}


def per_item_rows(out_dir: Path):
    ledger = defaultdict(lambda: {"cost": 0.0, "calls": 0, "tiers": set()})
    for row in load_ledger(str(out_dir / "cost_ledger.jsonl")):
        if row.get("tier") == "free":
            continue
        entry = ledger[row["item_id"]]
        entry["cost"] += float(row.get("cost_total") or 0.0)
        entry["calls"] += 1
        entry["tiers"].add(row.get("tier"))

    rows = []
    for path in sorted(out_dir.glob("*.loc15.json")):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        md, ctx = envelope.get("metadata", {}), envelope.get("context", {})
        record_id = path.name.replace(".loc15.json", "")
        item_id = ctx.get("item_id") or record_id
        entry = ledger.get(item_id, {"cost": 0.0, "calls": 0, "tiers": set()})
        confidence = (md.get("field_confidence") or {}).get("transcript")
        notes = ctx.get("policy_notes") or []
        rows.append({
            "Record ID": record_id,
            "Item": item_id,
            "Title": md.get("title") or "",
            "Images in item": ctx.get("page_count") or 1,
            "Model tier": "/".join(sorted(entry["tiers"])) or "-",
            "AI requests": entry["calls"],
            "Cost USD": f"{entry['cost']:.4f}",
            "Transcript confidence": "" if confidence is None else confidence,
            "Needs human review": "YES" if (confidence is not None and confidence < 70) else "",
            "Vocabulary terms rejected": "YES" if any(n.startswith("Rejected") for n in notes) else "",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=Path("out_batch"))
    parser.add_argument("--all-ledgers", default="out*/cost_ledger.jsonl",
                        help="Glob for every ledger to include in the project total")
    args = parser.parse_args()

    rows = per_item_rows(args.out_dir)
    if not rows:
        sys.exit(f"no records found in {args.out_dir}")

    item_csv = args.out_dir / "cost_per_item.csv"
    with item_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    delivered = sum(float(r["Cost USD"]) for r in rows)
    flagged = sum(1 for r in rows if r["Needs human review"])
    images = sum(int(r["Images in item"]) for r in rows)
    live_items = {r["Item"] for r in rows}

    # The ledger is append-only, so it still holds calls billed against item ids that no longer
    # exist -- work superseded when item grouping and output naming were corrected mid-effort.
    # Those rows are real spend but are not attributable to any delivered record, so they are
    # reported separately rather than folded in. Without this split the tier counts add up to more
    # records than the batch contains, and the totals do not reconcile.
    by_tier = defaultdict(lambda: {"cost": 0.0, "calls": 0, "items": set()})
    by_type = defaultdict(lambda: {"cost": 0.0, "calls": 0})
    superseded = 0.0
    superseded_calls = 0
    for row in load_ledger(str(args.out_dir / "cost_ledger.jsonl")):
        tier, call_type = row.get("tier"), row.get("call_type")
        cost = float(row.get("cost_total") or 0.0)
        if tier == "free":
            continue
        if row["item_id"] not in live_items:
            superseded += cost
            superseded_calls += 1
            continue
        by_type[call_type]["cost"] += cost
        by_type[call_type]["calls"] += 1
        by_tier[tier]["cost"] += cost
        by_tier[tier]["calls"] += 1
        by_tier[tier]["items"].add(row["item_id"])

    summary = [
        ["DAAHO AI metadata - cost summary", ""],
        ["Pricing verified", PRICING_VERIFIED_ON],
        ["Pricing source", PRICING_SOURCE],
        ["", ""],
        ["DELIVERED BATCH", ""],
        ["Catalog records", len(rows)],
        ["Images covered", images],
        ["Cost of the delivered records USD", f"{delivered:.2f}"],
        ["Average cost per record USD", f"{delivered / len(rows):.4f}"],
        ["Average cost per image USD", f"{delivered / images:.4f}"],
        ["Records flagged for human review", flagged],
        ["", ""],
        ["Superseded work in this batch USD", f"{superseded:.2f}",
         f"{superseded_calls} requests that were redone after two bugs were fixed mid-effort "
         f"(item grouping, output naming); real spend, but not attributable to a delivered record"],
        ["Batch total USD", f"{delivered + superseded:.2f}", "delivered + superseded"],
        ["", ""],
        ["BY MODEL TIER", "records", "AI requests", "cost USD", "avg per record", "used for"],
    ]
    for tier in ("luna", "terra", "sol"):
        if tier not in by_tier:
            continue
        bucket = by_tier[tier]
        count = len(bucket["items"])
        summary.append([
            TIERS[tier].model_id, count, bucket["calls"], f"{bucket['cost']:.2f}",
            f"{bucket['cost'] / max(1, count):.4f}", TIERS[tier].intent,
        ])
    both = sum(1 for r in rows if "/" in r["Model tier"])
    if both:
        # These record counts overlap, so they sum to more than the batch. Say so explicitly rather
        # than leave a reader to wonder why the columns do not add up.
        summary.append(["", "", "", "", "", (
            f"Record counts overlap: {both} handwritten items were run at terra first and then "
            f"re-run at sol, so they are billed in both rows. Their 'Model tier' column reads "
            f"'sol/terra'."
        )])

    summary += [["", ""], ["BY WORK TYPE", "requests", "cost USD", "note"]]
    labels = {
        "extraction": "Reading each item and generating its metadata and transcript",
        "ocr_fallback": "Extra transcription pass (disabled for this batch)",
        "tesseract": "Local OCR - runs on this machine, never billed",
    }
    for call_type in ("extraction", "ocr_fallback", "tesseract"):
        if call_type not in by_type:
            continue
        bucket = by_type[call_type]
        summary.append([call_type, bucket["calls"], f"{bucket['cost']:.2f}",
                        labels.get(call_type, "")])

    # Whole-effort total, including the runs that were superseded or thrown away.
    summary += [["", ""], ["ALL RUNS IN THIS EFFORT", "records", "cost USD", "what it was for"]]
    grand = 0.0
    for path in sorted(glob.glob(args.all_ledgers)):
        records = [r for r in load_ledger(path) if r.get("tier") != "free"]
        if not records:
            continue
        cost = sum(float(r.get("cost_total") or 0.0) for r in records)
        grand += cost
        name = Path(path).parent.name
        summary.append([name, len({r["item_id"] for r in records}), f"{cost:.2f}",
                        RUN_NOTES.get(name, "")])
    summary += [
        ["", ""],
        ["TOTAL SPENT, ALL RUNS", "", f"{grand:.2f}",
         "Includes diagnostic runs and superseded batches, not just the delivered records"],
    ]

    summary_csv = args.out_dir / "cost_summary.csv"
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(summary)

    print(f"wrote {item_csv}   ({len(rows)} records)")
    print(f"wrote {summary_csv}")
    print(f"\ndelivered batch ${delivered:.2f} | all runs ${grand:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
