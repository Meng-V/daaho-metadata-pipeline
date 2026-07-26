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

## Gap now closed

`AI_Generated_Metadata_Test_Apr_21.xlsx` — the sheet the review assistant used for BC-0688 through
BC-0713 — **was recovered on 2026-07-25** and is the baseline the current pipeline is compared
against. See `docs/DECISIONS.md` D-012 for the field-by-field agreement and for which divergences
are deliberate.

Three CSV/XLSX versions now exist, oldest first:

| Version | Location | Role |
|---|---|---|
| January 2026 | `final_metadata.csv` (committed) | earliest; a partial recovery source for content later lost (see KNOWN_ISSUES) |
| April 21 2026 | `AI_Generated_Metadata_Test_Apr_21.xlsx` | what the review assistant reviewed BC-0688..0713 against |
| April 27 2026 | `out/final_metadata_2026-04-27_handoff.csv` (committed) | the handoff sheet, and the column template for exports |

`scripts/csv_version_diff.py` compares any two CSV versions. The xlsx needs no openpyxl to read —
it is a zip of XML; unzip it and parse `xl/worksheets/sheet1.xml` against `xl/sharedStrings.xml`.
