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
- **Deliberate asymmetry** *(superseded for places by D-014, 2026-10-02)*: when *no* place token
  matches, the original value is kept unvalidated rather than blanked. An unvalidated place a cataloger can see beats an empty field; for subjects
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

### D-012 — Deliberate compatibility with the April 2026 spreadsheet

**Decided:** 2026-07-25 by Meng Qu (project lead)
**Status:** active

`AI_Generated_Metadata_Test_Apr_21.xlsx` — the April sheet previously recorded as missing
— was recovered, so the current pipeline can finally be compared against the one it replaces. Both
produce the same 31 unique columns. Agreement on the 19 overlapping pilot items, after the fixes
below:

| Field | Agreement | |
|---|---|---|
| Identifier, Preservation Filename | **100%** | fixed, see below |
| Creator, Contributors | **100%** | fixed, see below |
| Decade, Language | **100%** | |
| Date | 93% | the one difference is BC-0713, where this version is correct |
| Genre | 75% | |
| Location | 62% | deliberate |
| Title, Subject (FAST), Summary, Transcript | 0–21% | deliberate |

**Three defects were fixed to restore compatibility:**

1. **Identifier / Preservation Filename.** Both derive from the output filename stem. Item grouping
   named single-page output `BC-0688` where the April sheet records `BC-0688_Recto` — breaking the
   spreadsheet's primary key. A single-page item is now named after its FILE; a multi-page item
   keeps the item id, since neither `_Recto` nor `_Verso` alone identifies the sheet.
2. **Creator on countersigned documents.** BC-0708 is issued over `S. Burns Weston, State
   Administrator` and countersigned `BY: Harry E. Rabe, Assistant Director`. This version named
   Rabe; the April sheet named Weston, and the image confirms Weston is right. The prompt now
   states that the creator is the person the document is issued FOR, with the countersigner going
   to `contributors`. Verified by re-running the item.
3. **`contributors` had no definition in the prompt at all**, so names on the page that were
   neither creator nor correspondent went nowhere — 26 of 128 items lost personal names entirely
   (`Abdul Hanif`, `Heanon Wilkins`, `Dorothy Robinson`, `Minchin A. Chang` ...). Personal names are
   a primary access point, so losing them makes those people unfindable. The prompt now divides the
   two fields explicitly: `correspondents` are the parties to the correspondence, `contributors` is
   everyone else named, and between them no legible personal name goes unrecorded.

**Genre collapsed to the general form.** `letters (correspondence)` is now mapped to
`correspondence` via `GENRE_PREFERENCE` in `app/main.py`. Both are authorized AAT preferred labels,
so this is a granularity choice, not a correctness one, and the April sheet used the general form.
Applied deterministically after vocabulary matching rather than by asking the prompt, so it is
guaranteed. **Not** collapsed: `memorandums`, `itineraries`, `telegrams`, `postcards`,
`clippings (information artifacts)`, `reports`, `prefaces` — the April sheet called all of these
`correspondence`, but a memorandum is not a letter and flattening them would lose real distinctions.

**Divergences kept deliberately:**

- **Location** adds the creation/sender place first (`Ohio--Oxford; Kansas--Wichita`). Required by
  the archivist MAP review, which asked for both sender and recipient locations.
- **Correspondents** use inverted form without honorifics (`Sheehan, Murray`, not
  `Mr. Murray Sheehan`) and record BOTH parties, where the April sheet recorded the recipient only
  in direct form. Kept inverted because the April handoff had already moved `Creator` to inverted
  form, and one sheet with two name conventions would complicate authority linking later. Kept both
  parties because the field is plural and the sender is usually also the creator, so having both
  lets a cataloger cross-check.
- **Title, Summary, Transcript, Subject (FAST)** diverge because v4 rewrote them on purpose:
  sentence case (D-001), the transcription policy (D-006/D-007), and a vocabulary grown from 47 to
  83 terms with the guessing fallback removed (D-010).

**Not adopted from the April sheet:** its `Correspondents` column recorded a group
(`Presidents of Ohio Colleges and Universities`), a bare title (`President of Miami University`),
and an award recipient on a form (`Rose Choi` — also misspelled; the image reads `Rosa`). None of
those are parties to a correspondence. They now go to `contributors` where they belong, or are
omitted where they name no person.

### D-013 — Handwritten items route to the `sol` tier; the refusal-to-guess rule stays

**Decided:** 2026-07-26 by Meng Qu (project lead)
**Status:** active

All 15 low-confidence records in the batch turned out to be **handwritten**. Their transcripts were
mostly `[handwritten] [illegible]`: AAMU-0014 produced 265 characters from six written pages,
AAMU-0073a 339 from two.

**A hypothesis that turned out to be wrong.** The first theory was that v4's rule 18 — *"DO NOT GUESS
AT HANDWRITTEN NAMES OR WORDS ... output [handwritten] [illegible] and nothing else"* — was
over-suppressing, and that the model could read the cursive if allowed to try. A v5 prompt relaxed
the rule, separating "do not invent what you cannot see" from "do not attempt cursive".

It made things worse. On AAMU-0073a, v5 produced 1,202 characters instead of 339 — and **invented
them**: `SEP 19 1930` for a stamp reading 1950, and `During the Christmas holidays I spent the week
at home` for a sentence that reads `on the coming home-coming day`. Pushed to try harder at a tier
that cannot read the script, the model fills the gap with plausible prose. **v4's refusal was
correct**, and v5 was deleted.

**The binding constraint is model capability, not the prompt.** The same item on `sol` with the
unchanged v4 prompt produced 2,323 characters of accurate text — verified line by line against the
image, including `I am a Miami graduate of Class of '28`, `the Institute of Public Administration in
N.Y.C.`, and the names `Dr. Shideler, Mr. A.K. Morris`.

Re-running all 15 on `sol`: **confidence rose on 15 of 15**, and the human-review queue fell from 15
items to 10. AAMU-0014 went from 265 characters to 5,477, spot-checked word-for-word against the
image — real content, with `[unclear]` correctly flagging only the Dutch ship name it could not
resolve. Cost $4.53 against $2.04 at `terra`.

This is the tiering from D-009 working as designed: the expensive tier is worth it on the minority of
items that need it, not on the batch. Run handwritten material on `sol` from the start.

**What this does not change:** per D-003, the transcription policy still says handwritten documents
should be transcribed manually. `sol` makes the AI transcript a much better *starting point* for that
work; it does not make it a finished transcript. All 10 remaining low-confidence items, and
AAMU-0074 (30) in particular, still need human eyes.

### Payload fix made at the same time

`app/ocr.py` `pil_bytes()` re-encoded every image to full-resolution PNG, turning a 3.0 MB JPEG
into a 25.8 MB PNG and a **34.4 MB base64 request body** — then the server downscaled it to 768px
anyway. Now the original file bytes are sent for already-supported formats, with the correct MIME
type. Same image: **4.0 MB**, an 8.6× reduction, with more detail reaching the model, not less.
Only TIFF/BMP are converted, and only those may be downscaled (12 MB cap).

---

### D-014 — Name fields hold one name per value; place is an array held to its vocabulary; type is not inferred

**Decided:** 2026-10-02 by Meng Qu (project lead)
**Status:** active

Importing the 128-item batch into the portfolio site found output that structured outputs cannot
prevent, because the schema constrains shape, not content:

- **Model reasoning in a name field.** AAMU-0003 contributors ended with
  `Iso, J. Yun H. T., I. S. O.? No. Need exact. Wait.`
- **Several people in one array element**, joined by quote characters: ``Dockery, F. Jean`,`Ellis, Gloria B.` ``
  (AAMU-0003) and four names in one string on AAMU-0058.
- **Ambiguous multi-person strings:** `Brooks, Ronald, Burton, Kay` (AAMU-0098), `Spadaro, Anita
  Zucco, Maria Elisabetta?` (AAMU-0076), `Runyon, Louisa Runyon Shera, [unclear]` (AAMU-0020).
- **`place` as one semicolon-joined string** while subjects and genre are arrays. The v4 user prompt
  asked for the semicolon; the v4 system prompt forbids semicolon-joined lists.
- **`Tokyo--Tokyo`** (AAMU-0102), which is not a FAST heading. It survived because of D-010's place
  asymmetry: the 9-entry list cannot tell it from the correct `Japan--Tokyo`, and both were kept.
- **`type`** filled on 10 of 128 items as `Text`, `text`, `memorandum`, `correspondence`,
  `Newspaper clipping`.

Now (`app/field_validation.py`, applied by `_enforce_post_extraction()` on extraction and rebuild):

- **Names.** `creator`, `contributors` and `correspondents` keep a value only if it is exactly one
  name. Rejected: quote-comma-quote joins, `?`, reasoning words (`wait`, `need exact`, `hmm`, ...),
  backticks, semicolons, over 120 characters, and more than one comma unless the extra comma
  introduces a suffix or life dates (`King, Martin Luther, Jr.`). Rejections are removed, recorded by
  value and reason in `context.rejected_names` and a `NEEDS NAME REVIEW` note, and surfaced in the
  run manifest as `needs_name_review`. Quote-joined values carry a `suggested_split`, but are **not
  split automatically**: the string came from an output that had already broken down.
- **Place is an array** (schema v3), sender first. The schema item pattern is one `State--City`
  token; the v4 prompt now asks for an array. Readers go through `place_tokens()`, which accepts the
  legacy string, so the committed baselines in `out/` still read correctly. CSV export joins with
  `; `, so the upload sheet's `Location` column is byte-identical for any surviving place.
- **Place follows the subject rule.** A token absent from `vocab/fast_places.txt` is removed and
  recorded in the same `Place tokens absent from the approved FAST list:` note that
  `scripts/expand_vocab_from_run.py` already reads. The original order is kept in
  `context.place_as_extracted`, so growing the list and rebuilding restores a token in its original
  position, and the sender stays first.
- **`type` is never written from model output.** The April 2026 sheet leaves Type blank on every
  row, and genre carries the document type against AAT.
- **`metadata_tiers` is refreshed after enforcement.** It used to snapshot values before enforcement,
  so it kept every rejected subject and genre term (117 mismatches on the batch). It would also have
  kept the rejected names.

Rebuild re-offers every rejection to the current rules, so the review trail survives repeated
rebuilds. Rebuilds converge after one migration pass, which recovers place tokens the old code
dropped. Pinned by `tests/test_field_validation.py`. `scripts/audit_fields.py` counts these defects
in any output directory without changing it.

**Effect on out_batch** (128 records, current output vs. rebuilt):

| | before | after |
|---|---|---|
| Name values that are not one name | 7 in 6 records | 0 (7 in review trail) |
| Place stored as a string | 112 | 0 |
| Place tokens not in the approved list | 26 (16 distinct) in 25 records | 0 |
| Records with a place | 112 | 87 |
| Model-supplied `type` | 10 | 0 |

**Cost of the stricter place rule:** 25 records have no place until `fast_places.txt` grows past
its 9 pilot entries. The rejected tokens (`Japan--Tokyo`, `New York--New York`, `China--Peking`,
...) are the worklist for that, and a rebuild restores them once approved.


### D-015 — Places use FAST authorized headings, verified by FAST id; variants map to them

**Decided:** 2026-10-05 by Meng Qu (project lead)
**Status:** active — supersedes the 9-entry place list of D-014, and the collection's use of
`District of Columbia--Washington`

The archivist's MAP review sets the standard: Location "is a controlled vocabulary field that uses
the FAST Subject Heading", to be validated against FAST and consistent across the collection, and
*missing* locations are named as an error to fix. D-014 held places to `vocab/fast_places.txt`, but
that list held only the 9 places that happened to occur in the 19-image pilot. Applied to the
128-item batch it would have emptied the place of 25 records, most of them correct FAST headings
(`Japan--Tokyo`, `Illinois--Chicago`) that had simply never been reviewed — creating the missing
locations the review asks us to fix.

Now:

- **`vocab/fast_places.txt` lists FAST authorized headings, each with its FAST id** (26 headings).
  The list is a verified cache of FAST, not the standard itself.
- **Verification requires a FAST id.** A FAST suggest result with a matching label but no `idroot`
  is a see-reference, not a heading: `China--Peking` and `Japan--Kobe` both matched by label alone
  and were counted as verified by `scripts/expand_vocab_from_run.py` and by
  `app/vocab_validation.validate_fast_subject`. Both now require the id.
- **`vocab/fast_place_variants.txt` maps a variant to its authorized heading** — `China--Peking` →
  `China--Beijing`, `New York--New York` → `New York (State)--New York`, `Tokyo--Tokyo` →
  `Japan--Tokyo`, `Singapore--Singapore` → `Singapore`. One table, read by `app/places.py`, replaces
  three hard-coded and slightly different copies of the D.C. mapping. A mapping belongs there only
  when the place is certain and only the heading's form is wrong; every correction is written to the
  record's notes. Historical names stay in the transcript; the controlled field takes the current
  authorized form, as LC and FAST do.
- **Washington, D.C. is `Washington (D.C.)`** (fst01204505). FAST does not authorize
  `District of Columbia--Washington`, which the collection had used; the project lead chose to
  standardize on FAST. Records already published elsewhere under the old form need the same change
  to stay consistent.
- **Shape no longer decides validity.** The schema's place pattern required `State--City`, which
  rejects FAST's own headings for D.C. and city-states and flagged 18 valid records; it now forbids
  only semicolons and commas. `validation_core` checks the approved list before the shape.
- **A rebuild replaces its notes.** It used to keep the previous notes whenever the new list came
  out empty, so 13 records still reported places as rejected after they had been approved.

Result on the 128-item batch, rebuilt offline: 112 records keep a place (as before D-014; 87 under
it), every place is an approved FAST heading, and no record reports a rejection that no longer holds.

`Pennsylvania--Philadelphia`, the form the archivist prescribed, was confirmed by hand by the project
lead on 2026-10-05; the suggest API does not return its id.

### D-016 — Name lists are never capped

**Decided:** 2026-10-05 by Meng Qu (project lead)
**Status:** active

The schema limited `contributors` to 8 names and `correspondents` to 12. AAMU-0003 and AAMU-0069
each name 22 people, so both records were flagged as invalid. Nothing was lost in this batch — all 22
names are in the data, the CSV export and the portfolio — but the same schema is sent to the model in
strict mode, so on the next paid run a cap could make the model drop people at generation time,
where no later check can see it.

A schema limit is not a reason to remove a person from the record. Both caps are removed, and
`tests/test_field_validation.py` fails if a name list is ever capped again.

### D-017 — A reviewer may set place; reviewed values are labelled as reviewed

**Decided:** 2026-10-05 by Meng Qu (project lead)
**Status:** active

16 records came out with no place. Each was checked against its scan, since letterheads, postmarks
and stamps are not transcribed (policy R1) and can only be seen there. Five had a place the model
missed; three need an archivist's judgment; eight genuinely state none.

The five were set through review files (`<stem>.review.json` beside each record), not by editing
the output, so the change carries its evidence and a rebuild re-derives it. The files live in the
ignored `out_batch/`; the record of them is here:

| Item | Place | Evidence on the scan |
|---|---|---|
| AAMU-0050 | Ohio--Cincinnati | Telegram headed "Cin NL Apr 22", signed "Morris Edwards, Cin Cham of Com"; luncheon at the Netherland Plaza |
| AAMU-0036 | Ohio--Oxford | Written by President R. M. Hughes ("Mrs. Hughes' and my thanks"); office carbon to Huang at Miami |
| AAMU-0029 | Ohio--Oxford | Writer at Miami: "his long connection here the University sent flowers" |
| AAMU-0073c | Ohio--Oxford | The president to Miami faculty about Hasegawa's visit "to be in Oxford ... for Homecoming" |
| AAMU-0087 | Ohio--Oxford | Internal memoranda between Dean Etheridge and the Foreign Student Adviser |

The last four apply the MAP review's rule to "supply Ohio--Oxford as a location when it is clear
that the document originates from Miami University through context ... even if it doesn't say it on
the letter." Approved by the project lead; the evidence was read from the scans by Claude.

Left for an archivist: BC-0897 (a Miami-typed copy of a YMCA secretary's letter, original place not
stated), AAMU-0068 (unsigned carbon recommendation), AAMU-0069 (student paper naming no institution).

Mechanism:

- **`place` is now reviewable** (`REVIEWABLE_FIELDS` in `app/ai_metadata.py`), alongside the five
  Tier 2 fields.
- **A review cannot bypass the vocabulary.** The override is applied before enforcement, so a
  reviewed place that is not an approved FAST heading is rejected and recorded like any other.
- **Reviewed values are labelled `Human-Reviewed`.** Provenance labels were fixed per field, so an
  overridden subject still read "AI-Proposed Subject". The override note now records the value, the
  evidence, the reviewer and the date.

Found while checking the scans, not yet corrected — for review in the portfolio CMS: AAMU-0050's
transcript marks a legible telegram illegible; AAMU-0066 is signed "O Ito" (likely the O. Ito of
AAMU-0068), not "Otto"; AAMU-0068 is dated May 11, 1926, not May 10; AAMU-0028's first page is
misread ("Marie Marshall" as "Miami Itinerary", "Miss Peggy Lou Upham" as "Miami University");
items over six pages restart page markers at `[page 1]` in their second chunk; AAMU-0087 holds two
memoranda but is described as one.
