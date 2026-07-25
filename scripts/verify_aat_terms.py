#!/usr/bin/env python3
"""Verify genre terms against the Getty AAT and report the authorized preferred label.

The AAT genre list must contain real AAT preferred labels, or `_enforce_approved_genre()` in
app/main.py will silently reject valid model output. This queries the Getty SPARQL endpoint
directly rather than trusting anyone's memory of the vocabulary.

Usage:
    python3 scripts/verify_aat_terms.py vocab/aat_genre.txt
    python3 scripts/verify_aat_terms.py --terms "letters (correspondence)" "forewords"
    python3 scripts/verify_aat_terms.py vocab/aat_genre.txt --suggest

With --suggest, any term that is not a preferred label is searched for as a substring so the
authorized form can be found (e.g. "forewords" -> the actual AAT concept covering it).
"""

import argparse
import sys
from pathlib import Path

import requests

SPARQL = "https://vocab.getty.edu/sparql.json"
TIMEOUT = 30


def _query(sparql: str):
    response = requests.get(SPARQL, params={"query": sparql}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def check_preferred(terms):
    """Return {term: aat_id} for terms that are AAT preferred labels."""
    found = {}
    # Chunked so a long list does not blow the query size.
    for start in range(0, len(terms), 40):
        chunk = terms[start:start + 40]
        values = " ".join(f'"{t}"@en' for t in chunk)
        rows = _query(f"""
            SELECT ?concept ?label WHERE {{
              VALUES ?label {{ {values} }}
              ?concept a skos:Concept ; skos:inScheme aat: ;
                       xl:prefLabel/xl:literalForm ?label .
            }}""")
        for row in rows:
            found[row["label"]["value"]] = row["concept"]["value"].rsplit("/", 1)[-1]
    return found


def check_alt(terms):
    """Return {term: (preferred_label, aat_id)} for terms that are AAT *alternate* labels."""
    found = {}
    for start in range(0, len(terms), 20):
        chunk = terms[start:start + 20]
        values = " ".join(f'"{t}"@en' for t in chunk)
        rows = _query(f"""
            SELECT ?concept ?alt ?pref WHERE {{
              VALUES ?alt {{ {values} }}
              ?concept a skos:Concept ; skos:inScheme aat: ;
                       xl:altLabel/xl:literalForm ?alt ;
                       xl:prefLabel/xl:literalForm ?pref .
            }}""")
        for row in rows:
            found[row["alt"]["value"]] = (
                row["pref"]["value"],
                row["concept"]["value"].rsplit("/", 1)[-1],
            )
    return found


def suggest(term: str, limit: int = 6):
    """Substring search over AAT preferred labels."""
    needle = term.split("(")[0].strip().replace('"', "")
    rows = _query(f"""
        SELECT ?label WHERE {{
          ?concept a skos:Concept ; skos:inScheme aat: ;
                   xl:prefLabel/xl:literalForm ?label .
          FILTER(CONTAINS(LCASE(?label), LCASE("{needle}")))
        }} LIMIT {limit}""")
    return [row["label"]["value"] for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", type=Path, help="Vocab file to verify (# comments skipped)")
    parser.add_argument("--terms", nargs="*", default=[], help="Verify these terms instead of a file")
    parser.add_argument("--suggest", action="store_true", help="Search AAT for unmatched terms")
    args = parser.parse_args()

    if args.terms:
        terms = list(args.terms)
    elif args.path:
        # Same parsing as app.main._load_controlled_list: strip trailing inline comments.
        terms = [
            token for token in (
                line.split("#", 1)[0].strip()
                for line in args.path.read_text(encoding="utf-8").splitlines()
            ) if token
        ]
    else:
        sys.exit("give a vocab file path or --terms")

    terms = sorted(set(terms))
    print(f"verifying {len(terms)} terms against Getty AAT ({SPARQL})\n")

    preferred = check_preferred(terms)
    missing = [t for t in terms if t not in preferred]
    alternates = check_alt(missing) if missing else {}

    for term in terms:
        if term in preferred:
            print(f"  OK    {term:44} aat:{preferred[term]}")
        elif term in alternates:
            pref, aat_id = alternates[term]
            print(f"  ALT   {term:44} -> preferred: {pref!r} (aat:{aat_id})")
        else:
            print(f"  MISS  {term}")
            if args.suggest:
                for hit in suggest(term):
                    print(f"          candidate: {hit}")

    bad = [t for t in terms if t not in preferred]
    print(f"\n{len(preferred)}/{len(terms)} are AAT preferred labels")
    if bad:
        print(f"not preferred: {len(bad)} -> {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
