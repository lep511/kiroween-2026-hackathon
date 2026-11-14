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
  map is a daily **Insurgency Report**. No always-on server: a nightly Lambda writes a
  static snapshot that the globe loads.

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
backend, a **Python** pipeline reads real news and runs a deterministic **heuristic
extractor** (attack type → mitigation playbook, data/sector detection, actor attribution).
Rust-in-the-browser, Python-news-extraction, and a WebGL globe: runtimes that don't normally
meet, fused into one monster.

```
news RSS (BBC/WaPo/NYT/THN/HackerNoon)
        │
        ▼
Python Lambda (daily): fetch → extract → skin ─► snapshot.{bin,json} on S3 ─► CloudFront
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
| `pipeline/`       | Python news pipeline (`sources` + `extract` + `geolocate`)     |
| `infra/`          | AWS SAM template (Lambda, EventBridge, S3, DynamoDB, CloudFront)|
| `schema/`         | Shared snapshot contract (JSON Schema + binary layout v2)      |
| `.kiro/`          | Kiro specs, hooks, and steering (see below)                    |

## Quickstart (fully offline — no AWS, no API keys)

```bash
# 1. Generate a snapshot from the committed curated real incidents
python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline

# 2. Run the globe
cd frontend
npm install
npm run dev          # open the printed localhost URL
```

To pull **live** incidents from the news RSS feeds instead, drop `--offline`.

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
