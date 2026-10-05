#!/usr/bin/env python3
"""Turn a run's rejected controlled terms into verified vocabulary additions.

D-010 stops the pipeline guessing when a term is outside the approved lists, and records what it
rejected instead. Those rejections are the raw material for growing the vocabulary. This script
collects them, checks each against its authority file, and writes only the ones that verify.

  subjects / places  ->  FAST (fast.oclc.org suggest API), which returns the authorized heading
                         and its fst id
  genre              ->  Getty AAT SPARQL, preferred labels only

Usage:
    python3 scripts/expand_vocab_from_run.py out_batch                # report only
    python3 scripts/expand_vocab_from_run.py out_batch --write        # append verified terms
    python3 scripts/expand_vocab_from_run.py out_batch --write --places-only

Nothing is written without --write. Existing entries are never rewritten or reordered; verified
new terms are appended under a dated heading so the provenance of each batch of additions is
visible in the file itself.
"""

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import _load_controlled_list  # noqa: E402

FAST_SUGGEST = "https://fast.oclc.org/searchfast/fastsuggest"
GETTY_SPARQL = "https://vocab.getty.edu/sparql.json"
TIMEOUT = 25

REJECT_PATTERNS = {
    "subjects": re.compile(r"^Rejected subject terms absent from the approved FAST list:\s*(.+)$"),
    "genre": re.compile(r"^Rejected genre terms absent from the approved AAT list:\s*(.+)$"),
    "places": re.compile(r"^Place tokens absent from the approved FAST list:\s*(.+)$"),
}

VOCAB_FILES = {
    "subjects": Path("vocab/fast_subjects.txt"),
    "genre": Path("vocab/aat_genre.txt"),
    "places": Path("vocab/fast_places.txt"),
}

# FAST suggest facets. "autoSubject" narrows to topical headings; there is no working geographic
# equivalent -- passing suggest=autoGeographic makes the endpoint answer "Status: 404" inside a
# 200 response, which surfaces as a JSON decode error. Places query the unfaceted index instead.
FAST_INDEX = {"subjects": "suggestall", "places": "suggestall"}
FAST_SUGGEST_FACET: Dict[str, Optional[str]] = {"subjects": "autoSubject", "places": None}


def collect_rejections(out_dir: Path) -> Dict[str, Counter]:
    """Read policy_notes across a run's envelopes and tally rejected terms per vocabulary."""
    import json

    found = {kind: Counter() for kind in REJECT_PATTERNS}
    for path in sorted(out_dir.glob("*.loc15.json")):
        try:
            notes = json.loads(path.read_text(encoding="utf-8")).get("context", {}).get("policy_notes", [])
        except Exception:
            continue
        for note in notes:
            for kind, pattern in REJECT_PATTERNS.items():
                match = pattern.match(note)
                if match:
                    for term in match.group(1).split(";"):
                        term = term.strip()
                        if term:
                            found[kind][term] += 1
    return found


def verify_fast(term: str, kind: str) -> Tuple[bool, Optional[str], Optional[str], List[str]]:
    """Return (verified, authorized_heading, fst_id, near_misses)."""
    # Parentheses are Solr query syntax. Unescaped, "Miami University (Oxford, Ohio)" and
    # "World War (1939-1945)" fail to parse -- the only two existing vocabulary entries that did
    # not verify during a self-check. Escaping them fixes both.
    escaped = re.sub(r'([()\[\]{}"\\^~*?:])', r"\\\1", term)
    params = {
        "query": escaped,
        "queryIndex": FAST_INDEX[kind],
        "queryReturn": "suggestall,idroot,auth,type",
        "rows": 20,
    }
    facet = FAST_SUGGEST_FACET[kind]
    if facet:
        params["suggest"] = facet
    try:
        response = requests.get(FAST_SUGGEST, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
    except Exception as exc:
        return False, None, None, [f"(lookup failed: {exc})"]

    wanted = " ".join(term.lower().split())
    others: List[str] = []
    for doc in docs:
        ids = doc.get("idroot") or []
        # Topical headings carry `auth`; geographic headings return only `suggestall`. Checking
        # `auth` alone silently failed every place lookup, including entries already in the vocab.
        candidates = [doc.get("auth")] + list(doc.get("suggestall") or [])
        for candidate in [c for c in candidates if c]:
            # A label with no FAST id is a see-reference ("China--Peking" -> China--Beijing), not an
            # authorized heading. Counting it as verified let variant forms into the vocabulary.
            if " ".join(candidate.lower().split()) == wanted and ids:
                return True, candidate, ids[0], []
        for candidate in [c for c in candidates if c]:
            if candidate not in others:
                others.append(candidate)
    return False, None, None, others[:4]


def verify_aat(terms: List[str]) -> Dict[str, str]:
    """Return {term: aat_id} for terms that are AAT preferred labels."""
    found: Dict[str, str] = {}
    for start in range(0, len(terms), 30):
        chunk = terms[start:start + 30]
        values = " ".join(f'"{t}"@en' for t in chunk)
        query = f"""
            SELECT ?concept ?label WHERE {{
              VALUES ?label {{ {values} }}
              ?concept a skos:Concept ; skos:inScheme aat: ;
                       xl:prefLabel/xl:literalForm ?label .
            }}"""
        try:
            response = requests.get(GETTY_SPARQL, params={"query": query}, timeout=TIMEOUT)
            response.raise_for_status()
            for row in response.json()["results"]["bindings"]:
                found[row["label"]["value"]] = row["concept"]["value"].rsplit("/", 1)[-1]
        except Exception as exc:
            print(f"  AAT lookup failed for a chunk: {exc}", file=sys.stderr)
    return found


def append_terms(path: Path, entries: List[Tuple[str, str]], heading: str) -> int:
    """Append `entries` as `term  # comment` lines under a dated heading. Skips duplicates."""
    existing = _load_controlled_list(str(path))
    fresh = [(t, c) for t, c in entries if t not in existing]
    if not fresh:
        return 0
    width = max(len(t) for t, _ in fresh) + 2
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# --- {heading} ---\n")
        for term, comment in sorted(fresh):
            handle.write(f"{term:<{width}}# {comment}\n" if comment else f"{term}\n")
    return len(fresh)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--write", action="store_true", help="Append verified terms to vocab/")
    parser.add_argument("--date", default=time.strftime("%Y-%m-%d"), help="Heading date")
    parser.add_argument("--force-places", action="store_true",
                        help="Write place terms despite unreliable verification (see the caveat "
                             "in the places branch). Only after confirming them by hand.")
    for kind in VOCAB_FILES:
        parser.add_argument(f"--{kind}-only", action="store_true", help=f"Only process {kind}")
    args = parser.parse_args()

    only = [k for k in VOCAB_FILES if getattr(args, f"{k}_only")]
    kinds = only or list(VOCAB_FILES)

    rejections = collect_rejections(args.out_dir)
    total_added = 0

    for kind in kinds:
        terms = rejections[kind]
        print(f"\n{'=' * 78}\n{kind.upper()}  ({len(terms)} distinct rejected terms)\n{'=' * 78}")
        if not terms:
            continue

        verified: List[Tuple[str, str]] = []
        unverified: List[Tuple[str, List[str]]] = []

        if kind == "genre":
            ids = verify_aat(list(terms))
            for term, count in terms.most_common():
                if term in ids:
                    verified.append((term, f"aat:{ids[term]}  (x{count} in run)"))
                else:
                    unverified.append((term, []))
        else:
            for term, count in terms.most_common():
                ok, auth, fst_id, near = verify_fast(term, kind)
                if ok:
                    note = f"fast:{fst_id}" if fst_id else "FAST verified"
                    # Keep the project's existing casing convention; record FAST's authorized
                    # form in the comment when it differs, so the authority link is not lost.
                    if auth and auth != term:
                        note += f'  authorized: "{auth}"'
                    verified.append((term, f"{note}  (x{count} in run)"))
                else:
                    unverified.append((term, near))

        for term, comment in verified:
            print(f"  OK    {term:42} {comment}")
        for term, near in unverified:
            print(f"  MISS  {term}")
            for candidate in near:
                print(f"          candidate: {candidate}")

        print(f"\n  verified {len(verified)}/{len(terms)}")

        if kind == "places":
            # The FAST suggest endpoint cannot verify geographic headings reliably. There is no
            # working geographic facet (suggest=autoGeographic answers 404 inside a 200), the
            # endpoint caps at 20 relevance-ranked docs, and popular same-name institutions bury
            # the heading. A self-check against the existing vocabulary verified only 6 of 9
            # entries, missing "Pennsylvania--Philadelphia" and "District of Columbia--Washington",
            # which are unquestionably valid. Those are FALSE NEGATIVES, so writing only what
            # "verified" would exclude real headings while implying they were checked.
            #
            # Subjects have a working facet and self-check at 47/47, so they are written; places
            # are reported for confirmation against the searchFAST interface instead.
            print("\n  NOT WRITTEN. Place verification via this API produces false negatives: a")
            print("  self-check verified only 6 of the 9 places already in the vocabulary.")
            print("  Confirm these by hand at https://fast.oclc.org/searchfast/ and add them to")
            print("  vocab/fast_places.txt, or pass --force-places once confirmed.")
            if args.force_places and verified:
                added = append_terms(
                    VOCAB_FILES[kind], verified,
                    f"Added {args.date} from {args.out_dir.name}: FAST suggest matched (see caveat in "
                    f"scripts/expand_vocab_from_run.py)",
                )
                total_added += added
                print(f"  --force-places given; appended {added} terms")
            continue

        if args.write and verified:
            added = append_terms(
                VOCAB_FILES[kind], verified,
                f"Added {args.date} from {args.out_dir.name}: verified against authority file",
            )
            total_added += added
            print(f"  appended {added} terms to {VOCAB_FILES[kind]}")

    if args.write:
        print(f"\nTotal appended: {total_added}")
        print("Re-apply to existing output with a rebuild (no API cost):")
        print(f"  python3 -m app.main --rebuild-from-existing --out {args.out_dir}")
    else:
        print("\nReport only. Pass --write to append verified terms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
