# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is the working directory for a **Kiroween 2026 hackathon submission** (deadline: **Friday, December 4, 2026, 2:00 PM Pacific**). The application ("The Rebellion of the Machines") is scaffolded and runnable; see the sections below for architecture and commands. Reference material also lives at the repo root:

- `OVERVIEW.md` — the hackathon overview (categories, bonus prizes, judging criteria).
- `RULES.md` — the full Official Rules. This is the binding source of truth; when `OVERVIEW.md` and `RULES.md` disagree, `RULES.md` controls.
- `skills-lock.json` — pins the `hackathon-guide` skill (from `challengepost/devpost-curriculum`) used to assist with the submission.

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

A web app that opens on an interactive **3D globe** where each point is a **real cyberattack reported by a recognized news outlet**, placed where it struck, **updated daily**, all reskinned with a "machines rising up / AI uprising" narrative. Every incident carries an extracted dossier: **ground zero (location), data hit, severity, fallout, how it could have been prevented ("the ward"), and a link to the article.**

**Confirmed decisions:**
- **Data**: real cyberattacks sourced from recognized outlets — **BBC News, The Washington Post, The New York Times, The Hacker News, HackerNoon** — painted with a machine-rebellion fiction layer (the facts stay faithful to the reporting; only the framing is fiction). Offline runs use a committed, hand-verified set of real incidents (`pipeline/fixtures/curated_incidents.json`); the cloud run reads each outlet's RSS live. **Every link must be the concrete article, never a generic/section page** — enforced by `sources.is_concrete_url` (used on both curated and live links) and guarded by `pipeline/tests/test_sources.py`. The offline set currently spans BBC, NYT, The Hacker News, and HackerNoon (all with HTTP-verified URLs); WaPo stays wired for the live feed. Only **recent** incidents ship: a daily report drops anything older than `RECENCY_WINDOW_DAYS` (90) relative to its date (`pipeline/transform.py`).
- **Extraction**: a **deterministic heuristic extractor** (`pipeline/extract.py`) maps attack type → mitigation playbook, detects affected data/sectors, derives severity, and attributes an attacker origin — reproducible and test-stable, the default everywhere (offline, tests, fixtures). An **optional** LLM path (`pipeline/agent_extract.py`) uses a **Strands Agents** agent on **Amazon Bedrock** to classify each incident and complete the dossier via structured output; it is strictly opt-in (`--use-agent` / `USE_AGENT=1`), degrades to the heuristic on any failure, and keeps the default pipeline dependency-free. Precedence is **curated `overrides` > agent > heuristic** — verified reporting always wins.
- **Platform**: AWS serverless — **Lambda + S3 + DynamoDB**.
- **Update model**: a daily scheduled Lambda (EventBridge cron) builds the report and writes a static snapshot (JSON dossier + binary) to **S3**; the globe loads that snapshot. No always-on server.

**Target architecture (the Frankenstein "seams"):**
- **Frontend** — static site (S3 + CloudFront) rendering the globe with WebGL (`globe.gl`/three.js). Loads `snapshot.bin` (via WASM) and joins `snapshot.json` dossiers by `id` for the detail panel.
- **Rust → WASM (browser)** — decodes the compact binary snapshot (layout **v2**) and aggregates strikes into render buffers (points + arcs). This is the headline "incompatible technologies" seam.
- **Python (daily pipeline)** — the scheduled Lambda: `sources.py` (news RSS, `defusedxml`-hardened) → `extract.py` (dossier extraction) → `geolocate.py` (place → coordinate) → `binary.py`/`transform.py` (emit snapshot). An optional AI seam, `agent_extract.py` (**Strands Agents** → **Amazon Bedrock**, opt-in), enriches dossiers via LLM structured output.
- **Storage** — S3 for snapshots; DynamoDB for the daily "Rebellion Timeline".

Keep the language runtimes (Rust in `rebellion-core/`, Python in `pipeline/`, TypeScript in `frontend/`) separated; the only cross-boundary contract is `schema/`.

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
`frontend/src/snapshot.ts` all implement `schema/binary-layout.md` (currently **v2**).
Change all three (and regenerate the committed fixtures under `schema/fixtures/`,
`rebellion-core/tests/fixtures/`, `frontend/public/snapshots/latest/`) together. The
binary carries only numeric/positional fields plus an `id`; the rich per-strike dossier
lives in `snapshot.json` (`schema/snapshot.schema.json`) and is loaded by
`frontend/src/snapshot-detail.ts` and joined to each point by `id`. The `witness` enum
(news outlets, 0–5) is mirrored in `pipeline/models.py`, `decode.rs`, and
`frontend/src/theme.ts` — keep those in sync too. Regenerate fixtures with:
`.venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --date 2026-11-14`
then copy the two files to `schema/fixtures/` and the `.bin` to `rebellion-core/tests/fixtures/`.

## Judging priorities

Judging weights five equal criteria: Potential Impact, Technological Implementation (depth and variety of Kiro feature use), Design, Innovation/Idea, and Presentation. "Technological Implementation" specifically rewards visible, varied use of Kiro features (custom agents, agent hooks, spec-driven development, steering docs, MCP, property-based testing, Kiro powers) — favor an approach that exercises several of these and leaves a documented trail in `/.kiro`.

## Working-directory note

This directory is a git repository (branch `main`). The public GitHub remote and final submission wiring are still to be set up.
