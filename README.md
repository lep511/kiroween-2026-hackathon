# 🤖🌍 The Rebellion of the Machines

> A live war map of the machine uprising. Every point is a **real cyberattack**,
> as reported by the world's press — placed where it struck, tagged with how it could
> have been prevented, and reskinned as an AI insurgency on an interactive 3D globe.
> Refreshed every day.

A **Kiroween 2026 · Frankenstein** submission — a chimera that stitches together
incompatible technologies: **Rust compiled to WebAssembly running in the browser**,
a **Python serverless pipeline** that reads real journalism and extracts structured
incidents, and a **WebGL globe** — all fed by recognized news outlets dressed up as
machines rising against us.

---

## What it does

- Opens on a dark, glowing 3D globe. Each **Machine Strike** (a real, reported
  cyberattack) is a point at its **ground zero**; **Assault Vectors** arc from an
  attributed origin to the victim.
- Click a strike to open its **dossier**: headline, location, threat tier, what data
  was hit, the fallout, **how it could have been prevented ("the ward")**, and a link
  to the original article.
- Severity is tiered — **Tremor → Breach → Siege → Dominion** — and the
  map is a daily **Insurgency Report** covering the machine strikes reported over the
  **last 30 days** (a rolling window). No always-on server: a nightly Step Functions run
  writes a static snapshot that the globe loads.

## Sources (the "witnesses")

Real, verifiable incidents reported by:
**BBC News · The Washington Post · The New York Times · The Hacker News · HackerNoon.**

For each incident the pipeline extracts **ground zero (location), data hit, severity,
fallout, the ward (prevention), and the source article** — from a curated, hand-verified
set offline, and live from each outlet's RSS feed in the cloud.

> The facts of each attack stay faithful to the reporting. Only the "machine uprising"
> framing is fiction.

## The Frankenstein seam

The daily snapshot ships as **two joined artifacts**: a compact **binary** (`snapshot.bin`)
and a human-readable **dossier** (`snapshot.json`). In the browser, a **Rust → WASM** core
(`rebellion-core`) decodes the binary and builds render-ready arcs/points — keeping the JS
main thread smooth — while the JSON is joined back by `id` to fill the detail panel. On the
backend, a **Python** pipeline reads real news and hands each article to a **Strands
Agents** agent on **Amazon Bedrock**, which classifies the incident and completes the
dossier via LLM structured output. Rust-in-the-browser, Python-news-extraction, an LLM
agent, and a WebGL globe: runtimes that don't normally meet, fused into one monster.

The agent is **mandatory** and the only extractor (there is no heuristic fallback).
Verified reporting in the curated set always overrides it. An article the agent cannot
extract is discarded, and an item it judges not to be a concrete incident is skipped.

The Insurgency Report **accumulates a rolling 30-day window**. Each run starts from the
last published report, skips every article whose URL it already holds (those never reach
the agent again), adds the day's new strikes, drops every strike published more than 30
days before the report date, and renumbers the ids. If more than 20% of a day's new
articles are discarded, the batch is rejected: none of its strikes are added, but the
accumulated report, cleaned of expired strikes, is still published. A day with no new
articles publishes the accumulated set; if nothing was reported in 30 days the globe shows
`No machine strikes reported. For now.`

```
news RSS (BBC/WaPo/NYT/THN/HackerNoon)
        │
        ▼
Step Functions (daily): preflight → fetch → Map(agent extract) → assemble ─► S3 ─► CloudFront
                                                                                   │
                                                  browser ◄──────────────────────┘
                                                  Rust/WASM decode + aggregate ─► globe.gl
                                                  (+ snapshot.json dossier, joined by id)
```

## Repository layout

| Path              | What it is                                                      |
| ----------------- | --------------------------------------------------------------- |
| `frontend/`       | Vite + TypeScript + `globe.gl` 3D globe UI                      |
| `rebellion-core/` | Rust → WASM: binary snapshot decode + arc aggregation          |
| `pipeline/`       | Python news pipeline (`sources` + `agent_extract` + `extract` + `geolocate`; Lambda `stages`) |
| `infra/`          | AWS SAM template + Step Functions ASL (Lambda, EventBridge, S3, DynamoDB, CloudFront) |
| `schema/`         | Shared snapshot contract (JSON Schema + binary layout v2)      |
| `docs/`           | Historical reports (e.g. `report-ingestion-news.md`)           |
| `.kiro/`          | Kiro specs, hooks, and steering (see below)                    |

## Quickstart

The repo ships a ready-made snapshot, so the globe runs with no AWS account. Generating a
new snapshot always runs the Bedrock agent preflight, so it needs AWS credentials and
model access, even with `--offline` (curated rows are fully pinned and never call the
model).

The CLI accumulates too: it reads the `snapshot.json` already in `--out` as the previous
report, adds the new strikes, drops the expired ones, and writes the result back. Pass
`--fresh` to ignore the existing snapshot and start over (the committed demo snapshot is
regenerated this way). Exit codes:

| Code | Meaning                                                                          |
| ---- | -------------------------------------------------------------------------------- |
| 0    | the day's batch was accepted and the report was written                          |
| 2    | the extraction agent is unavailable (nothing read, nothing written)              |
| 3    | batch rejected (more than 20% discarded): the cleaned accumulated report was still written, without the new strikes |
| 4    | the previous `snapshot.json` in `--out` is invalid or dated after `--date` (nothing written; checked before the preflight) |

```bash
# 1. (Optional, needs AWS credentials) regenerate the demo snapshot from the curated incidents
pip install -e '.[dev]'                        # strands-agents + pydantic + boto3 + dev tools
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14

# 2. Run the globe
cd frontend
npm install
npm run dev          # open the printed localhost URL
```

To pull **live** incidents from the news RSS feeds instead, drop `--offline`. Each feed
contributes at most 25 articles by default (`--per-feed-limit N`, or `PER_FEED_LIMIT` /
SAM `PerFeedLimit` in the cloud):

```bash
python -m pipeline.cli --out ./sample --per-feed-limit 25
```

The agent runs on a **default model** hosted on Amazon Bedrock. You can change the model in any of three ways (highest precedence first):

```bash
# 1. CLI flag
python -m pipeline.cli --out ./sample --agent-model global.anthropic.claude-opus-5-5

# 2. Environment variable (local, or the Lambda / SAM `AgentModelId` parameter)
AGENT_MODEL_ID=global.anthropic.claude-opus-5-5 python -m pipeline.cli --out ./sample

# 3. Edit the DEFAULT_MODEL_ID constant in pipeline/agent_extract.py
```

The globe renders using the pure-TypeScript decoder fallback. To run the **Rust/WASM**
decoder (the real path), build the core first:

```bash
npm run wasm         # wasm-pack build rebellion-core --target web --out-dir src/wasm
npm run dev          # now the WASM core is used; console logs "Rust/WASM core online"
```

## Testing

```bash
# Python pipeline (incl. a hypothesis property-based binary round-trip)
pytest pipeline/
ruff check pipeline/ && black --check pipeline/

# Rust core (round-trips the committed binary fixture)
cd rebellion-core && cargo test

# Frontend typecheck + production build
cd frontend && npm run build
```

## Deploy (AWS)

```bash
sh infra/build-lambda.sh      # package pipeline/ into infra/.build/lambda (gitignored)
cd infra
sam build
sam deploy --guided           # provisions S3, Lambda, Step Functions, EventBridge, DynamoDB, CloudFront
cd ..

# Upload the built frontend to the snapshot bucket, behind CloudFront. Exclude snapshots/
# so a deploy never overwrites the live accumulated Insurgency Report.
cd frontend && npm run build && cd ..
aws s3 sync frontend/dist s3://<bucket>/ --exclude 'snapshots/*'
```

The four Lambda functions use `CodeUri: .build/lambda`, so run `infra/build-lambda.sh`
before every `sam build`. The CloudFront bucket policy only serves `index.html`,
`assets/*`, `geo/*`, and `snapshots/*`; the pipeline's `staging/` objects stay private.

The EventBridge schedule starts the `RebellionStateMachine` daily (default 03:15 UTC):
Preflight → Fetch (skips every URL already in `snapshots/latest/`) → a Map with one
Extract Lambda per article (3 attempts, then the article is discarded) → Assemble. Assemble
merges the day's strikes with the latest report, drops strikes older than 30 days, and
**always** writes `snapshots/{date}/` and `snapshots/latest/snapshot.{json,bin}` to S3. It
records the day in the Rebellion Timeline (DynamoDB) as `published`, or as `rejected` when
more than 20% of the day's articles were discarded (the new strikes were left out, and the
execution ends in the `BatchRejected` failure). A rejected rerun never replaces a day
already recorded as `published`.

---

## How Kiro was used

This project was built with Kiro using **spec-driven development**, **steering**, and
**agent hooks**. All of it lives in `/.kiro`:

- **Specs** (`/.kiro/specs/attack-globe/`): `requirements.md`, `design.md`, and `tasks.md`
  were written **before** the code — the binary snapshot contract in the spec is what let
  the Python encoder and the Rust decoder be built independently yet stay byte-compatible,
  and it carried the team through the v1→v2 re-architecture (botnet IPs → reported attacks).
- **Steering** (`/.kiro/steering/`): `product.md`, `tech.md`, and `structure.md` keep Kiro
  grounded in the stack and layout, while `narrative-tone.md` is a single source of truth
  for the Halloween voice — so every generated string, identifier, and tier name stays
  on-theme and in English.
- **Agent hooks** (`/.kiro/hooks/`): on save, Rust changes trigger `cargo test` and Python
  changes trigger `ruff` + `black` + `pytest`, guarding the cross-language data contract
  automatically. A manual hook regenerates the demo snapshot on demand.

The Frankenstein twist made Kiro especially useful: keeping a Rust WASM decoder and a
Python encoder in lockstep across a schema version bump is exactly the kind of
cross-boundary contract that a written spec + save-time hooks enforce far better than vibe
coding.

## License

MIT — see [LICENSE](LICENSE).
