# Local Controlled Vocabulary Lists

These files are deterministic, in-repo controlled lists used by offline validation:

- `fast_places.txt`: approved FAST authorized place headings, each with its FAST id
- `fast_place_variants.txt`: variant and historical forms mapped to those headings (`variant => authorized`)
- `fast_subjects.txt`: approved reviewed subject terms from `Subject (FAST)`
- `aat_genre.txt`: approved AAT genre terms (38 verified preferred labels)

## File format

`app/main.py` `_load_controlled_list()` reads one term per line. Blank lines and `#` comments are
skipped, **including trailing inline comments** — so a term can carry its authority id beside it:

```
letters (correspondence)                # aat:300026879
```

## Verifying AAT genre terms

`_enforce_approved_genre()` matches model output against this list and drops anything absent, so a
term that is not an authorized AAT **preferred** label silently discards valid output. Verify
against the Getty SPARQL endpoint after any edit:

```bash
python3 scripts/verify_aat_terms.py vocab/aat_genre.txt
```

The script reports each term as `OK` (preferred label, with its `aat:` id), `ALT` (an alternate
label — use the preferred form it names instead), or `MISS`. Use `--suggest` to search AAT for a
replacement. `aat_genre.txt` was 38/38 `OK` as of 2026-07-25.

Qualifiers matter: `letters` and `letters (correspondence)` are different AAT concepts and only the
qualified form is preferred. The tail of `aat_genre.txt` records terms that were tested and
rejected, so they do not get re-added.

## Places follow FAST (D-015)

The standard is FAST itself, per the archivist's MAP review; `fast_places.txt` is a verified cache of
it. A heading is added only when FAST returns it **with a FAST id** — a label without an id is a
see-reference (`China--Peking` refers to `China--Beijing`). A form that names a certain place in the
wrong way goes in `fast_place_variants.txt`, never in `fast_places.txt`; `tests/test_places.py`
checks that every mapping lands on an approved heading.

`fast_subjects.txt` is still sized for the 19-image pilot and will under-cover a larger batch — see
the note on subject fallback behavior in `docs/DECISIONS.md`.

Regenerate from a reviewed metadata CSV:

```bash
python scripts/build_vocab_from_review_csv.py --input-csv "<path-to-reviewed-csv>" --out-places vocab/fast_places.txt --out-subjects vocab/fast_subjects.txt
```

Notes:
- Place variants, including every Washington, D.C. form, map to FAST headings through `fast_place_variants.txt`.
- Non FAST-style place tokens are dropped by the builder and printed in script output.
