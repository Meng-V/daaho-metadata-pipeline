# Project Decisions

Standing decisions for the DAAHO metadata pipeline. Each entry is binding until superseded here.
Add new decisions at the bottom; do not silently edit past ones.

**Why this file exists:** as of July 2026 both student workers who held the working context
(pipeline author and review assistant) have departed. Every decision below was previously
recorded only in email threads or in one person's head. Anything not written here is lost.

---

## D-001 — Title capitalization: sentence case

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

Titles use **sentence case**: capitalize the first word and proper nouns only.

This matches the archivist MAP review ("the model did a great job creating titles with
sentence capitalization") and the behavior already implemented in
`prompts/loc15_v2_system.txt`. No change to the prompt is required.

**Not adopted:** the review assistant's suggestions to capitalize mid-title words
(`Upham Itinerary document`, `Tosses His Dime`, `COLLEGE AID LETTER #4`). See
`tests/fixtures/jinming_review_2026-04.json` findings `0692-1`, `0698-1`, `0708-1`, which are
marked `superseded_by_decision`.

**Open caveat:** two of those three (`0698-1`, `0708-1`) are titles derived from text printed on
the item itself — a newspaper headline and an all-caps document heading. The reviewer may have
been applying "retain original capitalization" rather than expressing a title-style preference.
D-001 resolves them as sentence case for now. Revisit if headline-derived titles turn out to be
common in the larger batch.

**Unchanged by this decision:** the date suffix format (`, 19 October 1937` — day month year,
no comma inside the date) is already correct and is not part of D-001.

---

## D-002 — Creator inference from collection context is retained, but must carry its evidence

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — implementation pending

`prompts/loc15_v2_system.txt` instructs the model: *"If the document is signed only with a title
(e.g., 'President'), identify the actual person from context. For Miami University correspondence
from 1928-1945, the President was Alfred H. Upham."*

This rule is **kept**. It is a defensible cataloging inference, and the archivist MAP review does
not prohibit inference — it requires that values be verifiable.

**But** the inference must record its basis. The review assistant wrote *"I have no idea where
this information came from"* against six `creator` values, all of them `Upham, Alfred H.`
Provenance is currently a static per-field-name label map (`app/schema.py`
`FIELD_PROVENANCE_LABELS`), not per-item evidence, so there is nothing for a cataloger to check.

**Required:** each inferred value carries either a source quotation from the item or an explicit
inference note (e.g. *"signed 'President'; identified as Alfred H. Upham from the collection's
1928–1945 date range"*).

**Traceability.** Comparing the two CSV versions in this repo pins down exactly when this was
introduced:

| Item | `final_metadata.csv` (Jan 2026) | `out/final_metadata_2026-04-27_handoff.csv` |
|---|---|---|
| BC-0694, 0695, 0696, 0699, 0710, 0711, 0714 | `anonymous` | `Upham, Alfred H.` |
| BC-0716 | `anonymous` | `Royal Thai Legation` |
| BC-0697 | `anonymous` | *(empty)* |
| BC-0934 | `Miami University` | *(empty)* |

The six items the reviewer flagged are all in the first row. BC-0697 and BC-0934 are
**regressions** — a value was present in January and is gone in April. Nobody caught these at
the time; they are not in any review document.

---

## D-003 — Handwritten material is out of scope for AI transcription

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — triage not yet run

DAAHO Transcription Policy §2 (Methods): *handwritten documents should be transcribed
**manually**; OCR "can be used to aid in transcription of **typed** documents."*

AI transcription of handwriting is therefore not sanctioned by project policy, and it is
empirically where the worst errors occur — the AI invented the surnames `Murry` (BC-0716) and
`C V Hibbard` (BC-0718) out of handwritten passages the reviewer judged unreadable. The second is
potentially circular: BC-0718's `creator` is `Hibbard, C. V.`

**Required before committing to a batch size:** triage incoming images into typed / handwritten /
mixed. Typed items go through the pipeline; handwritten items go to a manual queue. If the
handwritten share is large, project scope must be renegotiated or a documented policy exception
recorded here.

---

## D-004 — Unreviewed AI output must not be published as final

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

DAAHO Transcription Policy §4: transcriptions *"must be reviewed and proofread by a person other
than the original transcriber"* before finalization.

With the AI as transcriber, the project lead is a valid reviewer under §4 — solo review is
policy-compliant. The binding constraint is **hours, not staffing**. At roughly 10 minutes per
item of careful comparison against the source image, 300 items is ~50 hours.

Therefore: output that has not been through human review stays in a staging layer, labeled
AI-generated and unproofread. It is not published to the Digital Edition as final metadata.

The engineering consequence: the pipeline's job is to **reduce human minutes per item**, not to
eliminate review. Deterministic policy checks (see `docs/transcription_policy_rules.md`) exist to
spend the project lead's limited attention only where a machine cannot decide.

---

## D-005 — Three name spellings left unadjudicated

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

Five name spellings were flagged for human confirmation against the source images. Two were
resolved by the review assistant before departing:

- **BC-0703** — `Swadi Nitibon` → **`Swasdi Nitibhon`** ✅
- **BC-0934** — `Rose Choi` → **`Rosa Choi`** ✅

Three were never adjudicated and the project lead has explicitly **declined** to adjudicate them:

- **BC-0688** — `Sukhsvasti` vs `Sukhsvati`
- **BC-0710** — addressee `Murray Sheehan` vs `Murray Seehan`
- **BC-0897** — `Wing Kong Chong` vs `Wing Kong` (is it a three-part name?)

These values remain **unverified AI output**. They are recorded as
`deferred_no_human_decision` in `tests/fixtures/jinming_review_2026-04.json` so that a later
reader does not mistake them for verified. They must not be counted as passing in any regression
report.

BC-0688, BC-0714, and BC-0897 additionally have **no human review at all** — the review pass
covered 16 of the 19 pilot images.

---

## D-006 — Strikeout and underline convention: TEI-mappable bracket markers

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — implemented in `prompts/loc15_v4_*.txt`

Transcription Policy §2 requires retaining strikeouts and preserving underlines. The policy assumes
a Google Docs deliverable where these are real character formatting. The pipeline's `transcript`
field is a plain JSON string and cannot carry formatting, so the project adopts inline markers:

| Feature | Marker | Maps to TEI |
|---|---|---|
| Strikeout / deletion | `[struck: crossed-out words]` | `<del>` |
| Underline | `[underlined: the underlined words]` | `<hi rend="underline">` |
| Author insertion | `^carets^` (already in policy §2) | `<add place="above">` |
| Illegible | `[illegible]` | `<gap reason="illegible"/>` |
| Partially readable | `[unclear]` | `<unclear>` |

**Rationale for the bracket form over embedded TEI/XML or Markdown:**

1. **It stays inside the policy's own idiom.** §2 already establishes `[illegible]`,
   `[correction]`, `[expansion]`, `[redacted]`, `[page N]`, `^carets^`. Introducing a second
   syntax family (`~~strike~~`, `<del>`) would mean two conventions in one field.
2. **It round-trips to TEI.** DAAHO produces a *Digital Edition*, so TEI encoding is a plausible
   destination. Each marker above has a single unambiguous TEI target, so conversion is a
   mechanical transform rather than a re-transcription.
3. **It survives plain-text handling.** The transcript passes through JSON, CSV export, and a
   Google Docs paste. Angle brackets get escaped or eaten; square brackets do not.

Not adopted: raw TEI/XML inline (unreadable for a cataloger proofreading in Docs, and invalid as
a fragment), and Markdown (`~~`, `__`) — no archival standing and collides with underscores in
transcribed text.

`scripts/policy_lint.py` warns on `~~`, `<s>`, `<del>`, `<u>`, and `__text__` and points at this
decision.

---

## D-007 — `[illegible]` and `[unclear]` both apply to written documents

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — implemented in `prompts/loc15_v4_*.txt`

Transcription Policy §2 (written documents) specifies `[illegible]`; `[unclear]` appears only in §3
(audio/film). The review assistant used both on written documents, and the distinction is useful.
Both are accepted, with this split:

- **`[illegible]`** — the word or region cannot be read at all, including text lost to damage,
  tearing, or missing page area.
- **`[unclear]`** — partially readable but no reading can be committed to. A partial reading may
  precede the marker: `September 1? [unclear]`, `Straits Sett ments [unclear]`.

One marker per unreadable word; consecutive gaps are `[illegible] [illegible]`, per the worked
example in policy §6.

**Absolute rule, in both cases:** never reconstruct what the text probably said. A plausible
reconstruction is worse than a marked gap, because a cataloger cannot distinguish it from a real
reading. This is the failure mode behind findings `0697-8`, `0697-9`, `0697-10`, `0926-1`, and the
invented surnames in `0716-2` and `0718-2`.

---

## D-008 — Inferred values are flagged via `field_confidence`, pending a real evidence field

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — interim measure

D-002 requires that inferred values carry their evidence. A proper implementation needs a new
schema slot (per-field source quotation or inference note), which is a change to
`app/schema.py` `LOC15_SCHEMA` and is not yet made.

Interim: `field_confidence` already exists in the schema and was unused — null in all 19 outputs.
`prompts/loc15_v4_system.txt` makes it mandatory and binds the scale so that **1–39 means inferred
from collection context rather than read from the item**. Any creator identified via the Upham rule
must score in that band.

**Schema fix required to make this work.** The field was declared as a free-key map
(`additionalProperties: {type: integer}`). OpenAI structured-outputs **strict mode** requires every
object to set `additionalProperties: false` and list all properties in `required`, so an
arbitrary-key dictionary cannot be expressed. That is why the field came back `null` on all 19
items — it was structurally unfillable, and it failed silently rather than erroring.

`app/schema.py` now declares eleven explicit nullable keys via `FIELD_CONFIDENCE_FIELDS` —
`title, date, place, creator, contributors, correspondents, transcript, description, subjects,
genre, language` — the fields a reviewer actually triages on. Existing outputs with
`field_confidence: null` still validate, so the baseline in `out/` is unaffected.

This does not satisfy D-002 — a number is not evidence. It does give a triage signal today, which
is what D-004 needs: it lets a solo reviewer sort by confidence instead of re-checking every field.
Replace with a real evidence field when the schema is next revised.

---

## D-009 — Three GPT-5.6 tiers, chosen for image fidelity, with per-image cost accounting

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active — implemented

### Why GPT-5.6 and not a cheaper family

The deciding factor is **not** reasoning ability, it is whether the model sees the page.

Per the [OpenAI vision guide](https://developers.openai.com/api/docs/guides/images-vision),
GPT-4o and GPT-4.1 tile-resize every image: scale to fit 2048×2048, **then reduce the shortest
side to 768px**. This collection's scans are up to 5222×6762, so the model that produced the
current baseline was reading a page rendered at roughly **768×995**. A full page of 1930s
typescript at that size does not support reliable name or date reading.

That is very likely the root cause of a whole class of findings in
`tests/fixtures/jinming_review_2026-04.json` — `Nakku`/`Nakaku` (0692-2),
`Honack's`/`Hosack's` (0697-6), `Jeni Van Ausdal`/`Jean Van Ausdall` (0697-2),
`28`/`26 February` (0713-1), `Rose`/`Rosa Choi` (0934-4), and the invented text in damaged
regions (0697-8/9/10). **No prompt change fixes an input the model cannot resolve.**

`detail: "original"` preserves input dimensions and is available on GPT-5.6 (and, with an
undocumented patch budget, GPT-5.4). All three tiers below are GPT-5.6 for that reason.

### The tiers

Defined in `app/cost.py`; select with `--tier`. Prices per 1M tokens, verified 2026-07-25.

| Tier | Model | Input | Cached | Output | Use for |
|---|---|---|---|---|---|
| `luna` | `gpt-5.6-luna` | $1.00 | $0.10 | $6.00 | Bulk: clean typed documents, good contrast, no handwriting |
| `terra` | `gpt-5.6-terra` | $2.50 | $0.25 | $15.00 | **Default**: typed with some difficulty, newspaper clippings |
| `sol` | `gpt-5.6-sol` | $5.00 | $0.50 | $30.00 | Hard: handwriting, damage, dense multi-column, linter-flagged reruns |

The point of three tiers is that a 300-image batch is not uniform. Routing the easy majority to
`luna` and reserving `sol` for the genuinely hard minority is what makes the batch affordable
without giving up quality where quality is at risk.

### gpt-4o support removed

Runtime support for `gpt-4o` (the previous default) was dropped rather than kept as a comparison
path. It cannot do the core task — the 768px tile-resize above — so it would never be used in
production, and keeping it meant maintaining a second parameter branch plus an *estimated* price
entry, since gpt-4o is no longer on OpenAI's main pricing page. Estimated rates in a budget report
are a liability.

The one argument for keeping it was isolating how much quality gain came from the v4 prompt versus
the model change. That experiment does not change any decision — v4 + GPT-5.6 is the answer either
way — and the old pipeline remains reproducible from git history (`out/` baseline is committed at
`0efaf88`). An unpriced model now triggers a loud stderr warning instead of silently ledgering
$0.00.

### Cost accounting

Two things cost money per image and are ledgered separately:

- `extraction` — the main vision + metadata call. Always runs.
- `ocr_fallback` — `transcribe_with_model()`, a second vision call made **only** when Tesseract
  returns under 25 characters. Skipped on most typed documents.

Tesseract itself runs locally and is free; it is written to the ledger as a zero-cost `tesseract`
row so reports state that explicitly instead of leaving it ambiguous.

Every run appends to `<out-dir>/cost_ledger.jsonl` (append-only, survives a crash, so a partial
run is still accurately accounted). Retried attempts are billed too — the ledger records each
attempt, not just the successful one. Per-item cost is also written into each output envelope at
`context.cost_usd`.

Report with `python3 scripts/cost_report.py --project 300`, which gives per-image, per-tier,
per-call-type, and a projection.

### D-009a — Images are capped at 15 megapixels before sending

Added 2026-07-25 after the first full v4 run.

`detail: "original"` is documented to preserve input dimensions, but empirically the model stops
reading very large scans and starts **fabricating** plausible period documents. Measured on the
19-image pilot, by `field_confidence.transcript`:

| Image size | Items | Transcript confidence |
|---|---|---|
| ~15 MP (3400×4400) | 13 | **85–99** |
| 31.5 MP (4914×6412) | 1 | 91 |
| 35.3 MP (5222×6762) | 1 | 57 |
| 35.6 MP (5250×6776) | 2 | 65 and **25** |
| 39.5 MP (5356×7377) | 1 | 72 |

The confidence-25 item (BC-0934) invented an entirely different document — see `KNOWN_ISSUES.md`.
Re-running it at the `sol` tier produced a *different* fabrication, proving this is not a model-
capability problem. Capping to 24 MP still fabricated; capping to **15 MP** recovered the real
document. `app/ocr.py` `MAX_PIXELS` therefore defaults to 15 MP, overridable with
`MAX_IMAGE_PIXELS_SENT`.

15 MP is still roughly 4× the linear resolution that tile-resizing models impose (768px shortest
side), and downscaling reduces cost too, since image tokens scale with area.

**Honest limit:** the cap stops the fabrication but does not make BC-0934 accurate — it still
misreads `-- Miami University` as `-- initial nationality` and marks the legible `Rosa Choi` line
`[illegible]`. The gpt-4o baseline read that line better. That item belongs in the human queue, and
its confidence score says so.

### D-009b — The vision OCR fallback is off by default

Added 2026-07-25. Enable with `--ocr-fallback`.

The fallback (`transcribe_with_model`) accounted for **$1.16 of the $3.10** first full run — 37.3%
— and two root causes made all of it waste:

1. **`pytesseract` is not installed in the active environment** (it *is* in `requirements.txt`).
   `tesseract_ocr()` therefore returns `("", 0.0)` for every image, the `< 25 characters` condition
   is always true, and the fallback fired on **19 of 19** items. The free local OCR has never run.
   As a side effect, `context.processing_confidence` has been meaningless throughout.
2. **Its 900-token output cap was consumed by reasoning.** Across the 19 calls, 82% of output
   tokens were reasoning tokens; BC-0692 and BC-0926 spent all 900 on reasoning and returned an
   **empty** transcript while being billed in full.

The extraction call already reads the image at `detail: "original"`, so the fallback is redundant
for typed documents. The cap was raised 900 → 4000 for the case where it is explicitly enabled.

To restore local OCR: `pip install -r requirements.txt && brew install tesseract`.

### D-010 — Controlled vocabularies never guess: unmatched terms are left empty and flagged

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

`_enforce_approved_subjects()` used to fall back to `"Correspondence"` — or, failing that,
`sorted(approved_subjects)[0]`, whichever approved term sorted first alphabetically — whenever no
approved term matched. `_enforce_approved_genre()` did the same with `"correspondence"`.

On the 19-image pilot this was invisible. At 300 images it is actively destructive: the subject
vocabulary holds **47 terms** and the place list **9**, both sized for the pilot, so any item whose
subject matter falls outside that coverage receives an unrelated term — carrying the same
`AI-Proposed Subject` provenance label as a real reading. Worse, an extraction that returned nothing
came out the other side holding `subjects: ["Correspondence"]`.

Now:

- Unmatched subject and genre terms are **rejected by name** in `policy_notes`, and the field is
  left empty.
- A field left empty this way records `NEEDS VOCAB REVIEW`, which `run_manifest.jsonl` surfaces per
  item as `needs_vocab_review`.
- Place tokens dropped during canonicalization are recorded too. Previously a two-token place where
  only one matched was silently rewritten to the single match.
- **Deliberate asymmetry:** when *no* place token matches, the original value is kept unvalidated
  rather than blanked. An unvalidated place a cataloger can see beats an empty field; for subjects
  and genre the reverse holds, because a wrong controlled term is worse than none.

An empty field a cataloger can see is better than a wrong one they cannot. Pinned by
`tests/test_batch_safety.py`.

**Still open:** `vocab/fast_places.txt` (9) and `vocab/fast_subjects.txt` (47) remain pilot-sized.
This decision makes their under-coverage *visible* instead of silently wrong; it does not fix it.
Expect a large `needs_vocab_review` count on the first real batch, and grow the lists from it.

---

### D-011 — A failed item writes no output, and every run leaves a manifest

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

`extract_metadata()` returned `{}` on failure. `process_path()` then ran that empty dict through
policy enforcement — which stamped a fallback subject onto it (D-010) — and wrote a full,
normal-looking envelope. Because resume logic is "skip if the output file exists", **one transient
rate limit became one permanent, invisible hole** that looked processed forever.

Three changes:

1. `extract_metadata()` now raises `ExtractionFailed` instead of returning `{}`. A failure cannot be
   mistaken for a result by any caller.
2. On failure `process_path()` writes **no** `.loc15.json`. It writes a sibling `.failed.json` with
   the error, the attempts billed, and the cost spent, then returns `failed`. Rerunning the same
   command retries exactly the failures. A later success deletes the stale marker.
3. Retries went from one immediate re-fire to **5 attempts with exponential backoff and full
   jitter**, honoring `Retry-After` when the server sends it. Rate limits and 5xx are retried;
   401/400 are not, since hammering an auth or schema error only wastes money.
   Tunable via `LLM_MAX_ATTEMPTS`, `LLM_BACKOFF_BASE`, `LLM_BACKOFF_CAP`.

Every run writes `<out-dir>/run_manifest.jsonl`, one record per item: `ok` / `skipped` / `failed` /
`missing`, plus per-item cost, `transcript_confidence`, and `needs_vocab_review`. The run prints an
outcome tally and lists failures at the end. Previously the only evidence a run had finished was the
presence of output files, which said nothing about what went wrong.

`--workers N` runs items concurrently (default 1; 4–6 is reasonable). `CostLedger` and `RunManifest`
are both lock-guarded, since a torn concurrent write would corrupt the accounting.

### Payload fix made at the same time

`app/ocr.py` `pil_bytes()` re-encoded every image to full-resolution PNG, turning a 3.0 MB JPEG
into a 25.8 MB PNG and a **34.4 MB base64 request body** — then the server downscaled it to 768px
anyway. Now the original file bytes are sent for already-supported formats, with the correct MIME
type. Same image: **4.0 MB**, an 8.6× reduction, with more detail reaching the model, not less.
Only TIFF/BMP are converted, and only those may be downscaled (12 MB cap).
