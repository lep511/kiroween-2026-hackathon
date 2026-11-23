---
inclusion: always
---

# Tech stack and commands

## Stack

- **Frontend**: static site (S3 + CloudFront), WebGL via `globe.gl`/three.js, TypeScript.
  Loads `snapshot.bin` through WASM and joins `snapshot.json` dossiers by `id`.
- **Rust → WASM** (`rebellion-core/`): decodes the binary snapshot (layout v2) and
  aggregates strikes into render buffers (points + arcs).
- **Python 3.13** (`pipeline/`): Lambda stages in `stages.py` (`handler.py` re-exports):
  `sources.py` (RSS, `defusedxml`, `PER_FEED_LIMIT` 25) → `agent_extract.py` + `extract.py`
  → `geolocate.py` (ISO code → coordinate only) → `binary.py`/`transform.py`.
- **Extraction**: Strands Agents on Amazon Bedrock is mandatory and the sole extractor.
  No heuristic fallback. Precedence: curated `overrides` > agent. Fully curated rows
  skip the agent. `country` is required, never a placeholder. Details:
  `agent-enrichment.md`.
- **Platform**: Step Functions + Lambda + S3 + DynamoDB (no SQS). A weekly EventBridge
  Scheduler schedule (every Thursday) starts `RebellionStateMachine` (`infra/statemachine/rebellion.asl.json`):
  Preflight → Fetch → Map(Extract, 3 attempts then discard) → Assemble → Summarize.
  Snapshots go to `snapshots/{date}/` and `snapshots/latest/`. Summarize writes
  `snapshots/{date}/summary.md` (never under `latest/`) with Claude Opus 4.6
  (`SUMMARY_MODEL_ID`, SAM `SummaryModelId`); a failed summary never blocks the run.
  The Rebellion Timeline
  (DynamoDB) records `published` or `rejected` (discard > 20%, `DISCARD_THRESHOLD`);
  a rejected rerun never replaces a day already `published`. Run rows carry
  `kind = "RUN"` and `date`, so the sparse GSI `runs-by-date` (the table's only index)
  lists them; Assemble rebuilds `snapshots/manifest.json` (`dates` plus `runs` with each
  report's status and strike total) from one Query on it plus a consistent GetItem of the
  run just written, and never drops a date already listed.
- Lambdas are packaged by `infra/build-lambda.sh` into `infra/.build/lambda`
  (gitignored); run it before `sam build`. Change table indexes in a deploy of their own:
  CloudFormation creates or deletes at most one index per stack update.

## Commands

Check the Rust toolchain first: `command -v cargo wasm-pack rustc`. If missing, do not
install it unless asked.

Every CLI run (including `--offline`) needs valid AWS credentials and Bedrock access
(preflight exits 2). Exit 3 = batch rejected by the discard threshold (cleaned report
still written). Exit 4 = previous `snapshot.json` invalid or dated after `--date`.
Tests need neither (stub agent, stub boto3).

    # Python pipeline (repo root)
    .venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14
    .venv/bin/python -m pipeline.cli --out ./sample --per-feed-limit 25
    .venv/bin/python -m pytest pipeline/tests -q
    .venv/bin/ruff check pipeline/ && .venv/bin/black --check pipeline/

    # Rust core
    cd rebellion-core && cargo test && cargo fmt --check && cargo clippy --all-targets
    cd frontend && npm run wasm

    # Frontend
    cd frontend && npm install && npm run dev
    cd frontend && npm test                        # vitest: history/transition logic + archive integrity
    cd frontend && npm run wasm && npm run build   # run wasm FIRST, or only the TS fallback decoder ships

    # Report archive (Rebellion Timeline), see structure.md
    cd frontend && npm run sync-snapshots          # needs AWS credentials; read-only on S3; copies runs
    bash frontend/scripts/sync-snapshots.sh --manifest-only   # no AWS: validate folders, rewrite manifest.json (keeps runs)

    # Timeline operations (repo root, AWS credentials; read-only unless --apply)
    .venv/bin/python -m pipeline.timeline_admin rebuild-manifest   # production manifest from DynamoDB (diff)
    .venv/bin/python -m pipeline.timeline_admin migrate            # add kind/date to old run rows, rebuild missing ones