# Draft handoff email — DAAHO AI metadata batch

**Not sent.** Edit the greeting and sign-off, then send it yourself.
Attach:
- `out_batch/metadata_upload_2026-07-25.csv` — the metadata
- `out_batch/cost_per_item.csv` — what each record cost
- `out_batch/cost_summary.csv` — cost totals

---

**Subject:** DAAHO metadata for the 316 images — handing this over to you

Hi [name],

Attached is the AI-generated metadata for the 316 images, in the same 31-column format as the April
sheet. It's yours now — you have the final say on what goes into the archive. Here's what you're
looking at.

**316 images, but 128 records.** 58 of the files are multi-page documents or recto/verso pairs, so
one record covers the whole item and its transcript spans all its pages (`[page 1]`, `[page 2]`, …).
AAMU-0069 alone is a 36-page volume in one record. This matters when you map records to files —
`Preservation Filename` gives only each item's first image.

**The handwritten items are the weak spot.** Fifteen records came back with poor transcripts, and
every one of them is handwritten. Re-running those on a stronger model helped a lot — one six-page
letter went from two lines to a full transcript — but ten are still the least reliable records in the
batch and worth checking against the images:

    AAMU-0014  0015  0016  0018  0019  0035  0060  0061  0073a  0074

AAMU-0074 is the weakest of them.

BC-0934 (the Korean student scholarship form) is also worth checking — it's typed but faint, and it
reads poorly.

**Fifteen columns are empty.** Eight of them because nobody had the information — Series,
Repository, Collection, Folder, Rights, Digital Collection, Digital Publisher, Digitized. These are
archival placement and rights, and I left them blank rather than let the system guess, since a wrong
box number is worse than an empty field. The other seven — Extent, Dimensions, Subject
(People/Local), Theme, Issue, Object ID — the pipeline doesn't produce at all, so please plan around
those staying empty.

**One caution before anything gets published:** our transcription policy requires a transcript to be
proofread by a person before finalization, and most of these haven't been. I'd treat the whole batch
as staging rather than final metadata.

**We've also changed models.** The earlier metadata came from GPT-4o, which shrinks large images
before reading them — our scans were being reduced to roughly a fifth of their resolution, which is
where a lot of the misread names and dates came from. This batch uses OpenAI's current generation,
which reads the scans at full size. To keep the cost down it runs in three tiers by how hard the
material is: **gpt-5.6-luna** for straightforward pages, **gpt-5.6-terra** for ordinary ones, and
**gpt-5.6-sol** for difficult ones, so we only pay the premium where it earns it. This batch ran on
terra, with the 15 handwritten items re-run on sol; luna wasn't needed.

Two things that will look unfamiliar, both deliberate: transcripts keep the original misspelling with
the correction in brackets (`Sincerly [Sincerely] yours`) rather than silently fixing it, and
personal names are inverted without honorifics (`Sheehan, Murray`). The earlier output did neither.

Two cost files are attached as well: one row per record, and a summary. Short version — the 128
records cost $28.38, averaging $0.22 each; $34.25 was spent in total once the pilot runs and the
diagnostic work are counted.

Everything else is in the project repo — the per-record JSON has confidence scores and processing
notes behind every value in the spreadsheet.

Best,
Meng
