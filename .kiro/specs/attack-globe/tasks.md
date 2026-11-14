# Spec — Attack Globe · Tasks

Ordered, checkable implementation tasks. Each should leave the repo runnable.

## 0. Foundation
- [x] `git init`, `.gitignore` (never excluding `.kiro`), MIT `LICENSE`, `README` skeleton
- [x] Steering docs (`product`, `tech`, `structure`, `narrative-tone`)
- [x] This spec (`requirements`, `design`, `tasks`)

## 1. Shared contract (`schema/`)
- [x] `schema/snapshot.schema.json` — JSON Schema for `snapshot.json`
- [x] `schema/binary-layout.md` — documented little-endian `.bin` layout
- [x] A tiny committed fixture snapshot for offline dev/tests

## 2. Python pipeline (`pipeline/`)
- [x] `models.py` — internal record + severity/source enums + narrative mapping
- [x] `feeds.py` — fetch & normalize abuse.ch Feodo (primary) + URLhaus (secondary)
- [x] `geolocate.py` — GeoLite2 lookup with offline fixture fallback
- [x] `transform.py` — feeds → internal records → JSON + binary snapshot (shared core)
- [x] `cli.py` — `python -m pipeline.cli --out ./sample` runs fully offline
- [x] `handler.py` — AWS Lambda entry: run transform, write to S3, summary row to DynamoDB
- [x] `tests/` — `pytest` for transform + binary encoder (round-trips with Rust layout)

## 3. Rust/WASM core (`rebellion-core/`)
- [x] `Cargo.toml` with `wasm-bindgen`, `serde`
- [x] `decode.rs` — parse header + records, validate magic/version
- [x] `aggregate.rs` — dedupe, build arcs, severity buckets, LOD cap
- [x] `lib.rs` — `wasm-bindgen` API (`build_render_batch`, `machine_count`, `core_version`)
- [x] `tests/decode_test.rs` round-trips the committed fixture (written; run `cargo test`
      where a Rust toolchain exists — not available in the current build env)
- [ ] `wasm-pack build` into `frontend/src/wasm` (TS fallback covers it meanwhile)

## 4. Frontend (`frontend/`)
- [x] Vite + TypeScript scaffold, `globe.gl` dependency
- [x] WASM integration: load core, decode + aggregate the snapshot
- [x] Globe render: points + assault-vector arcs colored by severity
- [x] Halloween skin: dark globe, glow, pulse, scanline/glitch, reduced-motion guard
- [x] Insurgency Report banner, tooltip, detail panel
- [x] Themed loader (`INITIALIZING THE UPRISING…`)
- [ ] Timeline scrubber (stretch)

## 5. Infra (`infra/`)
- [x] `template.yaml` — S3, Python Lambda, EventBridge daily rule, DynamoDB, CloudFront
- [ ] `sam build && sam deploy --guided`; verify daily job writes a fresh snapshot

## Verified in this build env
- Python: `pytest` 10/10 green, `ruff` clean, `black` clean (Python 3.13).
- Pipeline CLI produces a deterministic 472-byte snapshot (16 + 24×19).
- Frontend: `tsc` typecheck clean, `vite build` succeeds, preview serves the app
  and the snapshot (HTTP 200). Rust/WASM path pending `cargo`/`wasm-pack` (absent here).

## 6. Polish & submission
- [ ] README "how Kiro was used" write-up (specs, hooks, steering, MCP if used)
- [ ] Demo snapshot + 3-min video script
- [ ] Final checklist: `.kiro` present & not ignored, LICENSE detectable, repo public, English
