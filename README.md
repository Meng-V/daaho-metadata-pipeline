# DAAHO Metadata Pipeline

AI-assisted metadata generation for **Documenting Asian American Histories in Ohio** (DAAHO), a
digital collection at Miami University Libraries.

The pipeline reads scanned archival documents — letters, forms, newspaper clippings, bound volumes —
and produces one catalog record per archival item: title, date, creator, correspondents, places,
controlled subject and genre terms, and a transcript that follows the project's written transcription
policy. Output is JSON per item plus a CSV shaped like the collection's upload spreadsheet.

It is built around a premise: **an empty field a cataloger can see is better than a wrong one they
cannot.** Values that cannot be grounded in the document are left blank and flagged, never guessed.

---

## What it produces

For each archival item:

- **Descriptive metadata** — title in sentence case with a date suffix, ISO date, creator in inverted
  form, correspondents and contributors, FAST-style places, a grounded summary
- **Controlled terms** — subjects validated against FAST, genre against the Getty AAT. Unmatched terms
  are rejected by name and recorded, not silently replaced
- **A policy-compliant transcript** — original misspellings retained with the correction bracketed
  (`Sincerly [Sincerely] yours`), `[illegible]` never guessed, letterhead skipped, pages marked
  `[page N]`
- **A per-field confidence score** — the triage signal that lets one person review a batch
- **Full cost accounting** — per API call, per item, per model tier

Alongside every run: a manifest of per-item outcomes, a cost ledger, and a policy-compliance report.

## Scale and cost, measured

| | |
|---|---|
| Current batch | 316 images → **128 archival items** |
| Cost | **$17.95** — $0.14 per record, $0.057 per image |
| Records flagged for human review | 10 of 128 |
| Policy violations | 0 errors |
| Tests | 63, all offline |

Multi-page documents and recto/verso pairs become **one** record whose transcript spans all pages, so
image count and record count differ.

Costs are what was actually billed. Pricing the API's own reported token counts at published list
rates overstated this account's bill by 58%, so the ledger reports both figures and names which is
which — see `BILLING_CALIBRATION` in `app/cost.py`. **The provider's usage dashboard is authoritative
for amounts charged**; the ledger is authoritative for relative cost, which holds either way.

---

## Quick start

Python 3.10+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your OPENAI_API_KEY
python3 -m pytest tests/ -q   # 63 tests, no API key needed
```

Survey a batch before spending anything on it:

```bash
python3 scripts/triage_batch.py ./images --csv triage.csv
```

Reports how many archival items your files actually represent, which exceed the image-size cap, what
is already processed, and the projected cost at each model tier. No API calls.

Process:

```bash
python3 -m app.main --in ./images --out ./out_batch --tier terra --workers 4
```

Then review the results:

```bash
python3 scripts/policy_lint.py --out-dir ./out_batch --quiet     # transcription policy compliance
python3 scripts/audit_fields.py --out-dir ./out_batch            # name / place / type field defects
python3 scripts/cost_deliverable.py --out-dir ./out_batch        # cost CSVs for a handoff
python3 export_csv.py --out-dir ./out_batch \
    --template out/final_metadata_2026-04-27_handoff.csv --output upload.csv
```

Resume is "skip if the output file exists", so rerunning the same command retries only what failed. A
failed item writes a `.failed.json` and no record, so a resume never skips a hole.

Archival placement — box, folder, series, repository, rights — is **never** inferred. Supply it
explicitly or it stays empty:

```bash
python3 -m app.main --in ./images --out ./out_batch \
    --collection "..." --repository "..." --series "..." --box "..." --folder "..."
```

Pulling from Google Drive instead of a local directory needs `GDRIVE_FOLDER_ID` and OAuth desktop
credentials in `.env`; see `.env.example`. The download is not recursive, so sub-folders are skipped.

## Model tiers

Three tiers, selected with `--tier`, so the expensive model is spent only where it earns its cost.

| Tier | Model | For |
|---|---|---|
| `luna` | gpt-5.6-luna | Clean typed documents |
| `terra` | gpt-5.6-terra | **Default.** Typed with some difficulty, clippings |
| `sol` | gpt-5.6-sol | Handwriting, damage, dense multi-column pages |

All three read images at full resolution. Earlier tile-resizing models reduced a 5000px scan's
shortest side to 768px, which is where misread names and dates came from. Handwritten material should
go to `sol` from the start — on this collection that was the difference between a two-line transcript
and a full one.

---

## How it works

```
images ──► group into archival items ──► local OCR (free) ──► vision model
                                                                   │
   controlled-vocabulary enforcement ◄── tier policy ◄── structured metadata + transcript
                │
                ├──► per-item JSON  (metadata, tiers, provenance, confidence, notes)
                ├──► cost ledger    (one row per API call)
                ├──► run manifest   (per-item outcome)
                └──► CSV export     (collection upload sheet)
```

| Module | Role |
|---|---|
| `app/grouping.py` | Groups image files into archival items and orders their pages |
| `app/ocr.py` | Local OCR, image payload preparation, pixel cap |
| `app/ai_metadata.py` | Vision extraction, retry with backoff, tier policy |
| `app/schema.py` | The metadata schema and trust tiers |
| `app/main.py` | Per-item orchestration, vocabulary enforcement, rebuild |
| `app/cost.py` | Model tiers, pricing, per-call cost ledger |
| `app/evidence_qc.py`, `app/validation_core.py` | Deterministic quality checks |
| `vocab/` | Approved FAST and AAT terms, each carrying its authority id |
| `prompts/` | Cataloging standard and transcription policy as instructions |

Reprocessing metadata **without** re-calling the model — after expanding a vocabulary, for instance —
is free:

```bash
python3 -m app.main --rebuild-from-existing --out ./out_batch
```

This re-offers previously rejected terms to the current vocabulary and preserves archival placement.

Growing the vocabularies from what a run rejected, verified against the authority files rather than
typed from memory:

```bash
python3 scripts/expand_vocab_from_run.py out_batch --write
python3 scripts/verify_aat_terms.py vocab/aat_genre.txt
```

---

## Documentation

| | |
|---|---|
| [`docs/ADOPTING_THIS_PIPELINE.md`](docs/ADOPTING_THIS_PIPELINE.md) | **Bringing this to another institution.** What transfers, what you must change, and in what order |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every design decision with its reasoning |
| [`docs/OVERHAUL_2026-07.md`](docs/OVERHAUL_2026-07.md) | The July 2026 rebuild: what was wrong, how each fault was found, what remains open |
| [`docs/transcription_policy_rules.md`](docs/transcription_policy_rules.md) | The written transcription policy turned into enforceable rules |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Open problems |

## Status

The current batch is a **staging deliverable**. The project's transcription policy requires human
proofreading before a transcript is final, and most records have not had it. Confidence scores flag
where to look first, but they are the model scoring itself — a confidently wrong record will not be
flagged. Nothing here should be published as final metadata without a person signing off on that
record.

## License

See [LICENSE](LICENSE).
