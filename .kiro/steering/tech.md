# Steering — Tech

> This file tells Kiro **how** we build: the stack, conventions, and commands.

## Stack

| Layer            | Technology                                                   |
| ---------------- | ------------------------------------------------------------ |
| 3D globe UI      | Vite + TypeScript + `globe.gl` (three.js / WebGL)            |
| In-browser core  | **Rust → WASM** (`wasm-bindgen` + `wasm-pack`)               |
| Data pipeline    | **Python 3.12** AWS Lambda (daily): news RSS → extraction    |
| AI enrichment    | **Strands Agents** → Amazon Bedrock (optional, opt-in)       |
| XML parsing      | `defusedxml` (hardened parsing of untrusted RSS)             |
| Scheduling       | Amazon EventBridge (daily cron)                              |
| Storage          | Amazon S3 (snapshots + static site), DynamoDB (history)      |
| CDN              | Amazon CloudFront                                            |
| Infra as code    | AWS SAM (`infra/template.yaml`)                              |

## The Frankenstein seam

Rust compiled to WebAssembly runs **in the browser** to decode the daily binary snapshot
and build renderable arcs/points, keeping the JS main thread smooth. On the backend, a
Python pipeline pulls **real journalism** from six news outlets and runs a deterministic
**heuristic extractor** (attack type → mitigation playbook, data/sector detection, actor
attribution) to turn free-text headlines into a structured dossier. Rust-in-the-browser +
Python-news-extraction + a WebGL globe is the intentional "incompatible tech" story.

An **optional** fourth seam deepens the chimera: a **Strands Agents** agent backed by
**Amazon Bedrock** (`pipeline/agent_extract.py`) can classify each incident and complete
the dossier via LLM structured output. It runs on **Claude Opus 4.8** by default (the
`DEFAULT_MODEL_ID` constant, overridable via `--agent-model` / `AGENT_MODEL_ID`). It is
strictly opt-in (`--use-agent` / `USE_AGENT=1`); curated reporting always overrides it, and
any failure (no SDK, no credentials, a model error) degrades transparently to the
deterministic heuristic — so the default pipeline, the offline snapshot, and the whole test
suite stay reproducible and dependency-free.

## Data flow

1. `sources.py` — fetch RSS from BBC, WaPo, NYT, The Hacker News, HackerNoon
   (offline mode reads committed, hand-verified real incidents in `fixtures/`).
2. `extract.py` — deterministic heuristics derive attack type, data hit, fallout,
   severity, the ward, and attributed origin. Curated `overrides` always win.
   `agent_extract.py` — optional Strands/Bedrock enrichment fills any field a curated
   incident left blank (precedence: curated overrides > agent > heuristic).
3. `geolocate.py` — resolve country name/demonym → ISO code → representative coordinate.
4. `binary.py` / `transform.py` — emit `snapshot.json` (dossier) + `snapshot.bin` (render).

## Conventions

- **Language:** every file, comment, identifier, doc, and UI string is in **English**.
- **Data contract:** the pipeline and the Rust core share one schema in `schema/`
  (binary layout **v2**). The `.bin` carries only numeric/positional fields plus an `id`;
  the rich dossier lives in `snapshot.json` and is joined back by `id`.
- **Offline-first dev:** the pipeline runs locally from curated incidents and produces a
  reproducible snapshot, so the frontend and Rust core need no AWS account or network.
- **Testing:** `pytest` (incl. a `hypothesis` property-based binary round-trip) for the
  pipeline; `cargo test` for the Rust core.
- **Formatting/lint:** `ruff` + `black` (Python), `cargo fmt` + `clippy` (Rust),
  `prettier` (frontend).

## Common commands

```bash
# Pipeline (local)
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline  # curated real incidents
python -m pipeline.cli --out ./sample                                      # live news RSS
python -m pipeline.cli --out ./sample --use-agent                          # + Strands/Bedrock enrichment (needs AWS creds)
pytest pipeline/

# Rust core
cd rebellion-core && cargo test
wasm-pack build rebellion-core --target web --out-dir ../frontend/src/wasm

# Frontend
cd frontend && npm install && npm run dev

# Infra
sam build && sam deploy --guided
```
