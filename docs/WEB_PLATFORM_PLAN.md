# Plan — Packaging the Pipeline as a Hosted Web Application

Draft for discussion. Written against the pipeline as it exists today (128-record batch delivered,
48 tests, measured costs), not against a greenfield idea.

---

## 1. Four constraints that decide the architecture

These are measured facts about this pipeline, not preferences. Every stack choice below follows
from them.

**1.1 Processing is long.** A single archival item takes 30–90 seconds; the 128-item batch took
roughly 30–40 minutes at 3 workers. This cannot be an HTTP request/response. Vercel serverless
functions cap at 60s (Hobby) / 300s (Pro); AWS Lambda caps at 15 minutes. **A job queue with a
long-running worker is mandatory** — this single fact eliminates several otherwise attractive
options.

**1.2 The pipeline is Python and should stay Python.** `app/` is ~2,500 lines of Python carrying 48
tests and a year of hard-won corrections — the pixel cap, the failure semantics, the vocabulary
enforcement, the cost ledger. Porting it to TypeScript would mean re-learning every lesson in
`docs/OVERHAUL_2026-07.md`. **The backend is Python. That is settled.** The only open question is
what sits in front of it.

**1.3 Batches are large.** 316 images totalled 1.28 GB, individual files 0.2–9.1 MB. Uploading
through an application server wastes bandwidth and hits body-size limits. **Uploads must go
browser-to-storage directly via presigned URLs.**

**1.4 Operational simplicity is a project requirement, not a preference.** Both student workers who
built the current pipeline left, and nothing was documented (see D-012). Any architecture that
needs a specialist to operate will die the same way. **Prefer fewer moving parts over elegance.**

---

## 2. Recommended stack

### The recommendation

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js on Vercel** | Best fit for a multi-step wizard; you already deploy to Vercel; server components handle auth cleanly |
| API + worker | **FastAPI in one container** on Render / Railway / Fly.io | Same language as the pipeline, imports `app/` directly, no port |
| Job queue | **Postgres-backed queue** in the same container | Avoids running Redis. At 1–10 concurrent users this is entirely adequate |
| Database | **Postgres** (Neon / Supabase / provider-managed) | Users, jobs, configs, results |
| Object storage | **Cloudflare R2** | S3-compatible, **no egress fees** — matters when users download multi-GB result bundles |
| Auth | **Email magic link** (Auth.js / Clerk) | No password storage. Institutional SSO is the eventual answer, not the MVP one |

Two deployments, one language per side, no bespoke infrastructure.

### What I would reject, and why

**Next.js full-stack alone.** Attractive — one repo, one deploy — but it cannot run the Python
pipeline, and rewriting the pipeline is the single worst decision available here. Ruled out by 1.2.

**Full AWS (Lambda + Step Functions + Cognito + DynamoDB).** Scales further than this project will
ever need, and costs the most in operational attention. Lambda's 15-minute ceiling is a live problem:
the 36-page bound volume needed 12 sequential API calls. Step Functions would work around it and
would also be the first thing to break when the next student worker leaves. Ruled out by 1.4.

**Celery + Redis.** The textbook answer, and correct at scale. At this scale it is one more service
to run, monitor, and hand off. A Postgres queue (`SELECT … FOR UPDATE SKIP LOCKED`) is ~40 lines and
has no separate uptime story. Revisit if concurrency ever justifies it.

**A fully Python UI (FastAPI + HTMX).** Genuinely tempting — one deployment, one language, and the
UI here is a form wizard rather than an application. If you would rather not maintain a JS
toolchain, **this is a legitimate second choice** and would cut the build roughly in half. The
trade-off is a less polished multi-file upload and progress experience.

---

## 3. The user flow

Five steps, matching what you described, with the failure modes that testing has already exposed.

### Step 1 — Sign in
Email magic link. Account holds: institution name, saved configuration profiles, job history.

### Step 2 — Upload
Drag a folder or multi-select. Browser requests presigned URLs and uploads directly to R2. Progress
per file; resumable for large batches.

### Step 3 — Confirm grouping ← *the step you did not list, and the one that matters most*
Our own batch was **316 images but 128 archival items**. If a user's files follow a recognisable
convention (`_Page_1`, `_Recto`/`_Verso`, sequence prefixes), the system proposes the grouping and
shows it as a tree for confirmation. If not, they group manually or accept one-record-per-image.

This step is free — no API calls — and it is the single highest-leverage checkpoint in the flow.
Getting it wrong means every downstream record is wrong. `scripts/triage_batch.py` already does this
work at the command line; the UI is a view over it.

### Step 4 — Configure (the institution supplies its own rules)
Tabbed form, with Miami's configuration as the default template to fork:

- **Metadata profile** — which fields, which are required, the CSV column names to export
- **Trust tiers** — per field: AI may generate / AI proposes and staff validate / never machine-filled
- **Controlled vocabularies** — upload term lists or point at FAST/AAT; choose reject-and-flag vs allow-free-text
- **Transcription policy** — the rules governing transcripts, editable as text with our rules as the starting point
- **Fixed values** — repository, collection, rights: the fields that must never be inferred
- **Model tier** — with a live cost estimate from the measured per-image figures

Saved as a named profile and reusable. This is the substance of the "not bound by Miami's policy"
commitment in Section 7.12.

### Step 5 — Process
Job queued; worker runs the existing pipeline unchanged. Live progress: items completed, current
cost, failures. Closing the browser is safe.

### Step 6 — Review and export
Results table sorted by confidence — the 8% needing attention first, exactly as in the current
workflow. Click through to the image beside the generated record, edit fields, mark reviewed. Then
export.

---

## 4. Output formats — the brainstorm you asked for

The insight from our own experience: **the deliverable is not one file.** Our handoff needed the
upload CSV, per-record JSON, a cost report, and a review queue. Different institutions will need
different targets, and no single format serves all of them.

**Proposal: one ZIP bundle, with the user selecting which components to include.**

| Format | Purpose | Effort | Notes |
|---|---|---|---|
| **CSV, user's own columns** | Repository ingest | Done | `export_csv.py --template` already maps to an arbitrary header row. Have the user upload their sheet's header row in Step 4 |
| **Per-record JSON** | Archival record of provenance, confidence, processing notes | Done | The tool-independent preservation copy |
| **Transcripts as plain text** | Human reading, proofreading, OCR indexing | Trivial | One `.txt` per item |
| **Cost report CSV** | Budget accountability | Done | `cost_deliverable.py` |
| **Review queue CSV** | The short list a human must check | Trivial | Confidence-sorted |
| **TEI XML** | Scholarly digital editions | **Small — we designed for it** | D-006 chose bracket markers that map 1:1 to `<del>`, `<hi>`, `<gap>`, `<unclear>`. This is a transform, not a rewrite, and it is a genuinely differentiating feature |
| **Dublin Core / MODS XML** | Standard repository interchange | Medium | The lingua franca for OAI-PMH harvesting |
| **IIIF manifest** | Image delivery with transcript annotations | Medium | Increasingly expected in digital collections |
| **Direct connectors** (CONTENTdm, ArchivesSpace, Omeka S, Islandora) | Skip the spreadsheet entirely | Large, per-platform | Post-MVP, and only for platforms users actually ask for |

**My recommendation for the MVP:** ZIP containing CSV (user-mapped) + JSON + transcripts + cost
report + review queue. Add TEI in v1 — the design work is already done and it is the thing that will
distinguish this from generic OCR tools. Defer XML standards and connectors until a real user asks.

---

## 5. The API key problem — read this before building

Accepting other people's OpenAI keys makes you a custodian of their credentials. A leak means their
bill, their liability, your institution's name on the incident. OpenAI offers no OAuth for API keys,
so the key itself must be held. Three viable designs:

**A. Session-only (safest, most annoying).** Key lives in browser memory, sent with the job, held by
the worker in RAM, never written to disk. Nothing to breach. But a 40-minute job means the user must
keep the tab open, and a resumed job needs the key re-entered.

**B. Encrypted at rest, deleted on completion (recommended).** Key encrypted with a per-user data key
under a KMS master key, stored on the job row, deleted when the job finishes or fails. Exposure is
bounded to the job's lifetime. Requires KMS discipline: never log it, never return it via the API,
redact it from error traces.

**C. Encrypted and retained for convenience.** Best UX, largest liability. Not worth it here.

**Recommendation: B**, plus these regardless of choice:

- Validate the key with one trivial API call at submission, so a bad key fails in 2 seconds rather
  than 40 minutes
- Show a spend estimate before the job runs and enforce a user-set ceiling
- Per-user job concurrency limits, so one user cannot monopolise the workers
- A plain-language statement of exactly how the key is stored and when it is deleted
- Institutional review: **check with Miami's IT security office before launch.** Holding third-party
  credentials on a university-hosted service is likely to require a review you would rather discover
  now than after go-live

---

## 6. What has to change in the existing codebase

The pipeline currently reads its configuration from files and hardcodes the rest. Making an
institution's rules user-supplied is the real engineering work — the UI is comparatively easy.

| Today | Needs to become | Difficulty |
|---|---|---|
| Vocabularies as `vocab/*.txt` | Per-profile lists in the database | Easy — already file-driven |
| Prompts as `prompts/*.txt` | Per-profile templates, with ours as default | Easy — already versioned by filename |
| `LOC15_SCHEMA` hardcoded in `schema.py` | Generated from a profile definition | **Hard** — must emit strict-mode-valid JSON Schema (`additionalProperties: false`, every property in `required`); we already lost `field_confidence` to this once |
| `TIER1/2/3_FIELDS` hardcoded | Per-profile trust assignment | Medium |
| `GENRE_PREFERENCE`, `LETTERHEAD_PATTERNS` hardcoded | Per-profile rules | Medium |
| Filename grouping regexes in `grouping.py` | Chosen convention, or manual grouping from the UI | Medium |
| CLI writes to a directory | Writes to storage, reports progress to a job row | Medium |

**The schema-generation piece is the one to prototype first.** If per-institution schemas cannot be
generated reliably under strict mode, the whole "your rules, not ours" premise weakens, and it is
better to learn that in week one than in month three.

---

## 7. Phasing

**Phase 0 — Feasibility spike (1–2 weeks).** Prove the two things that could sink it: generate a
strict-mode-valid schema from a profile definition, and run one job end to end through a queue with
a browser-supplied key. Build no UI. If either fails, the plan changes.

**Phase 1 — MVP (6–10 weeks).** Auth, upload, grouping confirmation, configuration form, processing,
results table, ZIP export. Miami's profile as the default. Single worker. Target: one external pilot
institution, hand-held.

**Phase 2 — Usable by strangers (6–8 weeks).** Self-service profiles, TEI export, review-and-edit
interface, cost estimation and ceilings, documentation, concurrency. Target: three to five
institutions without hand-holding.

**Phase 3 — Sustaining.** Repository connectors, institutional SSO, shared public profiles for
common standards (DACS, Dublin Core), usage analytics for grant reporting.

Phase 0 and 1 are plausible for one part-time developer over a semester. Phase 2 realistically needs
either a dedicated student developer or contracted help.

---

## 8. Running costs

With users bringing their own keys, inference cost is zero to you. What remains:

| Item | Estimate |
|---|---|
| Vercel (frontend) | $0–20/mo |
| Container host (API + worker) | $10–25/mo |
| Postgres | $0–25/mo |
| R2 storage | ~$0.015/GB-month; **no egress fees** |
| **Total** | **roughly $25–75/month** at pilot scale |

The real cost driver is image retention. A 30-day auto-delete policy after export keeps storage
trivial and reduces how much of other institutions' material you are holding — which is also the
better answer for privacy and for the security review.

---

## 9. Open questions

1. **Who is the operator after launch?** If the answer is "Meng, alone," Phase 2 scope needs cutting
   and the HTMX option deserves serious reconsideration.
2. **Is this a Miami-hosted service or a grant deliverable others self-host?** Hosting means security
   review, uptime expectations, and support requests. Publishing a one-click deploy template has none
   of those obligations and reaches fewer people. This choice changes Phase 1 substantially.
3. **Do users need a review-and-edit interface, or is export-and-review-in-Excel enough?** Building
   the editor is a large share of Phase 2. Our own workflow reviewed in a spreadsheet perfectly well.
4. **Which repository platforms actually matter?** Do not build connectors speculatively.
5. **Does NHPRC funding cover implementation, or is this a follow-on proposal?** The answer sets the
   timeline and whether this is designed for one developer or a team.
