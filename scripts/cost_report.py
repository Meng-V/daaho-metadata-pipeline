#!/usr/bin/env python3
"""Cost report from a run's ledger: per image, per tier, per call type, plus a projection.

The ledger (out/cost_ledger.jsonl) records one row per billable API call, written as the run
proceeds. This script aggregates it three ways:

  1. PER IMAGE     -- exactly what each image cost, split by call type
  2. PER TIER      -- what each model tier cost in total, and its average per image
  3. PROJECTION    -- extrapolate a measured sample to a larger batch (e.g. 300 images)

Usage:
    python3 scripts/cost_report.py
    python3 scripts/cost_report.py --ledger out_v4/cost_ledger.jsonl
    python3 scripts/cost_report.py --project 300
    python3 scripts/cost_report.py --csv out_v4/cost_per_image.csv
    python3 scripts/cost_report.py --compare out/cost_ledger.jsonl

Note on OCR: Tesseract runs locally and costs nothing; it appears in the ledger as a `tesseract`
row with zero cost so the report can state that rather than leave it ambiguous. The billable
OCR path is `ocr_fallback` -- a vision transcription call made only when Tesseract returns almost
nothing.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.cost import PRICING_SOURCE, PRICING_VERIFIED_ON, TIERS, load_ledger  # noqa: E402

CALL_TYPES = ["extraction", "ocr_fallback", "tesseract"]


def aggregate(records):
    per_item = defaultdict(lambda: {"cost": 0.0, "calls": 0, "by_type": defaultdict(float),
                                    "tiers": set(), "in": 0, "cached": 0, "out": 0, "img": 0})
    per_tier = defaultdict(lambda: {"cost": 0.0, "calls": 0, "items": set(),
                                    "in": 0, "cached": 0, "out": 0})
    per_type = defaultdict(lambda: {"cost": 0.0, "calls": 0})
    estimated_pricing = False

    for row in records:
        item = row.get("item_id", "?")
        tier = row.get("tier", "?")
        call_type = row.get("call_type", "?")
        cost = float(row.get("cost_total") or 0.0)
        estimated_pricing = estimated_pricing or bool(row.get("pricing_estimated"))

        entry = per_item[item]
        entry["cost"] += cost
        entry["by_type"][call_type] += cost
        entry["in"] += int(row.get("prompt_tokens") or 0)
        entry["cached"] += int(row.get("cached_tokens") or 0)
        entry["out"] += int(row.get("completion_tokens") or 0)
        entry["img"] += int(row.get("image_tokens") or 0)
        if tier != "free":
            entry["calls"] += 1
            entry["tiers"].add(tier)

        if tier != "free":
            bucket = per_tier[tier]
            bucket["cost"] += cost
            bucket["calls"] += 1
            bucket["items"].add(item)
            bucket["in"] += int(row.get("prompt_tokens") or 0)
            bucket["cached"] += int(row.get("cached_tokens") or 0)
            bucket["out"] += int(row.get("completion_tokens") or 0)

        per_type[call_type]["cost"] += cost
        per_type[call_type]["calls"] += 1

    return per_item, per_tier, per_type, estimated_pricing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default="out/cost_ledger.jsonl")
    parser.add_argument("--project", type=int, default=0, help="Project cost to this many images")
    parser.add_argument("--csv", default="", help="Write the per-image table to a CSV file")
    parser.add_argument("--compare", default="", help="Second ledger to compare totals against")
    args = parser.parse_args()

    records = load_ledger(args.ledger)
    if not records:
        sys.exit(f"no ledger records found at {args.ledger}\n"
                 "(a run writes this automatically unless --no-cost-ledger was passed)")

    per_item, per_tier, per_type, estimated = aggregate(records)
    total = sum(e["cost"] for e in per_item.values())
    n_items = len(per_item)

    print(f"ledger:  {args.ledger}")
    print(f"pricing: verified {PRICING_VERIFIED_ON} -- {PRICING_SOURCE}")
    if estimated:
        print("WARNING: some rows used estimated (non-official) pricing; totals are approximate.")
    print()

    # ---- 1. per image -----------------------------------------------------------------
    print("=" * 86)
    print("PER IMAGE")
    print("=" * 86)
    header = f"{'item':18} {'tier':7} {'extract':>9} {'ocr_fb':>9} {'total':>10} {'in tok':>9} {'out tok':>8}"
    print(header)
    print("-" * 86)
    for item in sorted(per_item):
        entry = per_item[item]
        tiers = "/".join(sorted(entry["tiers"])) or "-"
        print(f"{item:18} {tiers:7} "
              f"{entry['by_type'].get('extraction', 0.0):>9.5f} "
              f"{entry['by_type'].get('ocr_fallback', 0.0):>9.5f} "
              f"{entry['cost']:>10.5f} "
              f"{entry['in']:>9,} {entry['out']:>8,}")
    print("-" * 86)
    avg = total / n_items if n_items else 0.0
    print(f"{'TOTAL':18} {'':7} {'':>9} {'':>9} {total:>10.5f}   over {n_items} images")
    print(f"{'AVG / IMAGE':18} {'':7} {'':>9} {'':>9} {avg:>10.5f}")

    # ---- 2. per tier ------------------------------------------------------------------
    print()
    print("=" * 86)
    print("PER TIER")
    print("=" * 86)
    print(f"{'tier':8} {'model':18} {'items':>6} {'calls':>6} {'cost':>10} {'avg/item':>10}  intent")
    print("-" * 86)
    for tier_name in sorted(per_tier, key=lambda t: per_tier[t]["cost"], reverse=True):
        bucket = per_tier[tier_name]
        tier_def = TIERS.get(tier_name)
        model_id = tier_def.model_id if tier_def else "(legacy/unknown)"
        intent = tier_def.intent.split(".")[0] if tier_def else ""
        item_count = len(bucket["items"])
        print(f"{tier_name:8} {model_id:18} {item_count:>6} {bucket['calls']:>6} "
              f"{bucket['cost']:>10.5f} {bucket['cost'] / max(1, item_count):>10.5f}  {intent}")

    # ---- 3. per call type ------------------------------------------------------------
    print()
    print("=" * 86)
    print("PER CALL TYPE")
    print("=" * 86)
    for call_type in CALL_TYPES + [t for t in sorted(per_type) if t not in CALL_TYPES]:
        if call_type not in per_type:
            continue
        bucket = per_type[call_type]
        share = bucket["cost"] / total * 100 if total else 0.0
        label = {
            "extraction": "metadata + transcript (main vision call)",
            "ocr_fallback": "vision OCR fallback (billable)",
            "tesseract": "local OCR -- runs on this machine, no API cost",
        }.get(call_type, "")
        print(f"  {call_type:14} {bucket['calls']:>4} calls  ${bucket['cost']:>9.5f}  {share:>5.1f}%   {label}")

    # ---- 4. projection ----------------------------------------------------------------
    if args.project:
        print()
        print("=" * 86)
        print(f"PROJECTION TO {args.project} IMAGES  (linear from {n_items} measured)")
        print("=" * 86)
        print(f"  measured average per image:  ${avg:.5f}")
        print(f"  projected {args.project} images:        ${avg * args.project:.2f}")
        print()
        print("  Same volume at each tier, using this run's average token counts:")
        tok_in = sum(e["in"] for e in per_item.values()) / max(1, n_items)
        tok_cached = sum(e["cached"] for e in per_item.values()) / max(1, n_items)
        tok_out = sum(e["out"] for e in per_item.values()) / max(1, n_items)
        for name in ("luna", "terra", "sol"):
            tier_def = TIERS[name]
            per_image = (
                (tok_in - tok_cached) / 1_000_000 * tier_def.input_per_m
                + tok_cached / 1_000_000 * tier_def.cached_input_per_m
                + tok_out / 1_000_000 * tier_def.output_per_m
            )
            print(f"    {name:6} {tier_def.model_id:16} ${per_image:.5f}/image  ->  "
                  f"${per_image * args.project:>8.2f} for {args.project}")
        print()
        print("  Caveat: assumes the token profile of the measured sample. Handwritten and")
        print("  dense multi-column pages run longer, so a mixed 300-image batch will differ.")

    # ---- 5. compare -------------------------------------------------------------------
    if args.compare:
        other = load_ledger(args.compare)
        if other:
            other_items = aggregate(other)[0]
            other_total = sum(e["cost"] for e in other_items.values())
            other_avg = other_total / max(1, len(other_items))
            print()
            print("=" * 86)
            print("COMPARE")
            print("=" * 86)
            print(f"  {args.ledger:40} ${total:>9.5f}  ${avg:.5f}/image  ({n_items} images)")
            print(f"  {args.compare:40} ${other_total:>9.5f}  ${other_avg:.5f}/image  ({len(other_items)} images)")
            if other_avg:
                print(f"  delta per image: {(avg - other_avg) / other_avg * 100:+.1f}%")

    # ---- CSV -------------------------------------------------------------------------
    if args.csv:
        out_path = Path(args.csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["item_id", "tiers", "billable_calls", "cost_extraction_usd",
                             "cost_ocr_fallback_usd", "cost_total_usd", "input_tokens",
                             "cached_tokens", "output_tokens", "image_tokens"])
            for item in sorted(per_item):
                entry = per_item[item]
                writer.writerow([
                    item, "/".join(sorted(entry["tiers"])), entry["calls"],
                    f"{entry['by_type'].get('extraction', 0.0):.6f}",
                    f"{entry['by_type'].get('ocr_fallback', 0.0):.6f}",
                    f"{entry['cost']:.6f}",
                    entry["in"], entry["cached"], entry["out"], entry["img"],
                ])
            writer.writerow([])
            writer.writerow(["TOTAL", "", "", "", "", f"{total:.6f}"])
            writer.writerow(["AVG_PER_IMAGE", "", "", "", "", f"{avg:.6f}"])
        print(f"\nwrote per-image CSV: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
