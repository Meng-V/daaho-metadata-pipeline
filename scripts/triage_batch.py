#!/usr/bin/env python3
"""Local, free triage of an image batch before spending anything on it.

Answers the questions that decide scope and cost, using no API calls:

  1. How many ARCHIVAL ITEMS are in here?  Filenames group multiple images into one item
     (Page_1..Page_N, Recto/Verso, a sequence-numbered bound volume), and the pipeline currently
     treats every file as an independent item -- which would give one 36-page volume 36 separate
     titles, dates and creators.
  2. Which files are already processed, so a run would re-bill them?
  3. Which files exceed the 15 MP cap and will be downscaled (docs/DECISIONS.md D-009a)?
  4. Are there duplicates, or files that are not readable images?
  5. What will this cost per tier, using the token profile measured on the pilot?

Usage:
    python3 scripts/triage_batch.py images/
    python3 scripts/triage_batch.py images/ --done-dir out_v4b --csv images_triage.csv
"""

import argparse
import csv
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.cost import TIERS  # noqa: E402
# Item grouping lives in one place. This script used to duplicate parse_name(), and the copy fell
# behind when letter-suffixed accession numbers (AAMU-0073a) were fixed -- it reported 130 items
# against the pipeline's 128.
from app.grouping import parse_name  # noqa: E402
from app.ocr import MAX_PIXELS  # noqa: E402

from PIL import Image  # noqa: E402

# Measured on the 19-image v4b run (out_v4b/cost_ledger.jsonl): mean tokens per image with the
# 15 MP cap and the OCR fallback off.
PILOT_INPUT_TOKENS = 19_478
PILOT_OUTPUT_TOKENS = 2_125

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("--done-dir", action="append", default=[],
                        help="Output dir(s) whose *.loc15.json count as already processed. Repeatable.")
    parser.add_argument("--csv", default="", help="Write the per-file table here")
    parser.add_argument("--max-pixels", type=int, default=MAX_PIXELS)
    args = parser.parse_args()

    files = sorted(p for p in args.image_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".gif", ".pdf"})
    others = sorted(p.name for p in args.image_dir.iterdir()
                    if p.is_file() and p not in files)
    if not files:
        sys.exit(f"no images found in {args.image_dir}")

    done = set()
    for directory in args.done_dir:
        for path in Path(directory).glob("*.loc15.json"):
            done.add(path.name.replace(".loc15.json", ""))

    rows, by_item, digests = [], defaultdict(list), defaultdict(list)
    unreadable = []
    for path in files:
        item_id, label, seq = parse_name(path.stem)
        try:
            with Image.open(path) as im:
                width, height = im.size
        except Exception as exc:
            unreadable.append((path.name, str(exc)))
            width = height = 0
        pixels = width * height
        digests[hashlib.md5(path.read_bytes()).hexdigest()].append(path.name)
        row = {
            "file": path.name, "item_id": item_id, "label": label, "sequence": seq,
            "width": width, "height": height, "megapixels": round(pixels / 1e6, 1),
            "downscaled": pixels > args.max_pixels,
            "already_processed": path.stem in done,
            "size_mb": round(path.stat().st_size / 1048576, 2),
        }
        rows.append(row)
        by_item[item_id].append(row)

    total = len(rows)
    processed = sum(1 for r in rows if r["already_processed"])
    pending = total - processed
    downscaled = sum(1 for r in rows if r["downscaled"])
    multi = {k: v for k, v in by_item.items() if len(v) > 1}

    print(f"batch: {args.image_dir}   {total} image files")
    if others:
        print(f"  non-image files ignored: {', '.join(others[:6])}"
              + (f" (+{len(others) - 6} more)" if len(others) > 6 else ""))
    if unreadable:
        print(f"\n  UNREADABLE ({len(unreadable)}):")
        for name, err in unreadable:
            print(f"    {name}: {err[:70]}")

    print(f"\n{'=' * 78}\nARCHIVAL ITEMS vs IMAGE FILES\n{'=' * 78}")
    print(f"  image files                {total:>5}")
    print(f"  distinct archival items    {len(by_item):>5}   <-- what a catalog record should describe")
    print(f"  items spanning >1 file     {len(multi):>5}")
    print(f"  files inside those items   {sum(len(v) for v in multi.values()):>5}")
    print("\n  Largest multi-file items:")
    for item_id, group in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:8]:
        labels = sorted({re.sub(r'\d+', 'N', r['label']) for r in group})
        print(f"    {item_id:14} {len(group):>3} files   {', '.join(labels[:3])}")

    print(f"\n{'=' * 78}\nWORK REMAINING\n{'=' * 78}")
    print(f"  already processed          {processed:>5}   (found in {', '.join(args.done_dir) or 'nothing'})")
    print(f"  pending                    {pending:>5}")

    print(f"\n{'=' * 78}\nIMAGE SIZES  (cap {args.max_pixels / 1e6:.0f} MP -> D-009a)\n{'=' * 78}")
    mps = sorted(r["megapixels"] for r in rows if r["megapixels"])
    if mps:
        print(f"  min {mps[0]:.1f} MP   median {mps[len(mps) // 2]:.1f} MP   max {mps[-1]:.1f} MP")
    print(f"  will be downscaled         {downscaled:>5}  ({downscaled / total:.0%})")

    dupes = {d: names for d, names in digests.items() if len(names) > 1}
    if dupes:
        print(f"\n  DUPLICATE CONTENT ({len(dupes)} groups):")
        for names in list(dupes.values())[:6]:
            print(f"    {' == '.join(names)}")

    print(f"\n{'=' * 78}\nCOST FOR {pending} PENDING FILES\n{'=' * 78}")
    print(f"  (token profile measured on the pilot: {PILOT_INPUT_TOKENS:,} in / {PILOT_OUTPUT_TOKENS:,} out per image)")
    for name in ("luna", "terra", "sol"):
        tier = TIERS[name]
        per_image = (PILOT_INPUT_TOKENS / 1e6 * tier.input_per_m
                     + PILOT_OUTPUT_TOKENS / 1e6 * tier.output_per_m)
        print(f"    {name:6} {tier.model_id:16} ${per_image:.4f}/image  ->  ${per_image * pending:>7.2f}")
    print("\n  Caveat: the pilot was single-sheet correspondence. Bound-volume pages and dense")
    print("  multi-column layouts run longer, so treat these as a floor.")

    if args.csv:
        out = Path(args.csv)
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote per-file table: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
