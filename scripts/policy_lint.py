#!/usr/bin/env python3
"""Deterministic DAAHO Transcription Policy checks on pipeline transcripts.

Implements the AUTO-checkable rules from docs/transcription_policy_rules.md (R1-R17). These are
the mechanical checks the departed review assistant was performing by eye. Machine-checking them
is what makes a solo review workflow viable at scale: a human should only look at what a checker
cannot decide.

Usage:
    python3 scripts/policy_lint.py                      # lint ./out
    python3 scripts/policy_lint.py --out-dir ./out_v4   # lint another run
    python3 scripts/policy_lint.py --json               # machine-readable
    python3 scripts/policy_lint.py --compare ./out      # diff violation counts vs another run

Exit code is 1 if any ERROR-severity violation is found, else 0.

Deliberately NOT checked here (a machine cannot decide these -- see docs/DECISIONS.md D-004):
  * whether a bracketed [correction] is the RIGHT correction
  * whether an [illegible] marker should have been a real reading, or vice versa
  * whether a value is justified by the item (provenance)
  * whether any text was omitted -- we cannot know what is on the image without reading it
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# --- R1: printed institutional letterhead openings seen in this collection -------------------
LETTERHEAD_PATTERNS = [
    r"ADDRESS OFFICIAL COMMUNICATIONS TO",
    r"^\s*DEPARTMENT OF STATE\s*$",
    r"^\s*Federal Security Agency\s*$",
    r"NATIONAL YOUTH ADMINISTRATION FOR",
    r"^\s*(FOR VICTORY|BUY)\s*$",
    r"OFFICE OF THE PRESIDENT",
    r"^\s*MIAMI UNIVERSITY\s*$",
    r"^\s*WESTERN UNION\s*$",
]

# --- Bracket markers the policy defines. Anything else in brackets is suspect. ---------------
KNOWN_MARKERS = {
    "illegible", "unclear", "handwritten", "redacted",
    "this section closed", "these pages closed",
}
KNOWN_PREFIXES = ("struck:", "underlined:", "page ")

SEVERITY_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}


# A date line marks the end of any letterhead region: "October 27, 1938", "20 September 1945",
# "1937-10-19". Matched loosely -- a false positive only shortens the region we inspect.
_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
# Abbreviated forms appear in received stamps: "SEP 25 1946", "MAR 1 1944". Missing them left the
# stamp inside the letterhead region, so the institution name printed on the stamp itself was
# flagged as transcribed letterhead on five items -- a third class of false positive in this checker.
_MONTHS_ABBR = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE_LINE = re.compile(
    rf"^\s*(?:\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}"
    rf"|(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|(?:{_MONTHS_ABBR})\.?\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}})\s*$",
    re.IGNORECASE,
)
# A received stamp also opens the region; it is document content, not stationery (R16 requires
# transcribing stamps), so it must not extend the letterhead scan past itself.
_STAMP_LINE = re.compile(r"^\s*(RECEIVED|ANSWERED|FILED)\b", re.IGNORECASE)


def _looks_like_date_line(line: str) -> bool:
    """True where the letterhead region ends: a date line or the start of a received stamp."""
    return bool(_DATE_LINE.match(line) or _STAMP_LINE.match(line))


def brackets(text: str) -> list:
    return re.findall(r"\[([^\]]*)\]", text)


def check(item_id: str, transcript: str) -> list:
    """Return a list of (severity, rule, message) violations."""
    issues = []

    def add(sev, rule, msg):
        issues.append((sev, rule, msg))

    if not transcript or not transcript.strip():
        add("ERROR", "R16", "transcript is empty or missing")
        return issues

    lines = transcript.splitlines()
    all_brackets = brackets(transcript)
    non_hw = [b for b in all_brackets if b.strip().lower() != "handwritten"]

    # R1 -- printed stationery letterhead must not be transcribed.
    #
    # Letterhead is the SENDER's printed masthead and always precedes the date line. An institution
    # name appearing *after* the date is the recipient's inside address, and a "RECEIVED / <date> /
    # PRESIDENT'S OFFICE" block is a received stamp -- both are the document's own content, and R16
    # explicitly requires transcribing stamps. Checking the whole opening region flagged all three
    # of those as violations; only the pre-date region is letterhead.
    head_lines = []
    for line in lines[:14]:
        stripped = line.strip()
        if _looks_like_date_line(stripped):
            break
        head_lines.append(stripped)
    head = "\n".join(head_lines)
    for pattern in LETTERHEAD_PATTERNS:
        match = re.search(pattern, head, re.MULTILINE | re.IGNORECASE)
        if match:
            add("ERROR", "R1", f"printed letterhead transcribed: {match.group(0).strip()!r}")
            break

    # R2 -- line breaks must not be mimicked.
    #
    # Mimicry looks like a *run* of consecutive short lines: letterhead, an address block, or a
    # column copied down the page. It does NOT look like an isolated short line between blank
    # lines -- a letter legitimately puts its [page N] marker, date line, heading, salutation and
    # closing on their own lines, and policy S2 only forbids reproducing the original's layout
    # within running text. An earlier version of this check counted every short line and reported
    # 15 false positives on correctly reflowed letters.
    content = [ln for ln in lines if ln.strip()]
    runs, current = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        runs.append(current)

    worst = 0
    for run in runs:
        if len(run) < 3:
            continue
        short = sum(1 for ln in run if len(ln) < 45)
        if short / len(run) >= 0.8:
            worst = max(worst, short)
    if worst >= 5:
        add("ERROR", "R2", f"line breaks appear mimicked: a run of {worst} consecutive short lines")
    elif worst >= 3:
        add("WARN", "R2", f"possible line-break mimicry: a run of {worst} consecutive short lines")

    # R4 -- page markers.
    if not re.search(r"^\s*\[page \d+\]\s*$", transcript, re.MULTILINE):
        add("ERROR", "R4", "no [page N] marker on its own line")

    # R6/R7 -- the retain-and-annotate contract leaves bracket traces. None at all is a red flag.
    if not non_hw:
        add("ERROR", "R6/R7", "no bracket annotations at all -- transcript is very likely silently normalized")

    # R13 -- superscript markup must be stripped.
    if re.search(r"</?sup>|<sup", transcript, re.IGNORECASE):
        add("ERROR", "R13", "superscript markup present; policy requires it removed")

    # R15 -- bare ampersand needs [and].
    for match in re.finditer(r"\s&\s", transcript):
        tail = transcript[match.end(): match.end() + 8]
        if not tail.lstrip().startswith("[and]"):
            add("WARN", "R15", "bare '&' not followed by [and]")
            break

    # R11/R12 -- project convention (D-006): [struck: ...] / [underlined: ...].
    if re.search(r"~~|<s>|<strike|<del", transcript, re.IGNORECASE):
        add("WARN", "R11", "non-standard strikeout markup; use [struck: ...] per D-006")
    if re.search(r"<u>|__[^_]+__", transcript):
        add("WARN", "R12", "non-standard underline markup; use [underlined: ...] per D-006")

    # Unknown bracket markers -- catches drift and invented markers.
    for marker in non_hw:
        token = marker.strip()
        low = token.lower()
        if low in KNOWN_MARKERS or low.startswith(KNOWN_PREFIXES):
            continue
        # A bracketed correction/gloss is free text; flag only if it looks like a directive.
        if len(token.split()) <= 3 and token.endswith(":"):
            add("WARN", "markers", f"unrecognized bracket marker: [{token}]")

    # Guessed-handwriting heuristic: [handwritten] followed by words then an uncertainty marker
    # means a candidate reading was offered where the policy requires none (R18).
    for match in re.finditer(r"\[handwritten\]\s*([^\[\n]{1,60}?)\s*\[(illegible|unclear)\]", transcript, re.IGNORECASE):
        guess = match.group(1).strip(" .,;:-")
        if guess:
            add("ERROR", "R18", f"candidate reading offered for uncertain handwriting: {guess!r}")

    # INFO: annotation density, useful when comparing runs.
    add("INFO", "stats", f"{len(content)} lines, {len(non_hw)} bracket annotations, {len(transcript)} chars")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--compare", default="", help="Second output dir to compare violation counts against")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--quiet", action="store_true", help="Suppress INFO lines")
    args = parser.parse_args()

    def lint_dir(directory: Path):
        results = {}
        for path in sorted(directory.glob("*.loc15.json")):
            item_id = path.name.replace(".loc15.json", "")
            metadata = json.loads(path.read_text(encoding="utf-8")).get("metadata", {})
            results[item_id] = check(item_id, metadata.get("transcript") or "")
        return results

    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        sys.exit(f"not a directory: {out_dir}")
    results = lint_dir(out_dir)
    if not results:
        sys.exit(f"no *.loc15.json found in {out_dir}")

    if args.as_json:
        payload = {
            item: [{"severity": s, "rule": r, "message": m} for s, r, m in issues]
            for item, issues in results.items()
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    rule_counts, sev_counts = Counter(), Counter()
    print(f"policy lint: {out_dir}  ({len(results)} transcripts)\n")
    for item_id, issues in results.items():
        shown = [i for i in issues if not (args.quiet and i[0] == "INFO")]
        flagged = [i for i in issues if i[0] != "INFO"]
        for sev, rule, _ in flagged:
            rule_counts[rule] += 1
            sev_counts[sev] += 1
        if not shown:
            continue
        marker = "ok  " if not flagged else "FAIL"
        print(f"[{marker}] {item_id}")
        for sev, rule, msg in sorted(shown, key=lambda i: SEVERITY_ORDER[i[0]]):
            print(f"         {sev:5} {rule:8} {msg}")

    clean = sum(1 for issues in results.values() if not any(s != "INFO" for s, _, _ in issues))
    print(f"\n{'=' * 66}")
    print(f"clean transcripts: {clean}/{len(results)}")
    print(f"violations: {sev_counts['ERROR']} ERROR, {sev_counts['WARN']} WARN")
    if rule_counts:
        print("\nby rule:")
        for rule, count in rule_counts.most_common():
            print(f"  {count:3}  {rule}")

    if args.compare:
        other = lint_dir(Path(args.compare))
        def errs(res):
            return sum(1 for issues in res.values() for s, _, _ in issues if s == "ERROR")
        mine, theirs = errs(results), errs(other)
        print(f"\ncompare: {out_dir} {mine} ERROR  vs  {args.compare} {theirs} ERROR"
              f"  ({mine - theirs:+d})")

    return 1 if sev_counts["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
