# Plan

Working plan for a solar-powered, locally-hosted RAG assistant for Richmond-area
sustainability questions. Decisions marked **[open]** still need a call.

---

## 1. Scope

### Question types to support (v1)

| Category | Example | Answer shape |
| --- | --- | --- |
| Disposal / recycling | "Where do I take old AA batteries?" | Place card(s) + what they accept |
| Curbside rules | "Can pizza boxes go in my bin?" | Yes/no + jurisdiction caveat |
| Hazardous & special waste | "Paint, motor oil, propane tanks, meds, tires" | Event schedule or facility card |
| Electronics | "Dead laptop and a CRT TV" | Facility card + fees |
| Composting | "Curbside compost pickup near the Fan" | Service list + how to start |
| Get involved | "River cleanups this month", "tree planting" | Org cards + contact |
| Reuse / repair | "Donate a couch", "fix a lamp" | Org cards |
| Energy & water | "Weatherization help", "rain barrel rebate" | Program card + eligibility |
| Transportation | "Bus pass", "bike routes" | Program card |

### Explicitly out of scope for v1

- Anything time-sensitive to the hour (today's bus delays, is the event cancelled).
- Legal, medical, or safety advice beyond quoting official guidance.
- Jurisdictions outside the Richmond metro (City, Henrico, Chesterfield, Hanover,
  plus regional/state programs). **[open]** include Goochland / Powhatan / New Kent?
- Languages other than English. Spanish matters a lot for this audience, but tiny models
  are weak multilingually — see §10.

### The jurisdiction problem

This is the single biggest correctness risk and it shapes the whole data model. Curbside
recycling for most of the metro runs through a regional authority, but accepted items,
bulk pickup, glass handling, and drop-off locations vary by locality. Every piece of
content gets a `jurisdiction` field (`richmond-city`, `henrico`, `chesterfield`,
`hanover`, `regional`, `virginia`), and the retriever filters on it.

Resolution strategy, in order:
1. User states it ("I'm in Henrico").
2. ZIP code → jurisdiction lookup table (ZIPs straddle lines; store the ambiguous ones).
3. Ask once, remember for the session.
4. If unresolved and the answer differs by jurisdiction, say so and give both.

---

## 2. Architecture

```
          ┌─────────────────────────────────────────────┐
  query → │ 1. Normalize + classify                     │  tiny intent/topic check,
          │    (in-scope? jurisdiction? needs_place?)    │  jurisdiction extraction
          └─────────────────────┬───────────────────────┘
                                ▼
          ┌─────────────────────────────────────────────┐
          │ 2. Hybrid retrieve                          │  numpy cosine  +  BM25,
          │    filter: jurisdiction ∈ {user, regional,  │  fused with Reciprocal Rank
          │    virginia}; fuse with RRF; top ~20        │  Fusion (see §3c)
          └─────────────────────┬───────────────────────┘
                                ▼
          ┌─────────────────────────────────────────────┐
          │ 3. Rerank (optional) → top 3–5 chunks       │  cross-encoder MiniLM, measured
          └─────────────────────┬───────────────────────┘  against its latency cost
                                ▼
          ┌─────────────────────────────────────────────┐
          │ 4. Confidence gate                          │  weak scores → refusal path
          └─────────────────────┬───────────────────────┘  (hotline + "I'm not sure")
                                ▼
          ┌─────────────────────────────────────────────┐
          │ 5. Generate prose wrapper (small LLM)       │  2–4 sentences, grounded,
          │    + 6. Render fact cards from structured   │  no invented specifics
          │         records (templated, not generated)  │
          └─────────────────────┬───────────────────────┘
                                ▼
                     answer + cards + sources + last_verified
```

Step 6 is the important one. The LLM output and the factual payload are **separate
channels**. A 1.7B model asked to restate "Monday–Friday 8am–4pm, 2539 Maury St" will
eventually produce "2593 Maury Street". So the model is prompted to refer to places by
name only, and the actual address/hours/phone block is emitted by the application from
the YAML record it retrieved. If the model names a place that isn't in the retrieved set,
that's a detectable error — log it and fall back.

---

## 3. Data layer

Two kinds of content, deliberately:

### 3a. Entity records — structured, hand-curated (`data/entities/*.yaml`)

The authoritative source for anything a user would act on. Target ~80–150 records for v1.

```yaml
id: cvwma-dropoff-maury-st            # stable slug
name: "<official name>"
type: dropoff_site                     # dropoff_site | event | org | program | service
scope: local                           # local | online  — see note below
jurisdiction: [richmond-city, regional]
topics: [waste, batteries]             # waste | water | energy | food | habitat |
                                       # transport | reuse | advocacy | education
accepts: [batteries-rechargeable, electronics, cfl-bulbs]
not_accepted: [alkaline-batteries, paint]
volunteer: false                       # true if they take volunteers
address: "..."
hours: "..."                           # free text; also structured_hours when parseable
phone: "..."
url: "https://..."
fees: "..."
notes_public: "Residents only; proof of residency required."
notes_internal: "Contact is <name>; we have a partnership."   # never retrieved, never shown
source_url: "https://..."
last_verified: 2026-10-01
verified_by: "<initials>"
```

Two fields earn their keep:

- **`scope: local | online`.** Not every useful resource is a place. A food-waste app, a
  carbon-neutral web host, or a national habitat campaign is genuinely helpful but answers
  a different question than "where do I take this." Retrieval should prefer `local` for
  *where/when* questions and allow `online` for *how/what can I do* questions — collapsing
  this into `jurisdiction` would make "Online / not local" a fake jurisdiction.
- **`notes_internal` is excluded from the index entirely.** Hand-maintained resource lists
  accumulate internal annotations — "active partnership in place", "we could put a
  collection bin in the office", "in case we're interested in adopting a road." Those are
  notes to colleagues, not facts about the organization, and a small model handed them in
  context will cheerfully relay them to the public. The split must exist at import time,
  because once it's all one `notes` column, nobody goes back and separates it.

Why YAML and not scraping: hours and accepted-item lists are exactly what must not be
wrong, they are small in volume, they change a few times a year, and a human reviewing a
diff is the cheapest possible QA. These records are rendered into cards *and* embedded as
retrievable text.

### 3b. Prose documents — scraped/collected, for context (`data/docs/*.md`)

Explanatory content: why glass is handled separately, how the city's combined sewer system
works, what the regional climate action plan commits to, how to start a compost pile. Each
file has front matter with `source_url`, `jurisdiction`, `topic`, `last_verified`,
`authority` (`official` | `nonprofit` | `community`).

Pipeline: `fetch` (snapshot raw HTML into `data/raw/`, committed) → `extract` (to Markdown)
→ `chunk` → `embed` → `index`. Raw snapshots are committed so the whole index is
reproducible and so a re-fetch produces a reviewable diff when a page changes. Respect
`robots.txt` and rate-limit; prefer official open-data endpoints over scraping where they
exist.

### Chunking

~400–600 tokens, split on headings first then sentences, 15% overlap, and **every chunk
carries its parent title + jurisdiction + source in the text itself** so a retrieved chunk
is self-describing when it lands in a short prompt. Entity records are one chunk each.

### 3c. Storage: plain text, not a database

**Decision: plain text files are the source of truth *and* the runtime store. No SQLite,
no vector database, for v1.**

The arithmetic settles it. A fully built-out corpus is ~150 entity records plus a few
hundred prose documents — call it **1,400 chunks**:

| | |
| --- | --- |
| Embedding matrix | 1,400 × 384 × 4 bytes = **2.1 MB** |
| Brute-force cosine scan | ~540k multiply-adds ≈ **< 1 ms** in numpy |
| Embedding the query itself | **10–30 ms** on a Pi 5 |
| Loading the whole corpus from YAML at boot | **tens of ms**, once |

Exact search costs roughly 1–3% of the query-embedding step that feeds it. An ANN index
(`sqlite-vec`, FAISS, LanceDB, Chroma) exists to make search sublinear at 10⁵–10⁹ vectors;
at 10³ it adds a build step, a binary artifact, a dependency, and *approximate* results in
exchange for saving under a millisecond. On a solar power budget the daemon-based vector
DBs are actively wrong — they hold RAM and burn idle CPU.

So:

- **Authoring + source of truth:** YAML / Markdown / CSV in git. Human-editable, diffable,
  reviewable in a PR, greppable, and the thing a volunteer can fix without tooling.
- **Runtime:** load at startup into a numpy array plus a Python dict. Keep a cached
  `.npy` of the embeddings keyed by a hash of the content so boot doesn't re-embed.
- **Keyword half:** an in-process BM25 (~50 lines, or `rank_bm25`).

**Startup cost.** Because the machine cold-boots on each use day (§7), boot time is a real
UX number, and the corpus is not what costs: loading YAML and a cached `.npy` is tens of
milliseconds. The cost is OS boot plus mapping a ~2 GB model file off storage — which is
the argument for **NVMe over an SD card**, worth maybe 30 seconds. Start `llama-server`
from a systemd unit at boot so the model is warm before anyone walks up at 9:00.

Keep retrieval behind a narrow interface — `search(query, filters) -> [(chunk_id, score)]`
— so the backend is swappable. **Revisit SQLite if** any of these becomes true:

1. Corpus exceeds ~50k chunks (it won't).
2. Several processes need concurrent access to the same index.
3. You want FTS5's stemming, prefix queries, and tuned ranking rather than hand-rolling
   them — this is the one genuinely good reason, and it's about text search quality, not
   vector scale.
4. Boot-time memory becomes tight *and* measurement shows the corpus, not the model, is
   the cause. (It won't be: the model is 1,000× larger than the corpus.)

If (3) bites, SQLite + FTS5 for the keyword half while keeping vectors in numpy is a fine
hybrid — and note `sqlite-vec` would still not be needed.

### 3d. `resources.csv` — the existing hand-maintained list

`resources.csv` (15 rows at time of writing) is the first real content and the model for
how curated input should arrive. Current columns, positionally (**no header row**):

`name, description, scope, url, notes`

It maps cleanly onto the entity schema: `name` → `name`, `description` → `description`,
`scope` (`Local` / `Online` / `Online / not local`) → `scope`, `url` → `url`, `notes` →
**split** into `notes_public` / `notes_internal`. Everything else (`type`, `topics`,
`jurisdiction`, `volunteer`, `last_verified`) is added during import.

**Fix at the source (in the spreadsheet), not in the importer:**

1. **Add a header row.** Positional parsing of a human-edited file breaks the first time
   someone inserts a column.
2. **Encoding is mangled.** Several cells contain `�` where a curly apostrophe or
   non-breaking space should be (`farmer�s`, `Climate�fresK`, `Xerces Society�`). Save as
   UTF-8 explicitly — LibreOffice asks for the encoding in *Save As → Edit filter
   settings*. Some URLs have a trailing non-breaking space that will break fetching.
3. **Two `url` cells are not URLs.** One holds a pasted page *title*
   ("Adopt-a-Highway | Virginia Department of Transportation") and one is missing its
   scheme (`ragandbonesrva.org`). The importer should hard-fail on a cell that doesn't
   parse as an absolute URL rather than silently indexing a dead link.
4. **Name typos become the bot's vocabulary.** "Accorn Host" → Acorn Host; "Scrap creative
   use" → SCRAP Creative Reuse; "Rag and bones" → Rag & Bones. The `name` field is what
   the model is allowed to say out loud, so it has to be the real name.
5. **One `description` is a pasted page title**, not a description.

**Ongoing editing workflow (as this grows past one person's spreadsheet):**

- **Editing surface:** a shared spreadsheet (Google Sheets or SharePoint/Excel Online —
  either works; pick whichever the team already lives in), with data-validation dropdowns
  on `scope` and `topics` so the enum drift seen in the original file can't recur.
- **Sync, not live dependency:** pull the sheet via its API on the dev machine or in CI,
  run it through the *same* importer/validator below, and open the result as a **PR with a
  reviewable diff** rather than auto-committing — the diff is the QA step. This sync never
  runs on the deployed device; the device is offline-first and ships with a frozen
  snapshot, never a live pull from Google/Microsoft at boot.
- **The transform stays deterministic code, not an LLM skill.** The same row must produce
  the same chunk text every run, or groundedness and the eval numbers in §6 stop being
  comparable across runs. There's a real place for an LLM in this workflow, just not here:
  helping a non-technical contributor *draft* a new row (research the org, suggest
  `topics`/`jurisdiction`, flag missing fields) with a human signing off before it lands in
  the sheet — assisting the person compiling facts, not generating facts shown to users.

**Import rules:**

- Import is **one-way**: CSV → generated YAML in `data/entities/`, with `id` derived from a
  slug of `name` so re-import is idempotent. Never write back to the CSV.
- Validate on import: absolute URL, non-empty name, `scope` in the enum, `last_verified`
  present. Fail loudly with the row number.
- Set `last_verified` at import and treat anything over ~6 months old as stale.

**What this list reveals about scope.** The plan's §1 table was waste-disposal-heavy; this
CSV is mostly *get involved* and *live differently*, and it adds whole categories the
taxonomy needs:

| New category | From the CSV | Example question |
| --- | --- | --- |
| Native plants / conservation landscaping | native plant nurseries, landscaping consultancies, leave-the-leaves | "What should I plant instead of a lawn?" |
| Food waste & local food | surplus-food apps, CSAs, food-justice farms | "What do I do with food I won't eat?" |
| Habitat & wildlife | river guardianship, pollinator habitat | "How do I help pollinators?" |
| Reuse (craft/materials) | creative-reuse donation centers | "Who takes craft supplies / fabric scraps?" |
| Oddly specific reuse | a cat rescue that collects empty pill bottles | "Can I recycle pill bottles?" |
| Litter cleanup | highway/roadside adoption programs | "How do I organize a cleanup?" |
| Training & education | sustainability workshops, efficiency consultancies | "Where can I learn about this?" |
| Greener consumer choices | carbon-neutral hosting, search that plants trees | "Are there greener alternatives to X?" |

That last pill-bottle row is the best argument in the file for this whole approach: no
general-purpose model will ever know that a specific Richmond cat rescue wants your empty
prescription bottles. That fact only exists because a person wrote it down.

### Taxonomy

A controlled vocabulary of item slugs (`batteries-alkaline`, `batteries-lithium-ion`,
`batteries-car`, `paint-latex`, `paint-oil`, `electronics-crt`, …) with a synonym map
("AA", "double A", "car battery", "vape", "power bank"). This is what makes a small model
viable: most queries are a synonym lookup away from an exact structured match, and the
synonym table catches what embeddings miss.

---

## 4. Model selection

Pick by measurement, not vibes. Candidates to benchmark (all Q4_K_M via `llama.cpp`):

| Model | Params | ~RAM @ Q4 | Notes |
| --- | --- | --- | --- |
| Qwen3 1.7B | 1.7B | ~1.2 GB | Strong instruction-following for its size |
| Llama 3.2 3B Instruct | 3B | ~2.0 GB | Good grounding behavior |
| Gemma 3 1B | 1B | ~0.8 GB | Fastest; test if it can stay grounded |
| Phi-4-mini | 3.8B | ~2.4 GB | Upper bound on what a Pi 5 tolerates |
| Llama 3.2 1B Instruct | 1B | ~0.8 GB | Floor case |

Rough Pi 5 expectation (CPU, memory-bandwidth bound): **~8–12 tok/s at 1B, ~4–6 tok/s at
3B**. With answers capped at ~120 tokens and SSE streaming, that's a 10–30 second answer —
acceptable, and much better than it sounds because the fact cards render instantly from
retrieval, before the prose arrives.

**The power budget does not constrain this choice** — at a 16 h/week duty cycle (§7) even
the 4B tier fits with ~2× winter margin, so pick purely on answer quality and latency. RAM
is the real ceiling: a 3–4B model at Q4 plus the embedding model wants the 16 GB Pi 5, or at
least 8 GB with nothing else running.

Selection criteria, in priority order:
1. **Groundedness** — does it refuse when context is insufficient, or does it fill in?
2. **Instruction adherence** — does it respect "name the place, don't restate the address"?
3. Tokens/sec and watt-hours per answer.
4. RAM headroom (leaves room for embeddings + OS).

**[open]** Whether a reranker earns its latency, and whether a static embedding model
(e.g. a model2vec-style distillation) is accurate enough to drop the transformer encoder
entirely — that would cut per-query energy noticeably.

### Running the bake-off: not hard, and it's the thing to do before buying hardware

This isn't a separate effort — it's the eval harness from §6 pointed at five GGUF files
instead of one. The whole point of building the harness first is that swapping models
becomes a one-line change (`llama-server -m <other model>.gguf`), not a rewrite:

1. Pull each candidate's GGUF (Q4_K_M) — a few minutes each, Hugging Face hosts
   pre-quantized builds for all five.
2. Run the same golden set (§6) through each, recording the same metrics table.
3. On the **dev machine first** (any laptop) to answer the question that actually matters
   — *does accuracy hold up at this size, at all* — before spending a cent on hardware. A
   1B model that can't stay grounded on the dev machine won't improve on target hardware.
4. Re-run the shortlist (whatever clears a groundedness bar, say 2–3 candidates) **on
   actual target hardware** — a borrowed/rented Pi or N100 — only for tok/s, latency, and
   Wh/answer. Accuracy doesn't change with hardware; speed and power do.

Expect maybe a day of wall-clock (mostly waiting on generations, not engineering) to get a
table like:

| Model | Groundedness | Fabricated-specific rate | p50 latency | Wh/answer |
| --- | --- | --- | --- | --- |
| Llama 3.2 1B | … | … | … | … |
| Gemma 3 1B | … | … | … | … |
| Qwen3 1.7B | … | … | … | … |
| Llama 3.2 3B | … | … | … | … |
| Phi-4-mini 3.8B | … | … | … | … |

**That table is the actual hardware decision.** If groundedness is roughly flat from 1B to
3B — plausible, since the job here is narrow (select + paraphrase retrieved text, not
recall facts from weights) — the 1B tier wins outright: cheaper board, lower power, more
margin on every number in §7, and the N100-vs-Pi price question in §7 stops mattering much
either way. If groundedness jumps meaningfully at 3B, that jump is worth the extra RAM and
the ~2× power draw, and it justifies paying for 16 GB. Don't guess which outcome you'll
get — the five-model run costs a day and removes the guess entirely, and every other
hardware number in this document (§7's panel size, §7's budget packages, the RAM line in
the platform choice above) is downstream of this one result.

---

## 5. Prompting

System prompt sketch:

```
You answer questions about recycling, waste disposal, and sustainability in the
Richmond, Virginia area, using only the SOURCES below.

Rules:
- Use only facts stated in SOURCES. If SOURCES do not answer the question, say
  "I don't have that in my sources" and nothing more.
- Refer to places and organizations by name only. Never write an address, phone
  number, price, or set of hours — those are added automatically after your answer.
- 2 to 4 sentences. Plain language. No bullet lists, no preamble.
- If SOURCES apply to a different locality than the user's, say so.

SOURCES:
[1] (richmond-city, verified 2026-10-01) <chunk>
[2] ...
```

Keep the prompt short — small models degrade with long instructions, and every system
token is tokens/sec spent. Budget: ≤250 system tokens, ≤1200 context tokens, ≤160 output.

Output gets a post-generation check: does it contain digits/street patterns not present in
the retrieved sources? Does it name an entity not in the retrieved set? Either → drop the
prose and show cards only. This guardrail means a bad generation degrades to a plain
directory answer rather than a wrong one.

---

## 6. Evaluation

Build this **before** tuning anything, and run it on both the dev machine and the target
hardware.

**Golden set: ~100–150 questions** written from real phrasing (short, misspelled, vague —
"wher do i put batterys"), each labeled with: expected jurisdiction, the entity/doc IDs
that must be retrieved, a correct-answer rubric, and an `expect_refusal` flag for the ~15%
that the corpus genuinely can't answer.

Metrics:
- **Retrieval recall@5** — did the needed document make the context? (The ceiling on
  everything else; fix this first.)
- **Groundedness** — fraction of answer claims supported by retrieved text.
- **Fabricated-specific rate** — any address/phone/hour/price not in sources. Target zero.
- **Refusal correctness** — refuses when it should, doesn't when it shouldn't.
- **Jurisdiction accuracy** — right locality's rule.
- **p50/p95 latency to first token and to completion**, on the Pi.
- **Watt-hours per answer.**

Grading: deterministic checks (ID match, regex for fabricated specifics, refusal
detection) cover most of it. For groundedness and rubric judgment, use a **frontier model
as an offline judge on the dev machine** — `claude-opus-5` via the Anthropic API, run as a
batch over eval outputs. Same tool helps draft the question set and adversarial
paraphrases. This is strictly a development-time dependency: nothing on the Pi ever calls
out to an API.

---

## 7. Hardware & power

### Duty cycle — the decisive constraint

**The device is used in person 2 days a week.** It harvests for 7 days and runs for 2, and
it can be **fully powered down the other 5**. That 3.5× harvest-to-use ratio changes the
engineering problem: this is a *battery-buffered intermittent load*, not a 24/7 server.

Two consequences, both good:

- **Idle power stops being the dominant term.** Most always-on solar Pi projects are
  limited by 3–4 W × 24 h of doing nothing. Off five days a week, that term nearly vanishes,
  and the only energy that matters is energy spent answering questions.
- **The energy budget can afford a better model.** The headroom below is large enough that
  moving from the 1B tier to the 3–4B tier — and adding the reranker — is affordable.
  Spend the watts on groundedness; that's the metric that decides whether this works.

### Energy budget

Operating hours are **9–5 on two days a week — 8 hours per use day, 16 hours per week of
runtime out of 168.** Pi 5 averages ~5 W light-duty and ~11 W under sustained inference on
a 3–4B model.

Note that ~11 W is a *worst case*: it assumes the CPU is generating tokens continuously for
eight hours. Real kiosk traffic is bursty — a few dozen questions across a day, each a
~20-second burst, with the machine idling between — so the realistic use-day average sits
much closer to the light-duty figure. The table below budgets for the worst case anyway;
the margin is cheap at this scale.

| Scenario | Per use day | **Per week (2 days)** |
| --- | --- | --- |
| Light use, 1B model (~5 W avg) | 40 Wh | **80 Wh** |
| Heavy use, 3–4B model (~11 W avg) | 88 Wh | **176 Wh** |
| Plus 5 days of controller + battery parasitic draw (see below) | — | **+25–45 Wh** |
| Design target | — | **~250 Wh/week** |

Harvest, using Richmond's ~4.5 peak-sun-hours/day annual average and under 3 in December,
at a 0.65–0.7 system derate:

| Panel | Summer | **December** | December vs. 250 Wh target |
| --- | --- | --- | --- |
| 20 W | ~440 Wh/wk | ~230 Wh/wk | 0.9× — too tight |
| **50 W** | ~1,100 Wh/wk | **~570 Wh/wk** | **2.3× — recommended** |
| 100 W | ~2,200 Wh/wk | ~1,140 Wh/wk | 4.6× — over-provisioned |

**50 W is the sweet spot**, keeping ~2× margin through the worst month to absorb a run of
overcast days, winter panel soiling, and a heavier-than-planned model. The earlier 100 W
figure assumed 24/7 operation and is no longer justified.

- **Panel: 50 W** nominal. **[open]** Mounting — a window-mounted panel loses a lot to
  glass and off-angle incidence; if it can't go outside or on a sill with real sky view,
  step up to 100 W to compensate.
- **Battery: LiFePO4, ~250–300 Wh** (e.g. 12 V / 20–24 Ah). Rationale: it must carry two
  consecutive heavy use days (176 Wh) without going below ~40% state of charge, so the pack
  shouldn't be smaller than ~250 Wh. Bigger buys dark-week insurance, and LiFePO4 lasts
  longer when shallow-cycled — but the panel, not the battery, is the winter bottleneck.
- **Charge controller: MPPT with a low quiescent current and low-voltage disconnect.**

### The parasitic-draw trap

With the Pi off 5 days a week, **the charge controller's own idle draw becomes a comparable
line item to the actual workload.** A typical MPPT controller pulls 10–20 mA at 12 V:

> 0.15–0.25 W × 24 h × 7 days = **25–42 Wh/week** — i.e. 10–20% of the total budget, spent
> doing nothing, plus LiFePO4 self-discharge (small, ~2–3%/month) and any BMS overhead.

This is the one place where chasing milliwatts actually pays. Check the quiescent-current
spec before buying, and prefer a controller that publishes it.

### Power optimizations, re-ranked for a 2-day duty cycle

1. **Hard power-down outside 9–5 on use days.** Full shutdown, not sleep — the machine is
   off 152 of 168 hours a week, and that's the entire ballgame. The Pi 5 has a real-time
   clock with wake-on-alarm, so it can schedule its own 8:45 wake and `shutdown` at 5:15;
   simpler still, someone is physically present on use days, so a switch or button works.
   **[open]** scheduled wake vs. manual power-on. Either way, boot must be fast enough that
   nobody is waiting — see the startup-cost note in §3c.
2. **Low-quiescent charge controller** (above).
3. **Cap output tokens hard.** Generation dominates active-hours energy; a 160-token
   ceiling roughly halves per-answer cost versus letting it ramble.
4. **Serve structured answers without the LLM** when an exact taxonomy match exists —
   the card alone answers "where do batteries go," at zero inference cost.
5. **Answer cache.** Now justified primarily by *latency*, not energy: a cache hit returns
   instantly instead of after 20 seconds, which matters a lot more with a person standing
   there. Keep it, re-frame it.
6. **Idle model unload** during the use day — still worth it over an 8-hour day with
   bursty traffic, but no longer critical.
7. **Run ingest and re-embedding on a use day** (or on grid power at a desk) — it's a
   batch job on a machine that's off most of the week, so just don't do it on battery.
8. CPU governor tuning, headless, disable HDMI/Bluetooth/LEDs.
9. **Brownout mode**: below a battery threshold, serve cache + cards only, no generation.
   Demoted to a safety net rather than a routine operating mode.

Instrument with an inline USB-C power meter and log Wh/query into the eval report, so "did
this change cost power" is answerable. Separately, log standby draw across a full off-week
once — that number is easy to assume and easy to get wrong.

### Access mode — open decision: single attached device vs. LAN server

**Not decided, and it's a real fork** — not a UI detail, since it changes concurrency
handling, network setup, and hardware cost.

| | **Single attached device** | **LAN server (people's own laptops)** |
| --- | --- | --- |
| What it is | One known screen (small touchscreen, or a reused old monitor/laptop) physically with the box | FastAPI app reachable over Wi-Fi; any laptop on the LAN opens it in a browser |
| Concurrency | Effectively one user at a time — default single-slot `llama-server` queuing is correct, not a limitation | Multiple people could query at once: either queue behind one slot (simple; an occasional extra 10–30 s wait during a burst) or run `llama-server --parallel N` (each slot duplicates KV-cache RAM — a real cost on an 8 GB box, fine on 16 GB) |
| Display hardware | Needs a screen — new 7–10" touchscreen (~$75) or $0 if reusing hardware already on hand | None — headless, that line item disappears |
| Network | Can skip Wi-Fi entirely (direct ethernet, or no network at all) | Needs LAN reachability — join existing Wi-Fi (ask whoever runs it) or have the box host its own isolated AP / a cheap travel router (~$25–40) so nothing else has to change |
| Error visibility | Whoever's at the screen sees a bad answer immediately | Errors happen on someone else's laptop, unobserved — this makes the logging and the "that was wrong" affordance in §8 more load-bearing, not less |
| Complexity | Lower | Slightly higher — basic LAN hygiene, bursty concurrent load |

**Leaning recommendation if nothing else decides it: LAN server.** It's cheaper (no
display hardware), it matches how people actually want to use a chatbot — on their own
device — and single-slot queuing handles low, bursty traffic fine, since the 10–30 s
generation time is already the bottleneck. Revisit if real usage shows several people
hitting it in the same minute; `--parallel 2` on a 16 GB box absorbs that.

**Either way: LAN-only, never internet-exposed.** No tunnel, no port-forward, no public
URL — a solar-powered single box has no business taking traffic from the open internet.
This supersedes the `[open]` Tailscale/tunnel line in §8 below; that line was written
before this constraint was confirmed and should be struck.

### Budget packages

Rough, **live-searched pricing as of Oct 2026 — not quotes.** The market here is moving
fast (see the DRAM-shortage note above); recheck before buying. Each column is one
coherent set of decisions; mix line items freely.

| Line item | **Pkg 1 — Budget**<br>N100 8 GB, LAN server | **Pkg 2 — Recommended**<br>N100 16 GB, LAN server | **Pkg 3 — Pi-based**<br>Pi 5 16 GB, single device | **Pkg 4 — Extra margin**<br>N100 16 GB, LAN, 100 W |
| --- | --- | --- | --- | --- |
| Compute (RAM + storage included on the N100; Pi is bare-board) | N100 mini PC 8 GB — $120 | N100 mini PC 16 GB — $180 | Pi 5 16 GB board — $250 | N100 mini PC 16 GB — $180 |
| Cooling / case | included | included | $15 | included |
| Storage | included | included | NVMe HAT + drive — $45 | included |
| Display | — | — | 7" touchscreen — $75 | — |
| Network | Travel router — $30 | Travel router — $30 | — | Travel router — $30 |
| Solar panel + MPPT | 50 W kit — $100 | 50 W kit — $100 | 50 W kit — $100 | 100 W kit — $180 |
| Battery | 256 Wh LiFePO4 — $110 | 256 Wh LiFePO4 — $110 | 256 Wh LiFePO4 — $110 | 384 Wh LiFePO4 — $220 |
| Wiring / fuses / enclosure | $30 | $30 | $30 | $30 |
| **Total** | **~$390** | **~$450** | **~$625** | **~$640** |
| Model tier it supports | 1B only | 3–4B comfortably | 3–4B comfortably | 3–4B comfortably |
| December power margin | ~2.7× | ~1.7× | ~2.6× | ~3.5× |

Notes on the numbers:

- **The N100 packages assume LAN-server mode (no display cost); Package 3 assumes single
  device (so it carries the touchscreen).** That's the two open decisions compounding —
  swap either axis and re-total.
- **Pi 5 pricing is the volatile one.** The DRAM shortage noted above means Package 3's
  $250 board could be meaningfully higher or (if the shortage eases) lower by the time
  this gets bought. N100 boards use DDR4, which hasn't spiked the same way — part of why
  they're currently the cheaper *all-in* route despite higher power draw.
- **Package 2's 1.7× December margin is the tightest of the four** because the N100 draws
  roughly double the Pi's power for the same 16 h/week active time. It's still comfortable
  margin, just worth knowing it's thinner than the Pi route — Package 4 exists as the
  fix if that margin feels too tight (bigger panel + bigger battery, ~$190 more).
- **None of this should be bought before the model bake-off in §4.** If that result says
  1B is indistinguishable from 3–4B on groundedness, Package 1 at $390 is the answer and
  the whole 16 GB / bigger-battery conversation is moot.

---

## 8. Serving & interface

- `llama-server` (llama.cpp) on localhost for completions and possibly embeddings. **Built
  so far (src/rva_chat/serve/) uses Ollama**, matching the dev-machine choice in §8's
  Docker note and §4 — swap at deployment, see llm.py's docstring.
- FastAPI app (`src/rva_chat/serve/app.py`): `/chat` (SSE, GET), `/chat-plain` (POST,
  no-JS), `/healthz`, `/metrics`, `/admin/stale`.
- **Built differently from the original "streams tokens" plan, deliberately:** a guardrail
  that can only judge the *complete* answer can't un-send words a user already saw —
  streaming prose token-by-token and then discarding it for failing the grounded-check
  (§5) is either impossible or requires a jarring "retract what you just read" UI. So
  `/chat` streams two SSE events instead of a token stream: `cards` fires immediately on
  retrieval (the actual UX goal — something visible in <1 s while the model is still
  running), then `answer` fires once, carrying the complete, already-guardrail-checked
  text (or the drop reason, if it failed). `done` closes the stream. This keeps "a bad
  generation degrades to cards-only, never a wrong answer" fully intact; the cost is the
  prose appearing all at once after generation finishes rather than growing word by word.
  Revisit if a faster model (§4 bake-off) makes the wait feel short enough that it's not
  worth the tradeoff, or if an incremental guardrail gets built.
- Front end: one static page (`templates.py`), vanilla JS, no build step, dark/light aware.
  Mobile-first, large tap targets — this gets used standing in a garage holding a dead
  battery.
- **No-JS fallback, implemented as progressive enhancement, not a separate page:** one
  `<form method="POST" action="/chat-plain">` serves both paths. JS intercepts `submit`
  and talks to `/chat` via `EventSource` (which only does GET — hence `/chat` being GET
  with `q` as a query param, not a POST body); when JS is off, the browser's native POST
  hits `/chat-plain`, which re-renders the *same* page shell with the question pre-filled
  and the answer/cards already in place. One template, one set of styles, two entry points.
- Access: LAN-only, permanently — see §7's access-mode decision (single device vs. LAN
  server). No tunnel, no public exposure, in either mode. `uvicorn ... --host 0.0.0.0` only
  at actual deployment; the dev-machine default binds `127.0.0.1`.
- Privacy: the query log (`src/rva_chat/serve/telemetry.py`) writes query text, matched
  entity IDs, grounded-check result, and latency — never an IP, user-agent, or session
  id. A `no_log` checkbox in the UI (and query param on `/chat`) skips logging for that
  request. Rotation is by calendar day (`logs/queries-YYYY-MM-DD.jsonl`), not a logging
  framework — enough for one low-traffic box. `/admin/stale` reuses the "~6 months" rule
  from §3d (`STALE_DAYS_DEFAULT = 180`) to list entities due for re-verification.
- **Containerization: skip Docker for v1.** The overhead is small in absolute terms
  (~50–100 MB RAM for the daemon, ~5–15 s added to a boot you're already doing on a cold
  schedule) but it buys little here: this is one box running one install, not a fleet, and
  `llama.cpp` wants compiling with CPU-specific flags (NEON on ARM, AVX2 on the N100)
  either way — Docker doesn't remove that step, it just adds a layer around it. Run
  `llama-server` natively + a Python venv for the FastAPI app, each as its own systemd
  unit. For the reproducibility Docker would normally buy, a full disk image snapshot
  (`dd`, or Raspberry Pi Imager's custom-image save) is actually the stronger story for a
  single physical device — reflash and you're back to a known-good state, no rebuild.
  **Reconsider Docker if** this ever deploys to multiple physical sites and parity across
  them starts to matter, or a specific service genuinely needs isolation from the rest.

---

## 9. Repository layout (proposed)

```
data/
  entities/        *.yaml           curated place/org/program records
  docs/            *.md             prose content with front matter
  raw/                              committed source snapshots
  taxonomy/        items.yaml       item slugs + synonyms
  zips.yaml                         ZIP → jurisdiction map
  imports/         resources.csv    hand-maintained spreadsheets (see §3d)
cache/
  embeddings.npy                    content-hash-keyed, rebuilt on change (not committed)
src/rva_chat/
  ingest/          fetch.py extract.py chunk.py embed.py import_csv.py
  retrieve/        corpus.py search.py (BM25 now; rerank.py/jurisdiction.py pending)
  generate/        prompt.py llm.py guardrails.py cards.py
  serve/           app.py telemetry.py templates.py  (built — see §8)
  cli.py                                              (built — terminal chat, Phase 1)
eval/
  goldens.yaml  run_eval.py  judge.py  reports/
bench/
  models.py  power.py
docs/
  PLAN.md  DATA_SOURCES.md
```

---

## 10. Risks and open questions

| Risk | Mitigation |
| --- | --- |
| **Stale content** — hours/programs change, user shows up to a closed facility | `last_verified` shown in every answer; `/admin/stale` queue; quarterly re-verification pass; link-rot checker in CI |
| **Hallucinated specifics** | Facts rendered from records, never generated; regex guardrail; fabricated-specific rate tracked at zero |
| **Jurisdiction mix-ups** | Mandatory `jurisdiction` field; filtered retrieval; ask-once resolution; dual answers when unresolved |
| **Small model can't follow the grounding rules** | Benchmark groundedness first; if the 1B tier fails, move up to 3B and spend the watts; worst case, fall back to cards-only + template answers with the LLM used only for query understanding |
| **Retrieval misses colloquial phrasing** | Synonym table; hybrid BM25 catches exact words embeddings blur; log every low-confidence query and mine it for new synonyms |
| **Scraping terms of service / fragility** | Prefer official open data; snapshot + rate-limit; favor curated YAML over scraped prose for anything that matters |
| **Solar shortfall in winter** | Oversize panel, brownout mode, optional grid trickle-charge fallback |
| **Spanish-speaking users unserved** | v1 English-only and honest about it. v2 options: a multilingual embedding model + curated Spanish entity fields (the cards are the valuable part and they translate cleanly), rather than trusting a 1B model to generate Spanish prose |
| **Liability on hazardous materials** | Never improvise; quote official guidance and link it; explicit disclaimer for hazardous categories |

---

## 11. Phases

**Phase 0 — Corpus (no code).** Clean up `resources.csv` per §3d (header row, UTF-8, real
URLs, corrected names, notes split). Verify the source list in `DATA_SOURCES.md` by hand.
Write 25 entity records covering the top disposal questions — the category the CSV doesn't
cover. Draft the item taxonomy. Write 40 golden questions. *Done when: a human can answer
the top 25 questions from the YAML alone.*

**Phase 1 — RAG on the dev machine.** CSV importer, YAML loader, embeddings cache, hybrid
retrieval in-process (§3c), card rendering, prompt v1, one candidate model. *Done when:
end-to-end answers in a terminal.*

**Phase 2 — Eval harness.** Full golden set, deterministic checks + offline judge, baseline
report. *Done when: a number exists for recall@5, groundedness, and fabricated-specific rate.*

**Phase 3 — Model bake-off.** All candidates × quantizations against the eval; pick on
groundedness first. *Done when: a model is chosen with data behind it.*

**Phase 4 — Port to the Pi.** Cross-check eval parity, measure latency and Wh/query, add
cache + idle unload + brownout mode. *Done when: p95 answer < 30 s and Wh/query is logged.*

**Phase 5 — Interface.** Web UI, streaming, cards, mobile, accessibility, no-JS fallback.

**Phase 6 — Solar.** Panel/battery/MPPT, a week of logged uptime through real weather.

**Phase 7 — Maintenance.** Re-verification workflow, link-rot CI, low-confidence query
review, corpus growth to full coverage.

Phases 0–2 are the ones that determine whether this works. The hardware is the easy part.
