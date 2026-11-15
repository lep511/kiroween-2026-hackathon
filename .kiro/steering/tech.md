# Steering — Tech

> This file tells Kiro **how** we build: the stack, conventions, and commands.

## Stack

| Layer            | Technology                                                   |
| ---------------- | ------------------------------------------------------------ |
| 3D globe UI      | Vite + TypeScript + `globe.gl` (three.js / WebGL)            |
| In-browser core  | **Rust → WASM** (`wasm-bindgen` + `wasm-pack`)               |
| Data pipeline    | **Python 3.13** AWS Lambda stages: news RSS → extraction     |
| AI extraction    | **Strands Agents** → Amazon Bedrock (mandatory, sole extractor) |
| Orchestration    | AWS Step Functions (Map per article, retry, discard)         |
| XML parsing      | `defusedxml` (hardened parsing of untrusted RSS)             |
| Scheduling       | Amazon EventBridge (daily cron → state machine)              |
| Storage          | Amazon S3 (snapshots + static site), DynamoDB (history)      |
| CDN              | Amazon CloudFront                                            |
| Infra as code    | AWS SAM (`infra/template.yaml`)                              |

## The Frankenstein seam

Rust compiled to WebAssembly runs **in the browser** to decode the daily binary snapshot
and build renderable arcs/points. It runs on the main thread: with tens of strikes in the
30-day window the decode cost is negligible, and moving it to a Web Worker only pays off if
the report grows to thousands of strikes. On the backend, a
Python pipeline pulls **real journalism** from the news outlets and turns free-text
headlines into a structured dossier. Rust-in-the-browser + Python-news-extraction + a WebGL
globe is the intentional "incompatible tech" story.

A fourth seam deepens the chimera: a **Strands Agents** agent backed by **Amazon Bedrock**
(`pipeline/agent_extract.py`) classifies each incident and completes the dossier via LLM
structured output. It is **mandatory and the sole extractor**: there is no heuristic
fallback, and without the SDK, AWS credentials, or model access nothing runs (CLI,
`--offline`, or cloud). It runs on **Claude Opus 4.8** by default (the `DEFAULT_MODEL_ID`
constant, overridable via `--agent-model` / `AGENT_MODEL_ID`). Curated reporting always
overrides it. In the cloud, **AWS Step Functions** fans out one Extract Lambda per article
with retries and discards; see `steering/agent-enrichment.md`.

## Data flow

0. Preflight — `agent_extract.ensure_agent_ready()` verifies the SDK, credentials, and
   model access before any feed is read (CLI exit 2 on failure).
1. `sources.py` — fetch RSS from BBC, WaPo, NYT, The Hacker News, HackerNoon, at most
   `PER_FEED_LIMIT` (25) articles per feed; drop non-article URLs (`is_concrete_url`) and
   non-incident items (`is_reportable_incident`, live RSS only). Offline mode reads
   committed, hand-verified real incidents in `fixtures/`.
2. `agent_extract.py` + `extract.py` — the agent extracts attack type, data hit, fallout,
   severity, the ward, ground-zero country, and attributed origin. Precedence: curated
   overrides > agent. Articles whose URL is already in the previous report are dropped
   before extraction (`transform.drop_known`), so they never reach the agent. A failing
   article is discarded and a non-incident (`is_incident: false`) is skipped; if more than
   20% are discarded, the day's new strikes are not added (the batch is rejected).
3. `geolocate.py` — ISO code → representative coordinate (centroid + jitter) only.
4. `binary.py` / `transform.py` — merge the previous report's strikes with the new ones,
   drop strikes older than 30 days (`RECENCY_WINDOW_DAYS`), renumber ids `1..N`, and emit
   `snapshot.json` (dossier) + `snapshot.bin` (render). The report is a **rolling 30-day
   window** and is always published, even on a day with no new articles or a rejected
   batch. In the cloud, `stages.py` runs these steps as Step Functions states.

## Conventions

- **Language:** every file, comment, identifier, doc, and UI string is in **English**.
- **Data contract:** the pipeline and the Rust core share one schema in `schema/`
  (binary layout **v2**). The `.bin` carries only numeric/positional fields plus an `id`;
  the rich dossier lives in `snapshot.json` and is joined back by `id`.
- **Offline-first dev:** the committed snapshot lets the frontend and Rust core run with
  no AWS account or network. Regenerating it (`--offline --fresh`) runs the agent
  preflight, so it needs AWS credentials, but fully curated rows never call the model and
  stay reproducible. Without `--fresh` the CLI accumulates onto the `snapshot.json`
  already in `--out`. Tests use stub agents and stub boto3 clients only.
- **Testing:** `pytest` (incl. a `hypothesis` property-based binary round-trip) for the
  pipeline; `cargo test` for the Rust core.
- **Formatting/lint:** `ruff` + `black` (Python), `cargo fmt` + `clippy` (Rust),
  `prettier` (frontend).

## Common commands

```bash
# Pipeline (local)
# Every run needs AWS credentials + Bedrock model access (the agent is mandatory)
# Runs accumulate onto --out/snapshot.json; --fresh ignores it (exit 3 = batch rejected, 4 = invalid or newer previous snapshot)
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14  # regenerate the demo fixtures
python -m pipeline.cli --out ./sample                                      # live news RSS
python -m pipeline.cli --out ./sample --per-feed-limit 10                  # cap articles per feed (default 25)
pytest pipeline/                                                           # no AWS needed (stubs)

# Rust core (one-time setup: rustup target add wasm32-unknown-unknown; cargo install wasm-pack)
cd rebellion-core && cargo test && cargo fmt --check && cargo clippy --all-targets
wasm-pack build rebellion-core --target web --out-dir ../frontend/src/wasm

# Frontend
cd frontend && npm install && npm run dev
cd frontend && npm run wasm && npm run build   # production: build the WASM core FIRST

# Infra (package the Lambdas into infra/.build/lambda first)
sh infra/build-lambda.sh
sam build && sam deploy --guided   # 4 Lambda stages + Step Functions state machine
aws s3 sync frontend/dist s3://<bucket>/ --exclude 'snapshots/*'
aws cloudfront create-invalidation --distribution-id <id> --paths /index.html
```

`frontend/src/wasm-loader.ts` finds the WASM package through `import.meta.glob`, which
Vite resolves at build time. A `npm run build` without a prior `npm run wasm` succeeds but
ships only the TypeScript fallback decoder. On the live site, the browser console logs
`[app] decode engine: wasm` when the Rust core is in use.
