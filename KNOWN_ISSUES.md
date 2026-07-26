# Known Issues

## RESOLVED (2026-07-25) — "Few-shot rebuild strips transcript field" was misattributed; the real bug was Tier 3

The original entry read:

> Observed: all 19 `out_fewshot_summary_test/*.loc15.json` files have empty `metadata.transcript` […]
> **Suspected cause:** `--rebuild-from-existing` […] does not merge back any top-level or tier fields
> not explicitly reconstructed.

That diagnosis was a hypothesis, and it does not hold up.

**Rebuild does not strip transcripts.** Tested against all 19 files of the gpt-4o baseline (`out/`)
and against current v4 output (`out_v4b/`): zero metadata keys lost, zero top-level keys lost, zero
context keys lost, zero transcripts emptied. `transcript` is in `TIER1_FIELDS`, so the tier policy
preserves it, and non-tier keys such as `language` survive too.

**What actually emptied those transcripts:** `out_fewshot_summary_test/` was produced by a normal
pipeline *run* (`--out out_fewshot_summary_test --prompt-version loc15_v3_fewshot`), not by a
rebuild — `scripts/summary_fewshot_comparison.py` only reads that directory, it never writes it. The
v3 few-shot prompt contains **no transcript instructions at all** (see `docs/DECISIONS.md`, and the
v4 prompt commit), and its user prompt is dominated by Summary style examples. The empty transcripts
came from the prompt, not from rebuild. The directory itself no longer exists locally, so the
original artifact cannot be re-examined.

**The real bug, found while testing the reported one:** rebuild silently **wiped Tier 3**.
`apply_tier_policy()` clears any Tier 3 field lacking an explicit default — correct for a fresh
extraction, where archival placement must never be inferred, but destructive on a rebuild. Injecting
`box: "Box 12", folder: "Folder 3", identifier: "BC-0692", repository: "Miami University Libraries"`
and rebuilding returned all four as `null`.

This blocked the intended workflow exactly: expand the controlled vocabularies from the first real
batch, then rebuild to re-apply them — which would have destroyed any archival placement recorded in
the meantime.

Fixed: `rebuild_existing_outputs()` carries existing Tier 3 values forward as defaults, so an
explicit CLI flag still overrides them and an absent value is still never invented. The rebuild
records `Preserved existing Tier 3 values on rebuild: …` in `policy_notes`. Pinned by
`tests/test_rebuild.py`, including that repeated rebuilds are stable.

## Jan → Apr 2026 pipeline regressions: data present in January is missing today

Found 2026-07-25 by diffing the two surviving CSV versions
(`python3 scripts/csv_version_diff.py final_metadata.csv out/final_metadata_2026-04-27_handoff.csv`;
full output in `docs/csv_diff_jan_to_apr_2026.txt`). 121 cells changed, of which **14 lost a value
that January had**. Verified still lost in the current `out/*.loc15.json`:

- **BC-0698 lost its entire transcript.** January held 1585 characters (`Tosses His Dime / The Post /
  U. S. WEATHER FOR...`); the current output has `transcript: null`. This is the same item the
  review assistant flagged with *"the corresponding section in the AI-generated transcript is
  completely blank, despite the presence of text in the original document"* — so her finding was
  not a partial omission, the whole transcript was dropped between versions.
- **`Language: English` lost on 7 items** — BC-0692, 0697, 0698, 0699, 0708, 0714, 0926. Exactly
  the 7 items with an empty `language` in `out/` today.
- **BC-0699 lost `Location: Japan--Osaka`.**
- **Creator regressions:** BC-0697 `anonymous` → empty; BC-0934 `Miami University` → empty.

Not regressions, despite appearing in the diff: BC-0692 / BC-0703 / BC-0934 lost `Date: undated`.
That is **correct** per the archivist MAP review — `Date` is a numeric-only controlled field and
undated items should leave it blank, with `undated` appearing in the title instead.

Why it matters: nobody noticed these at the time, and they are not recorded in any review
document. `final_metadata.csv` (January) is therefore **not obsolete** — it is a partial recovery
source for content the current pipeline no longer produces. Do not delete it, and check it before
re-running BC-0698.

Recommended fix: add a regression check that compares a fresh run against the previous run and
fails on any field that goes from populated to empty without an explicit reason.

## v4 fabricated a transcript for BC-0934, and the policy linter passed it

Found 2026-07-25 in the first full v4 run (`out_v4/`, tier terra).

BC-0934 is a **clean, fully legible typed form** — verified by opening
`SAMPLES/BC-0934_Recto.jpg` directly. It reads `OFFER OF SCHOLARSHIP FOR KOREAN STUDENT`, with
`Student Selected -- Rosa Choi, 18-254 Ton Am-Dong, Seoul, Korea.` and three signatures.

The gpt-4o baseline in `out/` transcribed it substantially correctly (1,100 chars). **v4 produced
416 characters of a different document**: it invented a letter skeleton
(`December 21, 1943` / `Dear Mr. [illegible]:` / `Sincerely yours,`) and filled the body with 28
`[illegible]` markers. None of the form's real content survived.

This is worse than over-marking uncertainty — it is a fabricated document structure. Suspected
cause: the v4 prompt's heavy "never guess, mark [illegible]" emphasis interacting badly with a
low-contrast page, causing the model to abandon reading and emit a plausible template.

**The important part: `scripts/policy_lint.py` scored this transcript as CLEAN.** It has
`[page 1]`, bracket annotations, no letterhead, and no long runs of short lines — every mechanical
rule passes while the content is fiction. A deterministic policy checker cannot detect fabrication,
which is the concrete limit behind `docs/DECISIONS.md` D-004.

**What did catch it:** `field_confidence.transcript = 25`, the lowest of all 19 items. Sorting the
run by that field puts BC-0934 first, then BC-0688 (57), BC-0897 (65), BC-0697 (68), with the
remaining 15 items at 72-99. The D-008 triage signal worked exactly as intended and is currently
the only automated defense against this failure mode.

Recommended: treat `field_confidence.transcript < 70` as a mandatory human-review queue, and add a
length-regression check (v4 transcript shorter than ~55% of a prior run's for the same item).

### Side effect: three flagged name spellings are now resolvable from this image

Opening the image also confirmed the review assistant's readings — `Rosa Choi`,
`18-254 Ton Am-Dong`, and `Provisions` (plural) are all correct against the source. The signature
reads **`Ernest H. Hahne`** (corroborated by a handwritten `Pres. Hahne` at top right), supporting
the earlier human note over the AI's `Ernest H. Hahm`. That is one of the five name spellings
flagged for confirmation in April; see D-005, which currently records three as unadjudicated.

