# Steering — Tech

> This file tells Kiro **how** we build: the stack, conventions, and commands.

## Stack

| Layer            | Technology                                              |
| ---------------- | ------------------------------------------------------- |
| 3D globe UI      | Vite + TypeScript + `globe.gl` (three.js / WebGL)       |
| In-browser core  | **Rust → WASM** (`wasm-bindgen` + `wasm-pack`)          |
| Data pipeline    | **Python 3.12** AWS Lambda (daily)                      |
| Scheduling       | Amazon EventBridge (daily cron)                         |
| Storage          | Amazon S3 (snapshots + static site), DynamoDB (history) |
| CDN              | Amazon CloudFront                                        |
| Infra as code    | AWS SAM (`infra/template.yaml`)                          |

## The Frankenstein seam

Rust compiled to WebAssembly runs **in the browser** to decode the daily binary snapshot
and aggregate thousands of events into renderable arcs/points, keeping the JS main thread
smooth. This Rust↔JS↔Python↔serverless fusion is the intentional "incompatible tech" story.

## Conventions

- **Language:** every file, comment, identifier, doc, and UI string is in **English**.
- **Data contract:** the pipeline and the Rust core share one schema in `schema/`.
  The JSON snapshot is human-readable; the `.bin` snapshot is what the WASM core decodes.
- **Offline-first dev:** the pipeline runs locally (CLI) and produces sample snapshots so
  the frontend and Rust core can be developed without any AWS account.
- **Testing:** `pytest` for the pipeline, `cargo test` for the Rust core.
- **Formatting/lint:** `ruff` + `black` (Python), `cargo fmt` + `clippy` (Rust),
  `prettier` (frontend).

## Common commands (fill in as modules land)

```bash
# Pipeline (local)
python -m pipeline.cli --out ./sample           # produce sample snapshot.json + .bin
pytest pipeline/

# Rust core
cd rebellion-core && cargo test
wasm-pack build rebellion-core --target web --out-dir ../frontend/src/wasm

# Frontend
cd frontend && npm install && npm run dev

# Infra
sam build && sam deploy --guided
```
