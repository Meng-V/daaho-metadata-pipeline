# Plan — Packaging the Pipeline as a Hosted Web Application

Written against the pipeline as it exists today (128-record batch delivered, 48 tests, measured
costs), not against a greenfield idea.

## Decisions taken (2026-08-18)

| Question | Decision |
|---|---|
| API key custody | **Encrypted at rest, deleted when the job ends.** Never logged, never returned by the API |
| Hosting | **Miami-hosted service.** Other institutions arrive with their own OpenAI key |
| Operator | **Meng Qu, alone.** This is a design constraint, not an aside |
| Metadata editing | **Export and review in a spreadsheet.** No in-browser editor |
| Funding | **NHPRC covers the testing phase only — not implementation or ongoing operation** |

The funding constraint is the most consequential of these and is addressed in §7.

---

## 1. Four constraints that decide the architecture

These are measured facts about this pipeline, not preferences. Every stack choice below follows
from them.

**1.1 Processing is long.** Measured on the delivered batch: **~120 seconds per API call**, and 316
images across 128 items took **64.6 minutes at 4 workers**. This cannot be an HTTP request/response. Vercel serverless
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

### The recommendation (revised 2026-09-10)

Settled after two rejected drafts. The earlier Next.js/Vercel and Next.js/Miami proposals are
recorded in §2.1 with the reasons they were dropped.

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Vite + React**, built to static files | A form wizard needs no server rendering. Vite emits plain assets that FastAPI serves directly |
| API + worker | **FastAPI**, `docker compose` on **EC2** | Same language as the pipeline, imports `app/` directly, no port |
| Job queue | **Postgres queue** (`SELECT … FOR UPDATE SKIP LOCKED`) | ~40 lines, no Redis, no separate uptime story |
| Database | **RDS PostgreSQL** `db.t4g.micro` | Managed backups and point-in-time recovery; also frees CPU on the app instance |
| Image staging | **S3**, 24-hour lifecycle rule | See §2.2 — this is staging, not caching |
| Edge / TLS | **CloudFront** | Free at our volume, and the only way to attach AWS WAF without an ALB |
| Auth | **Email magic link** | No password storage. Institutional SSO is the eventual answer, not the MVP one |

One instance, one compose file, one language per side, no bespoke infrastructure.

### 2.1 Why not the earlier drafts

**Next.js on Vercel** — rejected because the service must be Miami-hosted, which is a project
constraint, not a preference.

**Next.js hosted at Miami** — rejected because every Next.js server feature we would have paid for
in complexity (server components, API routes, middleware) is unused: all business logic is Python.
What remained was a Node runtime to patch and monitor for no benefit.

**Kubernetes / ECS / Fargate** — rejected by 1.4. `docker compose` on one instance is operable by one
person. Neither of the others is.

**NAT Gateway** — rejected on cost. At $0.045/hr plus $0.045/GB it exceeds two-thirds of the
application server's price. The instance sits in a public subnet behind a security group; RDS sits
in a private subnet and is reached over the VPC.

### 2.2 Staging, not caching

Each image is read exactly once — decode, downsample, base64, send, discard. Nothing is ever
re-read, so there is no cache workload and **no reason to introduce Redis or a CDN for images**.
What is needed is somewhere for a batch to live between upload and completion.

S3 over an EBS directory, for four reasons in order of weight:

1. **A lifecycle rule enforces deletion.** "Delete the images when the job ends" is a commitment made
   to adopting institutions; on S3 it is enforced by infrastructure rather than by a cleanup job that
   can silently stop running.
2. **A full disk takes the whole service down.** One failed cleanup on EBS stops Postgres writes and
   every running job. S3 has no full state.
3. **The instance becomes replaceable.** Resize, rebuild or move it with no data on board.
4. **Upload bandwidth stops competing with processing.** Browsers upload straight to S3 by presigned
   POST; the bytes never touch the application server.

Wrap it behind a four-method storage interface (`put` / `get` / `presign` / `delete`) with a local
filesystem implementation, so development needs no AWS account.

Two implementation details that are easy to get wrong:

- **Presigned POST, not presigned PUT.** Only POST carries a policy with `content-length-range`, so
  only POST can enforce the 10 MB per-image cap server-side. The 100-image cap is enforced by the
  backend simply issuing no more than 100 URLs.
- **Thumbnails belong in the browser.** The grouping-confirmation step runs in the same browser
  session that just picked the files, so the originals are still local. Downscale with a canvas for
  the preview grid. This is faster for the user than waiting on server-side generation and costs the
  server nothing.


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

## 7. Phasing, and the funding constraint

**NHPRC funds the testing phase, not implementation or operation.** The grant can pay to prove this
works; it cannot pay to run it as a service. That shapes both the scope and the exit plan.

| Phase | Scope | Funding |
|---|---|---|
| **0 — Feasibility spike** (1–2 weeks) | Generate a strict-mode-valid schema from a profile definition; run one job end to end through the queue with a browser-supplied key. **No UI.** If either fails, the plan changes | Testing ✓ |
| **1 — Working service** (8–12 weeks) | Auth, upload, grouping confirmation, template-based configuration, processing, results table, ZIP export, **spend ceilings**, **documentation** | Testing ✓ |
| **1.5 — Piloted** (4–6 weeks) | TEI export; one or two external institutions running real batches; usage data collected | Testing ✓ |
| **Later** | Repository connectors, institutional SSO, shared public profiles | **Needs new funding** |

Two items moved *forward* from the original Phase 2 because they **reduce** the support burden rather
than adding to it: spend ceilings prevent the "why was I charged this much" conversation, and
documentation prevents most of the rest. For a solo operator, anything that answers a question before
it is asked belongs early.

### What was cut, and why

**The in-browser review-and-edit interface.** It was the largest share of the original Phase 2 and
carries the highest ongoing support surface of anything proposed here — edit state in the database,
concurrent edits to one record, autosave, lost work on refresh, and the support requests all of that
generates. Meanwhile our own 128-record batch was reviewed perfectly well in a spreadsheet. **There
is no evidence it is worth building.** Revisit only if an institution asks for it specifically.

**Arbitrary schema editing**, narrowed to template forking. Instead of a general profile editor,
ship three or four presets — Dublin Core, our LOC15 profile, a minimal profile — which a user forks
and adjusts: field names, vocabularies, trust assignments, fixed values. An order of magnitude less
configuration surface, an order of magnitude less support, and the "your rules, not Miami's"
commitment in Section 7.12 still holds.

### Survival after the grant

Hosting is an ongoing monthly cost plus operator attention, and the grant will not cover it. Three paths,
and the first and third should be pursued together:

1. **Absorb it into the Libraries' service budget.** The monthly cost is small, but it still needs
   someone to approve it as a standing commitment.
2. **Use it as evidence in the next proposal.** A working prototype with real usage data from pilot
   institutions is materially stronger than a plan.
3. **Keep the self-hosting path permanently viable.** `docs/ADOPTING_THIS_PIPELINE.md` and the public
   repository already make this possible. If the hosted service is ever retired, the grant's output
   does not disappear with it.

The honest framing for the hosted service is therefore **best effort, no service-level agreement**,
with self-hosting documented as the durable option. That framing is also what makes it defensible to
run as a solo operator.

## 8. Running costs

Users bring their own keys, so inference is not the operator's cost: roughly **$4–6 per 100-image
batch**, paid by the adopting institution to its own provider.

The hosting budget is kept with the grant materials, outside this public repository.

At the planned configuration the service supports about **8 concurrent institutions**, each
completing a 100-image batch in about **8 minutes**. The sizing follows from three measurements, not
from guesswork: **28 MB** peak memory per worker, **0.29 s** CPU per image, and **~120 s** wall-clock
per API call. Workers are blocked on the network over 99 % of the time, so concurrency is bounded by
memory and speed is bounded by the model provider — which is why the server is sized for memory and
durability rather than CPU.

Image retention is 24 hours by lifecycle rule, not 30 days. The shorter window is the better answer
for the security review and for how much of other institutions' material Miami holds.

---

## 9. Remaining open questions

The questions about operator, hosting model, editing interface, and funding are answered above. What
is left:

1. **What does "Miami's own servers" mean concretely?** University on-premise hosting often cannot
   run containers, terminate TLS for an external service, or open the firewall paths this needs.
   Confirm with Miami IT whether this is on-premise infrastructure or cloud that Miami pays for —
   the answer changes §2 substantially, and it is worth asking before Phase 0.
2. **Security review timing.** Holding third-party API credentials on a university-hosted service
   very likely requires an IT security review. Start that conversation during Phase 0, not before
   launch — a late "no" would invalidate the design.
3. **Which preset profiles ship first?** Dublin Core is the obvious default. The second and third
   should come from whichever pilot institutions actually sign up.
4. ~~**Image retention period.**~~ Settled: **24 hours**, enforced by an S3 lifecycle rule rather
   than by application code. See §2.2.
5. **Which repository platforms matter?** Still: do not build connectors speculatively.
