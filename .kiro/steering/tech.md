# Steering — Tech

> This file tells Kiro **how** we build: the stack, conventions, and commands.

## Stack

| Layer            | Technology                                                   |
| ---------------- | ------------------------------------------------------------ |
| 3D globe UI      | Vite + TypeScript + `globe.gl` (three.js / WebGL)            |
| In-browser core  | **Rust → WASM** (`wasm-bindgen` + `wasm-pack`)               |
| Data pipeline    | **Python 3.12** AWS Lambda (daily): news RSS → extraction    |
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

## Data flow

1. `sources.py` — fetch RSS from BBC, WaPo, NYT, CNN, The Hacker News, HackerNoon
   (offline mode reads committed, hand-verified real incidents in `fixtures/`).
2. `extract.py` — deterministic heuristics derive attack type, data hit, fallout,
   severity, the ward, and attributed origin. Curated `overrides` always win.
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
pytest pipeline/

# Rust core
cd rebellion-core && cargo test
wasm-pack build rebellion-core --target web --out-dir ../frontend/src/wasm

# Frontend
cd frontend && npm install && npm run dev

# Infra
sam build && sam deploy --guided
```
