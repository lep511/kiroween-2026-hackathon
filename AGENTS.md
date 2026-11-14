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
- **Data**: real cyberattacks sourced from recognized outlets — **BBC News, The Washington Post, The New York Times, The Hacker News, HackerNoon** — painted with a machine-rebellion fiction layer (the facts stay faithful to the reporting; only the framing is fiction). Offline runs use a committed, hand-verified set of real incidents (`pipeline/fixtures/curated_incidents.json`); the cloud run reads each outlet's RSS live. **Every link must be the concrete article, never a generic/section page** — enforced by `sources.is_concrete_url` (used on both curated and live links) and guarded by `pipeline/tests/test_sources.py`. The offline set currently spans BBC, NYT, The Hacker News, and HackerNoon (all with HTTP-verified URLs); WaPo stays wired for the live feed. The Insurgency Report is a **rolling 30-day window**: each run (local CLI and cloud) starts from the previously published `snapshot.json`, skips articles whose URL it already holds (they never reach the agent again; fully curated rows are rebuilt from the curated data), adds the day's new strikes, drops every strike published more than `RECENCY_WINDOW_DAYS` (30) days before the report date, and renumbers ids `1..N` (carried strikes first, keeping their coordinates) (`pipeline/transform.py`).
- **Extraction**: a **Strands Agents** agent on **Amazon Bedrock** (`pipeline/agent_extract.py`) is **mandatory and the sole extractor**: it classifies each incident and completes the dossier via structured output. There is no heuristic fallback and no opt-in flag: without the SDK, AWS credentials, or model access nothing runs (CLI, `--offline`, or cloud), and a preflight (`ensure_agent_ready`) checks this before any feed is read. Precedence is **curated `overrides` > agent**; fully curated rows skip the agent. `country` (ground zero) is required and never a placeholder. A failing article is discarded and one the agent marks `is_incident: false` is skipped (not counted); if more than 20% of the day's new articles are discarded (`transform.DISCARD_THRESHOLD`), the batch is rejected: its new strikes are not added, but the accumulated report, cleaned of expired strikes, is still published. A day with zero new articles publishes the accumulated set (possibly empty). `geolocate.py` only maps an ISO code to coordinates. Details: `.kiro/steering/agent-enrichment.md`.
- **Platform**: AWS serverless — **Step Functions + Lambda + S3 + DynamoDB** (no SQS).
- **Update model**: a daily EventBridge schedule starts the `RebellionStateMachine` (`infra/statemachine/rebellion.asl.json`): Preflight → Fetch → a Map with one Extract Lambda per article (3 attempts, then discarded) → Assemble, which merges the day's strikes with `snapshots/latest/` and always writes a static snapshot (JSON dossier + binary) to **S3** (`snapshots/{date}/` and `snapshots/latest/`). The Rebellion Timeline records the day as `published`, or `rejected` above the discard threshold (`AcceptedChoice` → `BatchRejectedFail`, error `BatchRejected`); a rejected rerun never replaces a day already recorded as `published`. Fetch skips URLs already in `snapshots/latest/`. The Lambdas are packaged by `infra/build-lambda.sh` into `infra/.build/lambda` (`CodeUri: .build/lambda`, gitignored), which must run before `sam build`. The globe loads that snapshot. No always-on server.

**Target architecture (the Frankenstein "seams"):**
- **Frontend** — static site (S3 + CloudFront) rendering the globe with WebGL (`globe.gl`/three.js). Loads `snapshot.bin` (via WASM) and joins `snapshot.json` dossiers by `id` for the detail panel.
- **Rust → WASM (browser)** — decodes the compact binary snapshot (layout **v2**) and aggregates strikes into render buffers (points + arcs). This is the headline "incompatible technologies" seam.
- **Python (daily pipeline)** — Lambda stages in `stages.py` (`handler.py` re-exports them): `sources.py` (news RSS, `defusedxml`-hardened, `PER_FEED_LIMIT` 25 per feed, non-article and non-incident filters) → `agent_extract.py` (**Strands Agents** → **Amazon Bedrock**, mandatory) + `extract.py` (curated precedence) → `geolocate.py` (ISO code → coordinate) → `binary.py`/`transform.py` (emit snapshot).
- **Storage** — S3 for snapshots; DynamoDB for the daily "Rebellion Timeline".

Keep the language runtimes (Rust in `rebellion-core/`, Python in `pipeline/`, TypeScript in `frontend/`) separated; the only cross-boundary contract is `schema/`.

### Commands (verified)

The local env has Python via `uv` and Node; it has **no Rust toolchain**, so `cargo`/
`wasm-pack` are run elsewhere. A `.venv` (Python 3.13) holds the dev tools.

Every CLI run, including `--offline`, needs valid AWS credentials and Bedrock model
access: the agent preflight exits with code 2 otherwise. The CLI accumulates onto the
`snapshot.json` already in `--out` unless `--fresh` is given. Exit 3 means the batch was
rejected by the discard threshold (the cleaned accumulated report is still written);
exit 4 means the previous `snapshot.json` in `--out` is invalid or dated after `--date`
(nothing written; checked before the preflight). The tests need neither (stub agent, stub boto3).

```bash
# Python pipeline (run from repo root)
.venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14
.venv/bin/python -m pipeline.cli --out ./sample --per-feed-limit 25   # live RSS
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
`.venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14`
then copy the two files to `schema/fixtures/` and the `.bin` to `rebellion-core/tests/fixtures/`.
That command needs valid AWS credentials (preflight). Without them, the equivalent check is
`outcome = transform.run(offline=True, report_date=date(2026, 11, 14), ready_check=<stub>, extractor=<stub>, previous=None)`
plus `transform.write_artifacts(outcome.report, ...)`: all curated rows are fully pinned, so the agent is never
called and the output matches the committed fixtures except `generated_at`
(`test_offline_run_reproduces_the_committed_snapshot` asserts this). At the pinned date
2026-11-14 the 30-day window leaves 5 strikes: the BBC French-supermarket fridges row
(published 2026-10-12) and SolarWinds fall outside it.

## Judging priorities

Judging weights five equal criteria: Potential Impact, Technological Implementation (depth and variety of Kiro feature use), Design, Innovation/Idea, and Presentation. "Technological Implementation" specifically rewards visible, varied use of Kiro features (custom agents, agent hooks, spec-driven development, steering docs, MCP, property-based testing, Kiro powers) — favor an approach that exercises several of these and leaves a documented trail in `/.kiro`.

## Working-directory note

This directory is a git repository (branch `main`). The public GitHub remote and final submission wiring are still to be set up.

## Language Policy

All project-related artifacts must be written exclusively in English, including source code, variable and function names, comments, docstrings, documentation, reports, technical analysis, test descriptions, commit messages, logs, error messages, and configuration files. However, conversational interactions with the developer must remain in the language used by the developer. The language of the conversation must not affect the language of generated or modified project files, which must always be in English. This is a mandatory project-wide requirement.
