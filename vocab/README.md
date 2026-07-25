# Local Controlled Vocabulary Lists

These files are deterministic, in-repo controlled lists used by offline validation:

- `fast_places.txt`: approved FAST-style place tokens (`State--City`)
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

## Known gap

`fast_places.txt` (9 entries) and `fast_subjects.txt` (47 entries) are still sized for the 19-image
pilot. They will under-cover a larger batch — see the note on subject fallback behavior in
`docs/DECISIONS.md`.

Regenerate from a reviewed metadata CSV:

```bash
python scripts/build_vocab_from_review_csv.py --input-csv "<path-to-reviewed-csv>" --out-places vocab/fast_places.txt --out-subjects vocab/fast_subjects.txt
```

Notes:
- Place canonicalization currently normalizes common Washington, D.C. variants to `District of Columbia--Washington`.
- Non FAST-style place tokens are dropped by the builder and printed in script output.
