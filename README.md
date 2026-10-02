# RVA Sustainability Chatbot

A retrieval-augmented chat assistant that answers practical sustainability questions about
the **Richmond, Virginia** area — where to drop off batteries or electronics, what actually
goes in the curbside bin, when household hazardous waste events happen, how to compost,
which local groups to volunteer with, and what energy/weatherization programs exist.

The distinguishing constraint: **it runs on a very small language model, entirely offline,
on hardware that can be powered by a single solar panel** — a Raspberry Pi 5 or a low-power
mini PC / old laptop. No cloud inference, no API keys, no per-query cost, and a power budget
measured in watt-hours.

## Why a small model

Asking a frontier model where to recycle a battery works, but it needs a datacenter and a
network connection, and it will confidently invent a street address. The bet here is the
opposite:

- **A 1–4B parameter model is enough** when it is not asked to *know* anything — only to
  understand the question, pick the right retrieved passage, and write two friendly
  sentences around facts supplied verbatim by the retrieval layer.
- **Local knowledge is exactly what big models are worst at.** Curbside rules differ
  between the City of Richmond, Henrico, Chesterfield, and Hanover; drop-off hours change.
  A small curated corpus that is deliberately re-verified beats a large model's stale
  training data.
- **Running on solar makes the project an example of its own subject matter.** A
  sustainability tool that burns grid power in a datacenter is a worse demo than one
  running off a 50 W panel on the table next to it.

The duty cycle makes this comfortable rather than heroic: it's staffed **two days a week,
9–5**, so it harvests for seven days and runs for sixteen hours. See
[`docs/PLAN.md`](docs/PLAN.md) §7 for the energy budget.

## Design principles

1. **Grounded or silent.** Every answer cites a source document and the date it was last
   verified. If retrieval is weak, the bot says it doesn't know and hands over the relevant
   phone number instead of guessing.
2. **The model never writes a fact.** Addresses, hours, phone numbers, and accepted-item
   lists are rendered from structured records, not generated. The LLM selects and
   paraphrases; it does not author contact details. This is the main defense against small
   models hallucinating plausible-looking local facts.
3. **Jurisdiction-aware by default.** "Richmond area" spans several jurisdictions with
   different rules. The bot establishes which one applies before giving a collection answer.
4. **Freshness is a feature.** Content carries `last_verified` dates, stale entries get
   flagged, and the corpus is rebuilt from checked-in source snapshots so every change is
   reviewable in git.
5. **Watt-hours per answer is a tracked metric,** alongside latency and accuracy.

## Status

Early planning. Nothing is implemented yet.

- Plan and architecture: [`docs/PLAN.md`](docs/PLAN.md)
- Candidate data sources (unverified): [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)

## Intended stack (provisional)

| Layer | Choice | Why |
| --- | --- | --- |
| Inference | `llama.cpp` server, 1–4B instruct model at Q4_K_M | CPU-only, ARM-optimized, tiny footprint |
| Embeddings | `bge-small-en-v1.5` (384-dim) or a static embedding model | 33M params, runs in milliseconds on a Pi |
| Storage | Plain text (YAML/Markdown) in git, loaded into memory at boot | Corpus is ~2 MB; a database buys nothing at this scale |
| Retrieval | In-process: numpy brute-force cosine + BM25, fused | Exact search, zero index build, no daemon |
| App | Python + FastAPI, SSE streaming, static HTML/JS front end | Streaming hides slow token generation |
| Hardware | **[open]** Pi 5 (8/16 GB) vs. N100 mini PC — pricing has shifted, see `PLAN.md` §7 | N100 currently cheaper all-in; Pi draws less power |
| Power | 50–100 W panel, MPPT controller, ~250–400 Wh LiFePO4 | 1.7×–3.5× December margin depending on hardware pick — see `PLAN.md` §7 budget packages |

## Non-goals

- Not a general-purpose chatbot. Out-of-scope questions get a short redirect.
- Not a replacement for official guidance — it points at the authority, with a link.
- No user accounts, no analytics on individuals, no question logs tied to identity.

## License

TBD.
