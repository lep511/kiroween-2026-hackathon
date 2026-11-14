# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is the working directory for a **Kiroween 2026 hackathon submission** (deadline: **Friday, December 4, 2026, 2:00 PM Pacific**). No application code exists yet — the repo currently holds only reference material:

- `OVERVIEW.md` — the hackathon overview (categories, bonus prizes, judging criteria).
- `RULES.md` — the full Official Rules. This is the binding source of truth; when `OVERVIEW.md` and `RULES.md` disagree, `RULES.md` controls.
- `skills-lock.json` — pins the `hackathon-guide` skill (from `challengepost/devpost-curriculum`) used to assist with the submission.

Because the project is unstarted, there are no build, lint, or test commands yet. When the application is scaffolded, add those commands and the architecture notes to this file.

## Hard submission constraints (treat as non-negotiable)

These rules can cause **disqualification**, so respect them in every decision about tooling and structure:

- **The project must be built with Kiro** (IDE, CLI, Web, and/or Kiro Crew). Insufficient Kiro usage is grounds for disqualification.
- **The repo must contain a `/.kiro` directory at the root** showing specs, hooks, and steering. **Never add `/.kiro` or its subfolders to `.gitignore`.**
- **New work only**: everything must be created during the Submission Period (Oct 30 – Dec 4, 2026). Pre-existing code must be disclosed.
- The final submission must be a **public GitHub repo** (not GitLab/BitBucket) with an **open-source license file** detectable at the top of the repo.
- **Skeleton Crew category only**: the repo must contain **two separate folders for two distinct applications**.
- All submission materials must be in **English**.

## Category choice

**This submission targets the Frankenstein category**: stitch together a chimera of technologies into one app — bring together seemingly incompatible elements to build something unexpectedly powerful. Architecture and tooling decisions should lean into combining distinct/unlikely technologies, since that is what this category rewards.

## The project: "The Rebellion of the Machines"

A web app that opens on an interactive **3D globe** and shows cyberattacks / system hacks lighting up at points around the world, **updated daily**, all reskinned with a "machines rising up / AI uprising" narrative.

**Confirmed decisions:**
- **Data**: real public cyber-threat feeds painted with a machine-rebellion fiction layer (real impact + Halloween theme).
- **Platform**: AWS serverless — **Lambda + S3 + DynamoDB**.
- **Update model**: a daily scheduled Lambda (EventBridge cron) processes the feeds and writes a static snapshot (JSON/binary) to **S3**; the globe loads that snapshot. No always-on server.

**Target architecture (the Frankenstein "seams"):**
- **Frontend** — static site (S3 + CloudFront) rendering the globe with WebGL (e.g. three.js / globe.gl). Loads the daily snapshot from S3.
- **Rust → WASM (browser)** — heavy client-side work: aggregating/clustering attack arcs, geo math, and/or decoding a compact binary snapshot into render buffers. This is the headline "incompatible technologies" seam.
- **Python (daily pipeline)** — the scheduled Lambda: pull threat feeds, geolocate IPs, apply the narrative layer, emit the snapshot.
- **Rust Lambda (optional)** — fast parsing/aggregation of raw feeds if Python becomes the bottleneck.
- **Storage** — S3 for snapshots; DynamoDB for historical daily data / a timeline of the "rebellion".

When scaffolding, keep the two language runtimes (Rust and Python) and the serverless glue clearly separated, and record build/deploy commands here as they are created. Remember the hard constraints above — especially the `/.kiro` directory and building with Kiro.

### Commands (verified)

The local env has Python via `uv` and Node; it has **no Rust toolchain**, so `cargo`/
`wasm-pack` are run elsewhere. A `.venv` (Python 3.13) holds the dev tools.

```bash
# Python pipeline (run from repo root)
.venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline
.venv/bin/python -m pytest pipeline/tests -q
.venv/bin/ruff check pipeline/ && .venv/bin/black --check pipeline/

# Rust core (where a toolchain exists)
cd rebellion-core && cargo test
cd frontend && npm run wasm            # wasm-pack build into src/wasm

# Frontend
cd frontend && npm install && npm run dev      # dev server
cd frontend && npm run build                   # tsc + vite build -> dist/
```

**Data contract invariant:** `pipeline/binary.py`, `rebellion-core/src/decode.rs`, and
`frontend/src/snapshot.ts` all implement `schema/binary-layout.md`. Change all three
(and regenerate the committed fixtures under `schema/fixtures/`,
`rebellion-core/tests/fixtures/`, `frontend/public/snapshots/latest/`) together.

## Judging priorities

Judging weights five equal criteria: Potential Impact, Technological Implementation (depth and variety of Kiro feature use), Design, Innovation/Idea, and Presentation. "Technological Implementation" specifically rewards visible, varied use of Kiro features (custom agents, agent hooks, spec-driven development, steering docs, MCP, property-based testing, Kiro powers) — favor an approach that exercises several of these and leaves a documented trail in `/.kiro`.

## Working-directory note

This directory is not yet a git repository. Initialize git (and the eventual GitHub remote) as part of setting up the project.
