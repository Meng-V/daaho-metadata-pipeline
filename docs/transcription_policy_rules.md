# Transcription Policy → Machine-Checkable Rules

Derived from **DAAHO Transcription Policy (FINAL)**, §2 "Transcribing Written Documents".
The authoritative document is the policy itself (see `docs/source/README.md`); this file is the
engineering extraction — the rules an automated checker and the extraction prompt both consume.

§3 (audio/film) and §5 (translation) are out of scope for this image pipeline.

## The framing that matters

DAAHO transcription is **not verbatim**:

> Transcripts are rarely verbatim copies of source materials and typically incorporate light
> editing and fact-checking while still representing the tone and intended meaning of the
> original material. **All edits to transcripts are clearly indicated.**

The rule is **retain the original, then annotate the correction in brackets** — never silently
normalize, and never leave an error unmarked. The canonical form from §2:

```
This Novmber [November] weather is unusual.
```

The departed review assistant's correction format was exactly this (`Sincerly [Sincerely] yours.`),
which means her review document is a direct application of this policy and can be used as the
acceptance criterion. See `tests/fixtures/jinming_review_2026-04.json`.

## Rule table

`AUTO` = decidable by a deterministic checker. `PROMPT` = must be instructed, verified by sampling.
`BLOCKED` = cannot be represented in the current schema.

The "April 2026 state" column records compliance **before** the v4 prompt existed — it is the
evidence that motivated the rewrite, not a description of today. Current compliance is 0 policy
errors; run `scripts/policy_lint.py` for the live figure.

| # | Policy rule (§2) | Check | April 2026 state |
|---|---|---|---|
| R1 | Do not transcribe stationery **letterhead** | AUTO | ❌ violated — BC-0926 opens `ADDRESS OFFICIAL COMMUNICATIONS TO / THE SECRETARY OF STATE / WASHINGTON 25, D.C.`; BC-0708 opens `Federal Security Agency / NATIONAL YOUTH ADMINISTRATION FOR OHIO / Hoster Bldg.` |
| R2 | Do not mimic **line breaks**; do not retain original layout | AUTO | ❌ violated — 28 newlines per transcript on average, layout copied verbatim |
| R3 | Retain **paragraph** breaks as double carriage returns | AUTO | ⚠️ untested |
| R4 | Mark **page breaks** as `[page 1]`, `[page 2]` on their own first line | AUTO | ❌ 0 of 18 transcripts contain any `[page N]` |
| R5 | Retain **capitalization and punctuation exactly** as in the original | PROMPT | ❌ violated — `Sincerly`→`Sincerely`, `STUDENTS'`→`STUDENT'S`, `condition.`→`condition,` |
| R6 | **Misspellings**: transcribe as written, follow with `[correction]` | AUTO (presence) + PROMPT (accuracy) | ❌ 1 of 18 transcripts contains any non-`[handwritten]` bracket annotation |
| R7 | **Illegible** words → `[illegible]` | AUTO | ❌ 1 of 18 transcripts uses `[illegible]`/`[unclear]` |
| R8 | **Acronyms/abbreviations**: as written, then `[expansion]` | AUTO (presence) | ❌ none present |
| R9 | **Numerals**: >10 as numerals, <10 spelled out | AUTO | ⚠️ conflicts with R5 (see Open questions) |
| R10 | **Foreign-language** words: `[translation]` after first use | PROMPT | ❌ violated — `7 Nihon Odori, Nakaku`, `10-254 Yon Am-Dong` unannotated |
| R11 | **Strikeouts**: retain, do not delete | BLOCKED | plain-string transcript cannot express strikethrough |
| R12 | **Underlines**: preserve | BLOCKED | same |
| R13 | **Superscripts**: remove (`1st`, not `1ˢᵗ`) | AUTO | ⚠️ untested |
| R14 | **Insertions** between lines → `^carets^` | AUTO (presence) | ❌ none present |
| R15 | **Symbols** retained; `&` followed by `[and]` unless in a proper name | AUTO | ⚠️ untested |
| R16 | **Names** missing identifying info → clarify in `[brackets]`; alternate/original-language names in `[brackets]` | PROMPT | ❌ the root of the unverifiable-name findings |
| R17 | **Redactions** → `[redacted]`; closed sections → `[this section closed]` | AUTO | ⚠️ untested |
| R18 | Turn **auto-correct off** | PROMPT | ❌ this is R5's failure mode — the model behaves as an autocorrecting copy editor |

**Score against the April 2026 output (18 transcripts): essentially zero of the checkable rules were
implemented.** Root cause is already identified: `prompts/loc15_v2_system.txt` and
`loc15_v3_fewshot_system.txt` contained **no transcript instructions at all** — a regression from
`loc15_v1_system.txt`, which did have them. Those two prompt versions were deleted in the July 2026
cleanup; `loc15_v2_*` is kept because the committed `out/` baseline was produced with it and the
claims above are checkable against it.

## Use §6 as the few-shot example

Policy §6 supplies a complete worked example transcript, and it was a better few-shot than what the
v3 prompt used:

- Same era and genre as this collection — a 19 March 1938 travel letter, `Dear Miss Marshall`
- Demonstrates `[page 1]`
- Demonstrates the retain-plus-bracket form twice: `of couse [course]`, `evrybody [everybody]`
- Demonstrates consecutive `[illegible] [illegible]`
- Demonstrates flowing paragraphs with **no line-break mimicry** (R2)

It is the project's own authoritative example, and it is what `prompts/loc15_v4_system.txt` now
carries verbatim.

## Resolved

1. **R9 vs R5** — R9 (numeral style) applies only to transcriber-authored bracketed notes. Inside
   transcribed source text R5 wins: reproduce the document's own numerals. Encoded in
   `prompts/loc15_v4_system.txt` rule 10.
2. **`[illegible]` vs `[unclear]`** — both accepted for written documents, with a defined split.
   See **D-007**.
3. **R11/R12** — resolved with TEI-mappable bracket markers `[struck: ...]` and
   `[underlined: ...]`. See **D-006**.

## Still open

4. **Scope of the policy's output format.** §1 specifies Google Docs, Arial 12pt, PDF preservation
   copy / RTF access copy. Unclear whether the pipeline's JSON transcript is meant to become one of
   those documents or is an upstream artifact feeding them. Does not block anything yet, but it
   determines whether an RTF/Docs exporter is eventually needed.
5. **`text_reading` is unused.** The schema carries both `transcript` and `text_reading`, and
   `text_reading` is null in all 19 outputs. The v1 prompt defined it as "a clean, linear reading
   text with no markup" — which is exactly the *access* copy the policy's §1 RTF deliverable would
   want, with `transcript` as the annotated scholarly version. v4 leaves it null to avoid doubling
   output tokens. Revisit alongside item 4.

## What v4 and the linter do and do not cover

`prompts/loc15_v4_system.txt` + `prompts/loc15_v4_user.txt` encode R1–R18 and D-006/D-007.
`scripts/policy_lint.py` mechanically enforces the AUTO subset.

**Known limits of the linter** — these need human eyes and are why D-004 stands:

- It cannot judge whether a bracketed `[correction]` is the *right* correction.
- It cannot judge whether `[illegible]` should have been a real reading, or the reverse.
- It cannot detect **omission** (R16) beyond a wholly empty transcript — knowing that text is
  missing requires reading the image.
- Its R18 handwriting-guess check only fires when a candidate reading sits next to an uncertainty
  marker (`[handwritten] Murry [unclear]`). A bare confident guess with no marker
  (`[handwritten] C V Hibbard`, finding `0718-2`) is mechanically indistinguishable from a correct
  reading.
- R2 (line-break mimicry) is a heuristic on short-line ratio, not a layout analysis. Verse,
  address blocks, and tabular content will trip it legitimately.
