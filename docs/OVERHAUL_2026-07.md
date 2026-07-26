# The July 2026 Overhaul

What the pipeline was, what was wrong with it, and how each fault was found. Written for whoever
inherits this — including the wrong turns, because two of them cost real money and would be easy to
repeat.

**Context.** Both student workers who built and reviewed the April 2026 pilot had departed. The
project lead was alone, holding 316 unprocessed images, a 19-image pilot output, and one incomplete
human review that existed only as a PDF on a desktop.

---

## 1. Where it started

The April 2026 state:

- 19 pilot images processed with `gpt-4o` and a prompt called `loc15_v2`
- A handoff CSV, an archivist's field-by-field review, and a student assistant's correction list
- `0` policy violations by the project's own validator, which sounded like success

Against the one human review that existed, the pilot output resolved **0 of 30** findings. The
validator reporting zero problems was measuring the wrong things.

## 2. The root cause nobody had named

`prompts/loc15_v2_system.txt` and its few-shot successor contained **no transcript instructions at
all** — a regression from `loc15_v1`, which had them. The model writes the transcript, and every other
field derives from it, so an unconstrained transcript was the origin of most findings in the review:

- Source misspellings silently corrected (`Sincerly` → `Sincerely`)
- Damaged regions filled with plausible text that is not on the page
- Handwritten surnames invented (`Murry`, `C V Hibbard`) and then propagated into `creator`
- Whole regions omitted, including one transcript that was simply empty

The project *had* a written transcription policy. It had never been encoded.

## 3. What was built

In order, because each step depended on the one before.

### 3.1 Preserve the perishable evidence

The only human verification this collection will ever get was a prose PDF. It became
`tests/fixtures/jinming_review_2026-04.json` — 49 findings across 16 of 19 pilot images, with an
error-type vocabulary, per-finding status, and explicit records of what was *never* reviewed. Paired
with `scripts/regression_report.py`, a prompt change could finally be measured instead of argued.

Decisions that had lived in email threads went into `docs/DECISIONS.md`.

### 3.2 Encode the policy

`docs/transcription_policy_rules.md` turns the written policy into rules R1–R23, each marked AUTO,
PROMPT, or BLOCKED. Measured against the existing output, **essentially none** of the checkable rules
were satisfied.

`prompts/loc15_v4_*` encodes them, using the policy's own worked example as the few-shot.
`scripts/policy_lint.py` enforces the mechanical subset — the substitute for a reviewer who is no
longer here.

### 3.3 Fix the vocabularies

`vocab/aat_genre.txt` did not exist, though `--aat-genre` had pointed at it all along: genre
enforcement had been a silent no-op. It now holds 42 terms, each verified as an AAT *preferred* label
against the Getty SPARQL endpoint. Six of forty candidates failed verification and were corrected —
`forewords` is an alternate label, not a preferred one.

### 3.4 Move to a current model

The deciding factor was not reasoning ability. Tile-resizing models reduce an image's shortest side to
768px before reading it, so 5222×6762 archival scans were being read at roughly 768×995 — which is
where the misread names and dates came from. `detail: "original"` requires GPT-5.6, so all three cost
tiers are GPT-5.6.

### 3.5 Then everything the scale demanded

One record per archival item rather than per scan. Per-call cost accounting. Failure handling that
does not leave holes. Vocabularies that never guess. See `docs/DECISIONS.md` D-009 through D-013.

---

## 4. Faults found by measuring, not reasoning

Every one of these was silent. The output looked complete in all of them.

| Fault | How it surfaced | Consequence had it shipped |
|---|---|---|
| `field_confidence` declared as a free-key map, which strict structured outputs cannot express | Reading the schema before making it mandatory | Came back `null` on all 19 records without erroring; the whole triage signal dead |
| Images above ~32 MP are not read but **fabricated** | Confidence 25 on one item, then opening the image | An invented document passing every automated check |
| The OCR fallback fired on every image and returned nothing | 37% of a run's cost with no output to show | `pytesseract` was never installed, so local OCR silently no-opped and the billable fallback always triggered; its token budget was consumed by reasoning |
| `MAX_OUTPUT_TOKENS = 4096` too low for a reasoning model | One item spent all 4096 on reasoning, returned nothing, forced a retry | Silent truncation on longer documents |
| Per-item cost differenced from a global running total | A printed $0.64 against a ledger $0.09 | Every cost figure in a report to a supervisor wrong; ledger was right all along |
| Item grouping missed letter-suffixed accession numbers | Unexpected item ids in the run manifest | Two items split into one record per page |
| Output naming broke the upload sheet's primary key | Comparing against the April spreadsheet | `Identifier` and `Preservation Filename` both wrong for every single-page record |
| `contributors` had **no definition in the prompt** | Names visible in transcripts appearing in no field | 26 of 128 records lost personal names entirely — a primary access point |
| Rebuild silently wiped Tier 3 | Testing the *reported* bug, which did not reproduce | Archival placement destroyed by the expand-vocabulary-then-rebuild workflow |
| 14 of 21 reported policy violations were the checker's own false positives | Reading the flagged transcripts instead of the count | Sending a colleague a 21-item review queue that should have been 3 |

## 5. Two wrong turns worth recording

**A documented bug that did not exist.** `KNOWN_ISSUES.md` reported that rebuild strips transcripts,
with a "suspected cause". It does not: 19 baseline files and current output rebuild losslessly. The
real culprit was a v3 run whose prompt had no transcript rules. But testing the false report found a
*real* bug — rebuild wiping Tier 3 — which would have bitten later, at the worst possible moment.
**Reproduce before fixing, and keep testing after the report fails to reproduce.**

**A prompt fix that made things worse.** All 15 low-confidence records were handwritten, marked
`[handwritten] [illegible]`. The hypothesis was that v4's refusal-to-guess rule was over-suppressing,
so a v5 prompt relaxed it. Output tripled — and was **invented**: `SEP 19 1930` for a stamp reading
1950, `During the Christmas holidays I spent the week at home` for a sentence reading `on the coming
home-coming day`. The same item on the top tier with the **unchanged** prompt produced 2,323
characters of accurate text. The constraint was model capability; v4's refusal was correct. v5 was
deleted.

## 6. Results

| | April 2026 | July 2026 |
|---|---|---|
| Model | gpt-4o at ~768px effective | GPT-5.6, full resolution |
| Records | 19 (per file) | 128 (per archival item, 316 images) |
| Policy violations | 42 errors | 0 errors |
| Human-review findings resolved | 0 / 30 | 11 / 30 |
| Subject vocabulary | 47 terms | 83, authority-verified |
| Genre vocabulary | missing file | 42 terms, 42/42 verified |
| Cost accounting | none | per call, per item, per tier |
| Failure handling | wrote a complete-looking empty record | writes nothing, retries on resume |
| Tests | 9 | 48 |

Delivered: 128 records over 316 images for **$28.38** ($0.22/record, $0.09/image), 10 flagged for
human review. **$34.25** across every run including the pilots and diagnostics.

## 7. What is still open

Stated plainly, because the batch is a staging deliverable and not a finished one.

- **Only 4 of 128 records were checked against their source image by a human.** The other 124 rest on
  the model's self-reported confidence, deterministic policy checks, and a fixture covering only the
  19 pilot images. 109 AAMU records have had no human verification at all.
- `field_confidence` is the model scoring itself. It correlated well where it was checked, but a
  confidently wrong record will not be flagged.
- 8 columns are empty pending archival placement information; 6 more the pipeline cannot produce.
- 19 place headings await confirmation. The FAST suggest endpoint cannot verify geographic headings
  reliably — it failed on `Pennsylvania--Philadelphia` — so they were not written to the authority
  file on an unreliable check.
- `AAMU-0074` remains poor at confidence 30 even on the top tier.
- 4 R18 policy warnings were never investigated. Given the false-positive record, they may be a third
  such class.
- `pytesseract` is still not installed, so `processing_confidence` is `0.0` and meaningless on every
  record. `processing_confidence_valid: false` marks this.
- Per-item Tier 3 is still global to a run, so a batch spanning several boxes needs one run per box.
