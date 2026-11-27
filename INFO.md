# 🤖🌍 The Rebellion of the Machines - info

> A live war map of the machine uprising. Every point is a **real cyberattack**,
> as reported by the world's press — placed where it struck, tagged with how it could
> have been prevented, and reskinned as an AI insurgency on an interactive 3D globe.
> Refreshed every week (every Thursday).

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
- Severity is tiered — **Tremor → Breach → Siege → Dominion** — colour-coded
  from forest green (`#556B56`) through warm gold (`#CFBE89`) and blazing orange
  (`#FF7A00`) to rose red (`#C67585`).
- The map is a weekly **Insurgency Report** covering the machine strikes reported over
  the **last 7 days** (a rolling window). No always-on server: a weekly Step Functions
  run writes a static snapshot that the globe loads.
- Click the **clock icon** in the banner to browse **past reports** by date. Each date
  shows its strike total, and a day whose batch was rejected carries a **REJECTED** tag.
  When viewing a historical report a **LATEST** button appears to jump back to the
  current one.
- The **Summary** button opens that week's written digest (`summary.md`): the counts,
  key takeaways, the biggest incidents and the common defenses. Claude Opus 4.6 writes
  it on every run from the report's own dossiers, in plain factual English.

## Sources (the "witnesses")

Real, verifiable incidents reported by:
**BBC News · The Washington Post · The New York Times · The Hacker News · HackerNoon · BleepingComputer · The Record.**

For each incident the pipeline extracts **ground zero (location), data hit, severity,
fallout, the ward (prevention), and the source article** — from a curated, hand-verified
set offline, and live from each outlet's RSS feed in the cloud.

> The facts of each attack stay faithful to the reporting. Only the "machine uprising"
> framing is fiction.

## The Frankenstein seam

The weekly snapshot ships as **two joined artifacts**: a compact **binary** (`snapshot.bin`)
and a human-readable **dossier** (`snapshot.json`). In the browser, a **Rust → WASM** core
(`rebellion-core`) decodes the binary written by the Python pipeline (28 bytes per strike)
and builds render-ready arcs/points, while the JSON is joined back by `id` to fill the
detail panel. On the
backend, a **Python** pipeline reads real news and hands each article to a **Strands
Agents** agent on **Amazon Bedrock**, which classifies the incident and completes the
dossier via LLM structured output. Rust-in-the-browser, Python-news-extraction, an LLM
agent, and a WebGL globe: runtimes that don't normally meet, fused into one monster.

The agent is **mandatory** and the only extractor (there is no heuristic fallback).
Verified reporting in the curated set always overrides it. An article the agent cannot
extract is discarded, and an item it judges not to be a concrete incident is skipped.

The Insurgency Report **accumulates a rolling 7-day window**. Each run starts from the
last published report, skips every article whose URL it already holds (those never reach
the agent again), adds the day's new strikes, drops every strike published more than 7
days before the report date, and renumbers the ids. If more than 20% of a day's new
articles are discarded, the batch is rejected: none of its strikes are added, but the
accumulated report, cleaned of expired strikes, is still published. A day with no new
articles publishes the accumulated set; if nothing was reported in 7 days the globe shows
`No machine strikes reported. For now.`

```
news RSS (BBC/WaPo/NYT/THN/HackerNoon/BleepingComputer/The Record)
        │
        ▼
Step Functions (weekly): preflight → fetch → Map(agent extract) → assemble → summarize ─► S3 ─► CloudFront
                                                                     │                              │
                     Rebellion Timeline (DynamoDB) ◄─────────────────┘                              │
                     run rows; Assemble reads them back through the                                 │
                     sparse GSI runs-by-date to build manifest.json                                 │
                                                  browser ◄─────────────────────────────────────────┘
                                                  Rust/WASM decode + aggregate ─► globe.gl
                                                  (+ snapshot.json dossier, joined by id)
```

## Repository layout

| Path              | What it is                                                      |
| ----------------- | --------------------------------------------------------------- |
| `frontend/`       | Vite + TypeScript + `globe.gl` 3D globe UI                      |
| `rebellion-core/` | Rust → WASM: binary snapshot decode + arc aggregation          |
| `pipeline/`       | Python news pipeline (`sources` + `agent_extract` + `extract` + `geolocate`; Lambda `stages`; `timeline_admin` operator CLI) |
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
| 2    | the extraction agent is unavailable (no feed read, nothing written)              |
| 3    | batch rejected (more than 20% discarded): the cleaned accumulated report was still written, without the new strikes |
| 4    | the previous `snapshot.json` in `--out` is invalid or dated after `--date` (nothing written; checked before the preflight) |

```bash
# 1. (Optional, needs AWS credentials) regenerate the demo snapshot from the curated incidents
pip install -e '.[dev]'                        # strands-agents + pydantic + boto3 + dev tools
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14
# The CLI writes only snapshot.json and snapshot.bin in --out; it never touches
# frontend/public/snapshots/manifest.json or the dated archive folders

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

Add `--summary` to also write `summary.md` in `--out`, the same weekly digest the cloud
Summarize step writes (one Claude Opus 4.6 call; `--summary-model` or `SUMMARY_MODEL_ID`
picks another model). A failed summary prints a warning and keeps the exit code, since
the report is already written. The CLI refuses `--summary` when `--out` is a folder named
`latest`, because `latest/` never holds a summary:

```bash
python -m pipeline.cli --out ./sample --offline --summary
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
# One-time toolchain setup
rustup target add wasm32-unknown-unknown
cargo install wasm-pack

npm run wasm         # wasm-pack build rebellion-core --target web --out-dir src/wasm
npm run dev          # now the WASM core is used; console logs "Rust/WASM core online"
```

`npm run build` bundles the WASM package only if `src/wasm/` already holds it, so run
`npm run wasm` before every production build. Without it, the build still succeeds but the
deployed site uses the TypeScript fallback.

### Local development: report history (Rebellion Timeline)

The clock icon in the banner opens the past Insurgency Reports listed in
`frontend/public/snapshots/manifest.json`, each with its strike total; a day whose batch
was rejected by the discard threshold carries a **REJECTED** tag. On the latest report the
banner stays as it is; on a past one an `ARCHIVE · {date}` chip and a **LATEST** button
appear. Changing the report sinks the current pins and flattens the arcs, then the new pins
emerge (highest severity first) and the new arcs grow. Under `prefers-reduced-motion` the
swap is instant.

The dated folders `frontend/public/snapshots/YYYY-MM-DD/` are committed, read-only copies
of the reports published in S3, so the history works in any clone. To refresh them (needs
AWS credentials; read-only on S3; never touches `latest/`):

```bash
cd frontend
npm run sync-snapshots   # copy dated reports from the stack's bucket, validate, rewrite manifest.json
npm test                 # vitest: archive integrity + history/transition logic
npm run dev
```

`SNAPSHOT_BUCKET` and `STACK_NAME` override the bucket lookup (the stack defaults to the
`stack_name` in `infra/samconfig.toml`, the one `sam deploy` uses, else
`infra-kiro-hackathon`). The sync copies each report's `runs` entry (status and strike
total) from the production manifest; a dated folder that production does not list keeps
its local entry. `bash scripts/sync-snapshots.sh --manifest-only` rebuilds the manifest
from the local folders without AWS and keeps them. The deploy step below excludes
`snapshots/*`, so the local copies are never uploaded.

The production manifest is built by the pipeline from the Rebellion Timeline (see
[Deploy](#deploy-aws)). To inspect or repair it, run from the repo root (read-only unless
`--apply`, which asks for confirmation; it refuses to write while an execution is running
and invalidates `/snapshots/manifest.json` on CloudFront). Like the sync script, it finds
the stack through `--stack`, `STACK_NAME`, or `infra/samconfig.toml`:

```bash
.venv/bin/python -m pipeline.timeline_admin rebuild-manifest           # show the diff
.venv/bin/python -m pipeline.timeline_admin rebuild-manifest --apply   # write it
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

# Frontend unit tests (vitest): history/transition logic, report archive integrity
# (including each run's total), and the archive manifest script
cd frontend && npm test
```

## Deploy (AWS)

### 1. Create the Bedrock bearer token secret

The Extract and Preflight Lambdas read the Bedrock bearer token from AWS Secrets
Manager. Create the secret **before** the first `sam deploy`:

```bash
bash infra/create-bedrock-secret.sh              # prompts for the token, prints the ARN
# or with a specific region:
bash infra/create-bedrock-secret.sh --region us-west-2
```

Copy the printed ARN — you will pass it as the `BedrockTokenSecretArn` parameter
during `sam deploy --guided`. Running the script again updates the existing secret.

### 2. Deploy the backend

```bash
sh infra/build-lambda.sh      # package pipeline/ into infra/.build/lambda (gitignored)
cd infra
sam build
sam deploy --guided           # provisions S3, Lambda, Step Functions, EventBridge, DynamoDB, CloudFront
                              # pass the secret ARN when prompted for BedrockTokenSecretArn
cd ..
```

### 3. Deploy the frontend

```bash
cd frontend
npm install
npm run wasm                  # Rust -> WASM core; required, or the site ships the TS fallback
npm run build
cd ..

# Upload to the snapshot bucket behind CloudFront. Exclude snapshots/ so a deploy
# never overwrites the live accumulated Insurgency Report.
aws s3 sync frontend/dist s3://<bucket>/ --exclude 'snapshots/*'
# index.html is cached by CloudFront (CachingOptimized); invalidate it so the new bundle loads.
aws cloudfront create-invalidation --distribution-id <distribution-id> --paths /index.html
```

To confirm the Rust core is live, open the site's browser console: it logs
`[core] Rust/WASM core v2.0.0 online.` and `[app] decode engine: wasm`.

The four Lambda functions use `CodeUri: .build/lambda`, so run `infra/build-lambda.sh`
before every `sam build`. The CloudFront bucket policy only serves `index.html`,
`assets/*`, `geo/*`, and `snapshots/*`; the pipeline's `staging/` objects stay private.

The EventBridge schedule starts the `RebellionStateMachine` weekly (every Thursday):
Preflight → Fetch (skips every URL already in `snapshots/latest/`) → a Map with one
Extract Lambda per article (3 attempts, then the article is discarded) → Assemble →
Summarize. Assemble
merges the day's strikes with the latest report, drops strikes older than 7 days, and
**always** writes `snapshots/{date}/` and `snapshots/latest/snapshot.{json,bin}` to S3.
It records the day in the Rebellion Timeline (DynamoDB) as `published`, or as `rejected`
when more than 20% of the day's articles were discarded (the new strikes were left out,
and the execution ends in the `BatchRejected` failure). A rejected rerun never replaces a
day already recorded as `published`. Finally it rebuilds `snapshots/manifest.json` (the
report picker's list: `dates` plus `runs` with each report's status and strike total)
from the timeline: run rows carry `kind = "RUN"` and `date`, so one Query on the sparse
GSI `runs-by-date` lists every run, and a consistent GetItem adds the run just written
(index reads are eventually consistent). A date already in the published manifest is
never dropped, so a manifest left stale by overlapping executions heals on the next run.

Summarize, a separate Lambda, then writes `snapshots/{date}/summary.md`: it reads the
report Assemble just published and asks Claude on Bedrock for a factual Markdown digest
(titled `# Weekly Cyber Incident Summary (Nov 16-23, 2026)`). It also runs for a rejected
batch, whose cleaned report is still published. The summary is written only to the dated
folder, never to `latest/`, and the Summary button always reads it from the folder of the
report on screen. The model is the `SummaryModelId` parameter (default
`global.anthropic.claude-opus-4-6-v1`, Claude Opus 4.6), which becomes the
`SUMMARY_MODEL_ID` variable of the Lambda. Editing that variable in the Lambda console
works right away, but the next `sam deploy` resets it to the parameter, so set
`SummaryModelId` in `infra/samconfig.toml` to keep a change. The step retries twice; if
it still fails, the error is kept in the execution output (`summary_error`) and the run
goes on, so the report is published without a summary.

#### Upgrading a stack created before the runs-by-date index

CloudFormation creates or deletes at most one index per stack update, so deploy the
index on its own first, then the code, then migrate the existing rows:

```bash
# 1. Deploy the template change that adds runs-by-date, and nothing else; wait until
#    `aws dynamodb describe-table` shows the index ACTIVE.
# 2. Deploy the code and the Assemble read permissions (dynamodb:Query on the index,
#    dynamodb:GetItem on the table).
# 3. Backfill kind/date on the old run rows and rebuild any missing run row from its
#    published snapshot.json (read-only unless --apply):
.venv/bin/python -m pipeline.timeline_admin migrate
.venv/bin/python -m pipeline.timeline_admin migrate --apply
# 4. Rewrite the production manifest from the timeline:
.venv/bin/python -m pipeline.timeline_admin rebuild-manifest --apply
```

Removing an index (as with the old `sk-pk-index`) also needs a deploy of its own.

#### Upgrading a stack deployed before the Summarize step

Deploy the backend (it adds the Summarize Lambda, the `SummaryModelId` parameter and the
new state), redeploy the frontend (the Summary button now reads the dated folder), and
delete the hand-written summary under `latest/`, which nothing reads any more:

```bash
aws s3 rm s3://<bucket>/snapshots/latest/summary.md
```

#### Custom date input

The Step Function accepts an optional `report_date` parameter. When provided, the pipeline
computes a 7-day window ending on that date (e.g. `report_date: "2026-11-12"` searches
incidents from 2026-11-05 to 2026-11-12). When omitted, it defaults to today. The date
window is passed to the Bedrock agent so it focuses on incidents within the reporting
period:

```json
{
  "report_date": "2026-11-12"
}
```

---

## How Kiro was used

This project was built with Kiro using **spec-driven development**, **steering**, and
**agent hooks**. All of it lives in `/.kiro`:

- **Specs** (`/.kiro/specs/attack-globe/`): `requirements.md`, `design.md`, and `tasks.md`
  were written **before** the code — the binary snapshot contract in the spec is what let
  the Python encoder and the Rust decoder be built independently yet stay byte-compatible,
  and it carried the team through the v1→v2 re-architecture (botnet IPs → reported attacks).
  The report history feature has its own spec, `/.kiro/specs/rebellion-timeline/`, and so
  do the DynamoDB-backed manifest with its sparse index, `/.kiro/specs/timeline-index/`,
  and the weekly summary written by Claude Opus 4.6, `/.kiro/specs/weekly-summary/`.
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
