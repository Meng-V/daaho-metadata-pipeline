# Source Documents (local only — NOT committed)

This directory is gitignored except for this README. **This GitHub repository is PUBLIC**
(`Meng-V/daaho-metadata-pipeline`, forked from `lucas-ms1/daaho-metadata-pipeline`, both public).
The documents listed below contain student-worker names, university email addresses, and a private
Gmail thread permalink, so they must not be committed.

File the originals here so the project's authoritative sources live with the code rather than on
someone's Desktop. Everything the pipeline actually consumes has been extracted into committed,
PII-free artifacts — listed in the right-hand column.

| Expected filename | What it is | Extracted into |
|---|---|---|
| `Transcription Policy_FINAL.docx` | **Authoritative.** DAAHO transcription policy. §2 governs written documents; §4 the QC requirement; §6 a worked example transcript. | `docs/transcription_policy_rules.md` |
| `AI Metadata Generation Review.pdf` | Archivist field-by-field review (Title / Date / Decade / Location) against the Asian Americans at Miami MAP. | `docs/DECISIONS.md` (D-001) |
| `comments _ suggested corrections -- Jinming.pdf` | The only human verification pass this collection has. 16 of 19 pilot images. | `tests/fixtures/jinming_review_2026-04.json` |
| `Google Apps @ Miami University Mail - Re_ CSV Handoff.pdf` | April 2026 handoff email thread. Establishes which CSV version each review was made against, and the five name spellings flagged for confirmation. | `docs/DECISIONS.md` (D-005), fixture `provenance` block |

## Known gap

The Apr 21 Google Sheet (`AI_Generated_Metadata_Test_Apr_21`) that the review assistant used for
BC-0688 through BC-0713 is **not in this repo and may no longer exist**. `final_metadata.csv`
(January 2026) is an earlier version; `out/final_metadata_2026-04-27_handoff.csv` is the April one.
`scripts/csv_version_diff.py` compares the two that survive. Findings on items ≤ BC-0713 in the
fixture therefore need re-anchoring against current output before being treated as open.

If you can still retrieve that Apr 21 sheet from Google Drive, save it here as
`AI_Generated_Metadata_Test_Apr_21.csv` — it would make the fixture's ≤ BC-0713 findings exact.
