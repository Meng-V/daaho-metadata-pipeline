#!/usr/bin/env python3
"""Export JSON metadata files to CSV format matching the AAMU-BC Metadata Upload Spreadsheet."""

import json
import csv
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.ai_metadata import apply_review_overrides

def normalize_headers(headers: List[str]) -> List[str]:
    """Drop duplicate Identifier headers while preserving the upload order."""
    normalized = []
    seen_identifier = False
    for header in headers:
        if header == "Identifier":
            if seen_identifier:
                continue
            seen_identifier = True
        normalized.append(header)
    return normalized

def read_csv_headers(csv_path: str) -> List[str]:
    """Read the header row from the CSV to get exact column order."""
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader)
    return normalize_headers(headers)

def join_list(value: Any, separator: str = "; ") -> str:
    """Join list items with separator, or return empty string if None/empty."""
    if not value:
        return ""
    if isinstance(value, list):
        # Filter out None and empty strings
        items = [str(item).strip() for item in value if item]
        return separator.join(items) if items else ""
    return str(value).strip()

def convert_digitized(value: Any) -> str:
    """Convert digitized boolean to 'Yes' or empty string."""
    if value is True or (isinstance(value, str) and value.lower() in ['true', 'yes', '1']):
        return "Yes"
    return ""

def extract_decade(date_str: Optional[str]) -> str:
    """Extract decade from date string (e.g., '1938-10-27' -> '1930-1939')."""
    if not date_str or date_str == "undated":
        return ""
    try:
        year = int(date_str.split('-')[0])
        decade_start = (year // 10) * 10
        decade_end = decade_start + 9
        return f"{decade_start}-{decade_end}"
    except (ValueError, IndexError):
        return ""

def map_json_to_csv_row(json_data: Dict[str, Any], filename: str) -> Dict[str, str]:
    """Map JSON metadata to CSV row matching the spreadsheet format."""
    md = json_data.get("metadata", {})
    context = json_data.get("context", {})
    normalized_title = (context.get("title_derivation") or {}).get("normalized_title")
    
    # Get identifier - prefer identifier, fall back to digital_identifier, or use filename stem
    identifier = md.get("identifier") or md.get("digital_identifier") or Path(filename).stem
    identifier = identifier.replace(".loc15", "")
    
    row = {
        "Identifier": identifier,
        "Title": normalized_title or md.get("title") or "",
        "Series": md.get("series") or "",
        "Issue": "",  # Not in JSON schema
        "Creator": md.get("creator") or "",
        "Contributors": join_list(md.get("contributors")),
        "Correspondents": join_list(md.get("correspondents")),
        "Date": md.get("date") or "",
        "Publisher": md.get("publisher") or "",
        "Location": join_list(md.get("place")),
        "Summary": md.get("description") or "",
        "Extent": "",  # Not in JSON schema
        "Dimensions": "",  # Not in JSON schema
        "Subject (FAST)": join_list(md.get("subjects")),
        "Subject (People)": "",  # Not directly mapped in JSON
        "Subject (Local)": "",  # Not directly mapped in JSON
        "Decade": extract_decade(md.get("date")),
        "Theme": join_list(md.get("theme")),
        "Genre": join_list(md.get("genre")),
        "Type": md.get("type") or "",
        "Language": md.get("language") or "",
        "Repository": md.get("repository") or "",
        "Collection": md.get("collection") or "",
        "Folder": md.get("folder") or "",
        "Rights": md.get("rights") or "",
        "Digital Collection": md.get("digital_collection") or "",
        "Digital Publisher": md.get("digital_publisher") or "",
        "Digitized": convert_digitized(md.get("digitized")),
        "Transcript": md.get("transcript") or "",
        "Preservation Filename": Path(filename).stem.replace(".loc15", "") or "",
        "Object ID": "",  # Not in JSON schema
    }
    
    return row

def _load_review(out_dir: Path, base_name: str) -> Dict[str, Any]:
    review_path = out_dir / f"{base_name}.review.json"
    if not review_path.exists():
        return {}
    try:
        return json.loads(review_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="Export LOC15 JSON to CSV")
    ap.add_argument("--out-dir", default="out", help="Directory with .loc15.json files")
    ap.add_argument("--template", default=r"C:\Users\freew\Downloads\AAMU-BC Metadata Upload Spreadsheet - Full.csv", help="CSV template with headers")
    ap.add_argument("--output", default="final_metadata.csv", help="Output CSV path")
    ap.add_argument("--apply-reviews", action="store_true", help="Apply review overrides before export")
    ap.add_argument("--include-review-columns", action="store_true", help="Include review/provenance columns in CSV")
    args = ap.parse_args()

    # Paths
    out_dir = Path(args.out_dir)
    csv_template_path = Path(args.template)
    output_csv = Path(args.output)
    
    # Read CSV headers to get exact column order
    print(f"Reading headers from: {csv_template_path}")
    try:
        headers = read_csv_headers(str(csv_template_path))
    except FileNotFoundError:
        print(f"Error: CSV template not found at {csv_template_path}")
        print("Using default headers from schema...")
        headers = [
            "Identifier", "Title", "Series", "Issue", "Creator", "Contributors", "Correspondents",
            "Date", "Publisher", "Location", "Summary", "Extent", "Dimensions",
            "Subject (FAST)", "Subject (People)", "Subject (Local)", "Decade", "Theme", "Genre",
            "Type", "Language", "Repository", "Collection", "Folder", "Rights",
            "Digital Collection", "Digital Publisher", "Digitized", "Transcript",
            "Identifier", "Preservation Filename", "Object ID"
        ]
        headers = normalize_headers(headers)
    
    # Find all canonical LOC15 JSON files in out/ directory
    json_files = sorted([f for f in out_dir.glob("*.loc15.json") if not f.name.endswith(".raw.json")])
    
    if not json_files:
        print(f"Error: No JSON files found in {out_dir}")
        return
    
    print(f"Found {len(json_files)} JSON files to process")
    
    # Process each JSON file
    rows = []
    for json_file in json_files:
        print(f"Processing: {json_file.name}")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            if args.apply_reviews:
                review = _load_review(out_dir, json_file.stem.replace(".loc15", ""))
                if review:
                    md = json_data.get("metadata", {})
                    md, _ = apply_review_overrides(md, review)
                    json_data["metadata"] = md

            row = map_json_to_csv_row(json_data, json_file.name)

            if args.include_review_columns:
                review = _load_review(out_dir, json_file.stem.replace(".loc15", ""))
                row["Review Status"] = review.get("status", "")
                row["Reviewer"] = review.get("reviewer", "")
                row["Review Notes"] = review.get("notes", "")
                row["Review Timestamp"] = review.get("reviewed_at", "")
                row["AI-Proposed Subject (FAST)"] = join_list(json_data.get("metadata", {}).get("subjects"))
                row["AI-Proposed Genre"] = join_list(json_data.get("metadata", {}).get("genre"))
                row["AI-Proposed Creator"] = json_data.get("metadata", {}).get("creator") or ""
                row["AI-Proposed Publisher"] = json_data.get("metadata", {}).get("publisher") or ""
                row["AI-Proposed Theme"] = join_list(json_data.get("metadata", {}).get("theme"))
            rows.append(row)
        except Exception as e:
            print(f"  Error processing {json_file.name}: {e}")
            continue
    
    # Write CSV file
    print(f"\nWriting {len(rows)} rows to {output_csv}")
    if args.include_review_columns:
        extra_headers = [
            "Review Status",
            "Reviewer",
            "Review Notes",
            "Review Timestamp",
            "AI-Proposed Subject (FAST)",
            "AI-Proposed Genre",
            "AI-Proposed Creator",
            "AI-Proposed Publisher",
            "AI-Proposed Theme",
        ]
        headers = headers + [h for h in extra_headers if h not in headers]

    with open(output_csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    
    # Keep stdout ASCII-safe for Windows terminals that default to cp1252.
    print(f"OK: exported to {output_csv}")
    print(f"Rows: {len(rows)}")
    print(f"Columns: {len(headers)}")

if __name__ == "__main__":
    main()

