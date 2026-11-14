# 🤖🌍 The Rebellion of the Machines

> A live war map of the machine uprising. Real public threat intelligence,
> reskinned as an AI insurgency, rendered on an interactive 3D globe and refreshed
> every day.

** — a chimera that stitches together
incompatible technologies: **Rust compiled to WebAssembly running in the browser**,
a **Python serverless data pipeline** on **AWS**, and a **WebGL globe**, all fed by
real botnet/malware feeds dressed up as machines rising against us.

![status](https://img.shields.io/badge/category-Frankenstein-ff1744)
![license](https://img.shields.io/badge/license-MIT-39ff14)

---

## What it does

- Opens on a dark, glowing 3D globe. Each **Awakened Machine** (a real malicious
  node from threat-intel feeds) is a point; **Assault Vectors** arc toward global
  command centers.
- Severity is tiered — **Flatline → Haunting → Possession → Singularity** — and the
  map is a daily **Insurgency Report** that updates on a schedule.
- Hover for a tooltip, click for a detail panel. The whole thing runs with no
  always-on server: a nightly Lambda writes a static snapshot that the globe loads.

## The Frankenstein seam

The daily snapshot ships in a compact **binary format**. In the browser, a **Rust →
WASM** core (`rebellion-core`) decodes it and aggregates thousands of events into
render-ready arcs/points — keeping the JS main thread smooth. Rust in the browser,
talking to a Python pipeline in the cloud, drawing on a WebGL globe: three runtimes
that don't normally meet, fused into one monster.

```
abuse.ch feeds ─► Python Lambda (daily) ─► snapshot.bin on S3 ─► CloudFront
                                                                     │
                                            browser ◄────────────────┘
                                            Rust/WASM decode + aggregate ─► globe.gl
```

## Repository layout

| Path              | What it is                                                      |
| ----------------- | --------------------------------------------------------------- |
| `frontend/`       | Vite + TypeScript + `globe.gl` 3D globe UI                      |
| `rebellion-core/` | Rust → WASM: binary snapshot decode + arc aggregation          |
| `pipeline/`       | Python data pipeline (AWS Lambda + offline CLI)                |
| `infra/`          | AWS SAM template (Lambda, EventBridge, S3, DynamoDB, CloudFront)|
| `schema/`         | Shared snapshot contract (JSON Schema + binary layout)         |
| `.kiro/`          | Kiro specs, hooks, and steering (see below)                    |

## Quickstart (fully offline — no AWS, no API keys)

```bash
# 1. Generate a sample Insurgency Report from committed fixtures
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline

# 2. Run the globe
cd frontend
npm install
npm run dev          # open the printed localhost URL
```

The globe renders immediately using the pure-TypeScript decoder fallback. To run
the **Rust/WASM** decoder (the real path), build the core first:

```bash
npm run wasm         # wasm-pack build rebellion-core --target web --out-dir src/wasm
npm run dev          # now the WASM core is used; console logs "Rust/WASM core online"
```

## Testing

```bash
# Python pipeline
pytest pipeline/
ruff check pipeline/ && black --check pipeline/

# Rust core (round-trips the committed binary fixture)
cd rebellion-core && cargo test

# Frontend typecheck + production build
cd frontend && npm run build
```

## Data sources

- **abuse.ch Feodo Tracker** — active botnet C2 IPs (primary).
- **abuse.ch URLhaus** — malicious URLs hosted on IPs (secondary).

Geolocation uses country centroids by default (no account needed, fully offline);
set `--mmdb path/to/GeoLite2-City.mmdb` for precise IP geolocation.

> Data is real threat intelligence. The "machine uprising" framing is fiction.

## Deploy (AWS)

```bash
cd infra
sam build
sam deploy --guided           # provisions S3, Lambda, EventBridge, DynamoDB, CloudFront
# Upload the built frontend (frontend/dist) to the snapshot bucket, behind CloudFront.
```

The EventBridge rule runs the pipeline daily (default 03:15 UTC), writing
`snapshots/latest/snapshot.{json,bin}` to S3 and a summary row to DynamoDB.

---

## How Kiro was used

This project was built with Kiro using **spec-driven development**, **steering**, and
**agent hooks**. All of it lives in `/.kiro`:

- **Specs** (`/.kiro/specs/attack-globe/`): we wrote `requirements.md` (user stories +
  acceptance criteria), `design.md` (architecture, the binary data contract, the
  narrative mapping), and `tasks.md` (an ordered, checkable build plan) **before**
  writing code. The binary snapshot contract in the spec is what let the Python
  encoder and the Rust decoder be built independently yet stay byte-compatible.
- **Steering** (`/.kiro/steering/`): `product.md`, `tech.md`, and `structure.md` keep
  Kiro grounded in the stack and layout, while `narrative-tone.md` is a single source
  of truth for the Halloween voice — so every generated string, identifier, and tier
  name stays on-theme and in English.
- **Agent hooks** (`/.kiro/hooks/`): on save, Rust changes trigger `cargo test` and
  Python changes trigger `ruff` + `black` + `pytest`, guarding the cross-language data
  contract automatically. A manual hook regenerates the demo snapshot on demand.

The Frankenstein twist made Kiro especially useful: keeping a Rust WASM decoder and a
Python encoder in lockstep is exactly the kind of cross-boundary contract that a
written spec + save-time hooks enforce far better than vibe coding.

## License

MIT — see [LICENSE](LICENSE).
