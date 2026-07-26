# Adopting This Pipeline at Your Institution

A guide for a developer or digital-collections technologist bringing this to a different archive.

This is not a general-purpose tool. It encodes one institution's cataloging standard, one
transcription policy, and one collection's quirks. Roughly 70% of it transfers unchanged; the other
30% is the part that makes the output correct for *your* archive, and skipping it produces confident
nonsense. This document is ordered so the 30% comes before you spend money.

Everything here was learned the expensive way — see `docs/DECISIONS.md` for the reasoning behind each
design choice and `docs/OVERHAUL_2026-07.md` for what went wrong before it was right.

---

## 0. What you are getting

A batch pipeline that reads scanned archival documents and produces one metadata record per item:
a title, date, creator, correspondents, places, controlled subject and genre terms, a policy-
compliant transcript, and a per-field confidence score. Output is JSON per item plus a CSV shaped
like a collection-management upload sheet.

What it is **not**: a finished cataloging system. There is no UI, no authentication, no queue, no
database. It is a script you run over a directory of images, and a set of guardrails that keep it
from inventing things.

**Cost, measured:** about **$0.09 per image** / **$0.22 per item** on a mid-tier model with
full-resolution reading. A 316-image batch cost $28.38. Budget 20–25% on top for the pilot and
diagnostic runs you will need.

---

## 1. Decide these five things before writing any code

Every one of these cost us a wrong batch or a wasted run.

### 1.1 What is an "item"?

**Not a file.** Our 316 images were 128 archival items: multi-page letters, recto/verso pairs, and one
36-page bound volume. Processing per file mints a separate title, date and creator for every page,
and gives one sheet two records that can contradict each other.

Your filenames encode this relationship and you must teach the code to read them. Ours:

    AAMU-0003_Page_1.jpg .. _Page_15.jpg   one 15-page document
    AAMU-0001_Recto.jpg / _Verso.jpg       two sides of one sheet
    01_AAMU-0069_Front_cover.jpg           a sequence-numbered volume
    AAMU-0073a / 0073b / 0073c             letter-suffixed sub-items under one accession

**Where to change it:** `app/grouping.py`. Rewrite `ITEM_NUMBER`, `SEQ_VOLUME`, `ITEM_LABEL` and
`_sort_key` for your convention, then run `scripts/triage_batch.py <dir>` and check the item count
against what a cataloger would say. `tests/test_grouping.py` shows the cases worth pinning, including
the ones we got wrong first (letter suffixes, page ranges like `Page_2-3`, a stray space in
`Page_ 8`).

### 1.2 What is your transcription policy?

Ours is not verbatim: **retain the original, then mark every edit in brackets** —
`Sincerly [Sincerely] yours`. Letterhead is skipped, line breaks are not mimicked, illegible text is
`[illegible]` and never guessed, each page opens with `[page N]`.

If you have no written policy, get one before running a batch. Without it the model behaves as a
copy editor: it silently fixes source misspellings and fills damaged passages with plausible prose,
and you cannot tell which words came from the document.

**Where to change it:** `docs/transcription_policy_rules.md` extracts our policy into numbered rules
marked AUTO (a checker can enforce it), PROMPT (the model must be told), or BLOCKED (not expressible
in plain text). Redo that table for your policy, then rewrite the TRANSCRIPT section of
`prompts/loc15_v4_system.txt` and the corresponding checks in `scripts/policy_lint.py`.

### 1.3 Which authority files, and are your vocabularies big enough?

We validate subjects and places against FAST and genre against the Getty AAT. Model output is
matched against local approved lists in `vocab/`; anything unmatched is **rejected by name and the
field left empty** — never replaced with a guess.

Our lists started at 47 subjects and 9 places, sized for a 19-image pilot. On a 316-image batch, 97
of 135 records had at least one term rejected. That is the system working, but plan for it: your
first real batch is also your vocabulary-discovery run.

**Where to change it:** `vocab/*.txt` (one term per line, `#` comments allowed inline), and
`--approved-subjects` / `--approved-places` / `--aat-genre` if you use different filenames. Use
`scripts/verify_aat_terms.py` and `scripts/expand_vocab_from_run.py` to grow the lists from a run's
rejections, verified against the authority rather than typed from memory.

### 1.4 Who proofreads, and what does "published" mean?

Our policy requires human proofreading before a transcript is final. We could not proofread 128
records, so the batch is a **staging** deliverable and nothing is published as final without a human
signing off on that record.

Decide this explicitly. The pipeline's `field_confidence.transcript` score is the triage signal that
makes a small review budget go far — on our batch it correctly isolated 15 problem records out of
128 — but it is the model scoring itself, not an independent measure. **A confidently wrong record
will not be flagged.**

### 1.5 Which fields will you leave empty on purpose?

Archival placement — box, folder, series, repository, rights — must never be inferred. A wrong box
number is worse than an empty field, and it is invisible once it is in a catalog. Ours ship empty
because nobody had the information.

**Where to change it:** `TIER3_FIELDS` and `TIER3_DEFAULTABLE_FIELDS` in `app/schema.py`. Supply real
values with the `--box` / `--folder` / `--series` flags, or per item via a manifest you write. Note
the gap: those flags are **global to a run**, so a batch spanning several boxes needs either one run
per box or code you add.

---

## 2. Set up

Python 3.10+.

```bash
git clone <your fork>
cd daaho-metadata-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your OPENAI_API_KEY in it
python3 -m pytest tests/ -q   # 48 tests, no API calls, no key needed
```

Optional: `brew install tesseract` (or your platform's package) for free local OCR. Without it
`tesseract_ocr()` silently returns nothing — which in our case made a billable fallback fire on
every single image. The pipeline records `processing_confidence_valid: false` when it is missing, so
check that field rather than trusting the score.

---

## 3. Adapt, in this order

### 3.1 Grouping — free to iterate

Rewrite `app/grouping.py` for your filenames. Then:

```bash
python3 scripts/triage_batch.py /path/to/images --done-dir out_batch --csv triage.csv
```

No API calls. Confirm: the item count matches a cataloger's count, no duplicate content, and you know
how many files exceed the pixel cap. **Do not proceed until the item count is right.**

### 3.2 Schema and controlled vocabularies

`app/schema.py` holds `LOC15_SCHEMA` (what the model may return), the tier lists (what is trusted at
what level), and `FIELD_CONFIDENCE_FIELDS`. Map these to your metadata application profile.

Two constraints that will bite:

- **OpenAI structured-outputs strict mode requires every object to set
  `additionalProperties: false` and list all properties in `required`.** A free-key map cannot be
  expressed. We lost `field_confidence` to this for an entire batch — it came back `null` on every
  record and failed *silently*. If you add an object field, verify it round-trips on one real call.
- `export_csv.py` maps schema fields to your upload sheet's column names. Point `--template` at a CSV
  whose header row is your real sheet.

### 3.3 Prompts

`prompts/loc15_v4_system.txt` is the cataloging standard as instructions; `_user.txt` is the
per-item contract and a self-check list. Adapt: the TITLE format, the LOCATION convention, the
CREATOR rules, the DESCRIPTION grounding restrictions, and the TRANSCRIPT section from §1.2.

Use a **worked example from your own policy** as the few-shot. Ours is the example transcript from our
transcription policy — same era and genre as the collection, and it demonstrates the bracket
convention, `[page N]`, and paragraph reflow in one passage. A generic example teaches generic output.

Version prompts by filename (`loc15_v5_*`) and select with `--prompt-version`. Keep the old one until
the new one is measured better.

### 3.4 Institution-specific inference — read this before copying it

Our prompt contains:

> *If the document is signed only with a title ("President"), identify the person from context. For
> Miami University correspondence from 1928–1945, the President was Alfred H. Upham.*

This is **our** collection's fact and it is wrong for yours. It is also the single largest source of
"where did this come from?" complaints in our human review — six records got a creator that appears
nowhere on the page. If you keep this pattern, keep the confidence-scoring rule with it: an inferred
value must score 1–39 so a reviewer can find it.

Grep the prompt for `Miami`, `Upham`, `Ohio--Oxford`, and `DAAHO` before your first run.

---

## 4. Pilot before batch

### 4.1 One image

```bash
python3 -m app.main --in /path/to/one.jpg --out ./out_probe --tier terra --prompt-version loc15_v4
python3 scripts/cost_report.py --ledger out_probe/cost_ledger.jsonl --project 300
```

This gives you **your** real per-image cost, which depends on your scan resolution. It also proves
the model accepts your schema, and that any object field you added actually populates.

### 4.2 Twenty images, then read them against the originals

Open the scans. Compare them to the transcripts, by eye, yourself. There is no substitute and it is
where every real problem in our pipeline surfaced: a fabricated transcript that every automated check
passed, a creator attributed to the wrong signatory, names present on the page that landed in no
field at all.

Build a fixture from whatever human review you have — see
`tests/fixtures/jinming_review_2026-04.json` for the shape — and score against it with
`scripts/regression_report.py`. Without a fixture you are guessing whether a prompt change helped.

### 4.3 Then the batch

```bash
python3 -m app.main --in ./images --out ./out_batch --tier terra \
    --prompt-version loc15_v4 --workers 4
```

Resume is "skip if the output file exists", so rerunning the same command retries only what failed.
A failed item writes a `.failed.json` and **no** `.loc15.json`, precisely so a resume does not skip a
hole.

Then:

```bash
python3 scripts/policy_lint.py --out-dir ./out_batch --quiet
python3 scripts/cost_deliverable.py --out-dir ./out_batch
python3 export_csv.py --out-dir ./out_batch --template your_sheet.csv --output upload.csv
```

---

## 5. Model tiers and image resolution

Three tiers are defined in `app/cost.py` — cheap / default / hard. Update the model ids and prices
when they change; an unpriced model warns loudly and ledgers at $0.00 rather than failing, so a
stale table silently understates your spend.

**The resolution finding is the one to carry over.** Tile-resizing models reduce a scan's shortest
side to 768px before reading it — a 5000px archival scan becomes unreadable at the word level, which
is where misread names and dates come from. Request full-resolution reading (`detail: "original"`),
and cap the pixels you send:

| Image size | Transcript confidence, measured |
|---|---|
| ~15 MP | 85–99 across 13 items |
| 31.5 MP | 91 |
| 35 MP+ | 57, 65, **25** |

Above roughly 32 MP the model stopped reading and started **fabricating** — inventing a different
document entirely. `MAX_PIXELS` in `app/ocr.py` caps at 15 MP; re-measure for your scanner rather
than trusting our number.

**Handwriting needs the top tier.** All 15 low-confidence records in our batch were handwritten.
Relaxing the prompt's "do not guess at handwriting" rule made the model invent text; running the
*unchanged* prompt on the strongest tier produced accurate transcription (one item went from 265
characters to 5,477, verified word-for-word against the image). Route handwritten material to the
top tier from the start. Note that a policy requiring manual transcription of handwriting is not
satisfied by a good AI transcript — it is a better starting point, not a finished one.

---

## 6. Guardrails worth keeping

These exist because the failure they prevent already happened here. Each was silent — the output
looked complete.

| Guardrail | Where | What it prevents |
|---|---|---|
| Vocabularies never guess | `_enforce_approved_subjects/_genre/_places` | An unrelated controlled term stamped on an out-of-scope item, carrying the same provenance label as a real reading |
| Failure writes no output | `ExtractionFailed`, `process_item` | One rate limit becoming one permanent invisible hole, because resume skips anything with an output file |
| Retry with backoff | `app/ai_metadata.py` | Re-firing into a rate limiter and then giving up; 401/400 are not retried, since hammering an auth error only wastes money |
| Per-call cost ledger | `app/cost.py` | Untracked spend; also bills retried and failed attempts, which a per-item estimate misses |
| Per-item cost attribution | `CostLedger.total_for` | **Never** difference a global running total around concurrent work — ours reported $0.64 for a $0.09 item |
| Run manifest | `RunManifest` | "Did it finish?" being answered by counting files |
| Confidence as triage | `field_confidence` | Needing to check all N records by hand |
| Rebuild is lossless | `rebuild_existing_outputs` | Re-applying an expanded vocabulary while wiping the archival placement you just entered |

### The limit of automated checking

`scripts/policy_lint.py` enforces the mechanically decidable rules and is what lets one person review
a batch. Know what it cannot do:

- It **cannot detect fabrication.** Our worst record — an invented document — passed every check as
  clean. Only the model's own low confidence score caught it.
- It cannot judge whether a bracketed correction is the *right* correction.
- It cannot detect omission beyond a wholly empty transcript.
- Its heuristics produce false positives. Two classes surfaced in one afternoon (18 of 21 reported
  errors were the checker's fault, not the output's). Investigate a violation class before trusting
  its count.

---

## 7. What we would not build again

- **Don't estimate batch cost from a per-item mean** if your page counts are skewed. Ours were: a
  26-item rerun cost $6.00 against a $3.60 estimate because those items happened to be the long ones.
  Sum the actual pages.
- **Don't add a second transcription pass** hoping to improve OCR. Ours was 37% of a run's cost and
  returned empty text on several items, because a reasoning model spends the output budget on
  reasoning. The main call already reads the image.
- **Don't set the output token cap tight.** Reasoning bills against the same budget and consumed
  56–100% of ours. One item spent the entire cap on reasoning and returned nothing. Output is billed
  per token used, so a generous ceiling is free.
- **Don't re-encode images.** We converted every JPEG to full-resolution PNG, turning a 3 MB file
  into a 34 MB request body — and the server downscaled it anyway.
- **Don't commit build artifacts.** A temp download directory and a generated static site sat in our
  history for months, triple-storing the same images.

---

## 8. If your repository is public

Ours is, and the source documents were not safe to commit: an email thread carrying colleagues'
addresses, and internal review documents. `docs/source/` is gitignored except its README, which lists
what belongs there and where each document's content was extracted to. Do the same before you commit
anything from a shared drive, and scan for addresses in what you *do* commit.

---

## 9. Where to look next

| File | Why |
|---|---|
| `docs/DECISIONS.md` | Every design decision with its reasoning. Read D-009 (model tiers, image resolution), D-010 (vocabularies never guess), D-011 (failure handling) first. |
| `docs/OVERHAUL_2026-07.md` | What the pipeline looked like before, what was wrong, and how each fault was found. The wrong turns are recorded too. |
| `docs/transcription_policy_rules.md` | A written policy turned into enforceable rules — the pattern to copy for your own. |
| `KNOWN_ISSUES.md` | Open problems, and one entry where the documented diagnosis turned out to be wrong. |
| `tests/` | 48 tests, all offline. `test_batch_safety.py` and `test_rebuild.py` pin the silent failures. |
