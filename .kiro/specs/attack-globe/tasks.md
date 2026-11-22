# Spec — Attack Globe · Tasks

Ordered, checkable implementation tasks. Each should leave the repo runnable.

## 0. Foundation
- [x] `git init`, `.gitignore` (never excluding `.kiro`), MIT `LICENSE`, `README` skeleton
- [x] Steering docs (`product`, `tech`, `structure`, `narrative-tone`, `agent-enrichment`)
- [x] This spec (`requirements`, `design`, `tasks`)

## 1. Shared contract (`schema/`) — binary layout v2
- [x] `schema/snapshot.schema.json` — JSON Schema for `snapshot.json` (strike dossier)
- [x] `schema/binary-layout.md` — documented little-endian `.bin` layout (28-byte record)
- [x] A committed fixture snapshot generated from the curated incidents (offline)

## 2. Python pipeline (`pipeline/`) — news incidents
- [x] `models.py` — `Strike` record + `Severity`/`Witness` enums + narrative mapping
- [x] `sources.py` — fetch & normalize RSS from BBC, WaPo, NYT, The Hacker News,
      HackerNoon; cyber-incident filter; offline curated loader (`defusedxml`-hardened)
- [x] ~~`extract.py` — deterministic dossier extraction (attack type → ward, data/sector,
      severity, origin attribution); curated `overrides` win~~ (superseded by section 7:
      no heuristic extraction)
- [x] ~~`agent_extract.py` — optional, opt-in Strands/Bedrock enrichment with heuristic
      fallback~~ (superseded by section 7: the agent is mandatory and the sole extractor)
- [x] Document the AI seam: steering `agent-enrichment.md` (single source of truth),
      plus `tech.md`, `design.md`, AGENTS.md, and README. Live Bedrock run verified
      (Opus 4.8, us-east-1)
- [x] ~~`geolocate.py` — country name/demonym → ISO → centroid with deterministic jitter~~
      (superseded by section 7: ISO code → centroid + jitter only)
- [x] `fixtures/curated_incidents.json` — hand-verified real incidents, each with a
      concrete, HTTP-verified article link (BBC, NYT, The Hacker News, HackerNoon;
      WaPo is wired for the live feed). Links are never generic/section pages.
- [x] `transform.py` — articles → strikes → JSON + binary (shared core)
- [x] `cli.py` — `python -m pipeline.cli --out … --offline` runs fully offline
- [x] ~~`handler.py` — single AWS Lambda entry~~ (superseded by section 7: `stages.py`
      Lambda stages under Step Functions; `handler.py` is a re-export alias)
- [x] `tests/` — `pytest` for extraction + transform + binary; a `hypothesis` property-based
      binary round-trip

## 3. Rust/WASM core (`rebellion-core/`) — v2
- [x] `decode.rs` — parse header + 28-byte records, validate magic/version=2
- [x] `aggregate.rs` — one point per strike (carries `id`), arcs origin→ground zero, LOD cap
- [x] `lib.rs` — `wasm-bindgen` API (`build_render_batch`, `strike_count`, `core_version`)
- [x] `tests/decode_test.rs` round-trips the committed fixture (`cargo test`: 8 passed;
      `cargo fmt --check` and `cargo clippy --all-targets` clean)
- [x] `wasm-pack build` into `frontend/src/wasm` (`npm run wasm`; the generated files are
      gitignored by wasm-pack's own `.gitignore`)

## 4. Frontend (`frontend/`)
- [x] Vite + TypeScript scaffold, `globe.gl` dependency
- [x] WASM integration: load core, decode + aggregate the binary snapshot
- [x] `snapshot-detail.ts`: load `snapshot.json`, index the dossier by `id`
- [x] Globe render: points at ground zero + assault-vector arcs colored by severity
- [x] Halloween skin: dark globe, glow, pulse, scanline/glitch, reduced-motion guard
- [x] Insurgency Report banner, tooltip, dossier panel (data hit / fallout / the ward / link)
- [x] Themed loader (`INITIALIZING THE UPRISING…`)
- [x] On-screen globe controls (rotate / zoom / pause auto-rotate)
- [x] Country selection: only countries with reported strikes are selectable
- [ ] Timeline scrubber (stretch)

## 5. Infra (`infra/`)
- [x] `template.yaml` — S3, Python Lambda, EventBridge weekly schedule, DynamoDB, CloudFront
      (reworked in section 7: four Lambda stages + Step Functions state machine)
- [ ] `sam build && sam deploy --guided`; verify weekly job writes a fresh snapshot

## Pivot note (v1 → v2)
The project began on live botnet-IP feeds (abuse.ch). It was re-architected so every point
is a **real cyberattack reported by a recognized news outlet**, with an extracted dossier
(ground zero, data hit, severity, fallout, the ward, article link). The cross-language
binary contract was bumped to **v2** and all three implementations + fixtures regenerated
together (see AGENTS.md "Data contract invariant").

## Verified in this build env
- Python: `pytest` green (incl. property-based round-trip), `ruff` clean, `black` clean (3.13).
- Pipeline CLI produces a deterministic 156-byte snapshot (16 + 28×5) at the pinned date
  2026-11-14; every strike links to a concrete, HTTP-verified article (no generic/section
  links).
- Frontend: `tsc` typecheck clean, `vite build` succeeds. The Rust/WASM core is built with
  `wasm-pack` (0.15.1) and bundled into `dist/assets/`; the deployed site serves
  `rebellion_core_bg-*.wasm` as `application/wasm` through CloudFront.
- AI seam: `agent_extract` tests green (stub agent, incl. live Pydantic schema when installed).
  Optional Strands/Bedrock path exercised **live** against **Claude Opus 4.8**
  (`us.anthropic.claude-opus-4-8`, us-east-1) — structured dossier returned and mapped.
  Since section 7 the agent is mandatory; the offline run still makes zero Bedrock calls
  because every curated row is fully pinned, and its output matches the committed fixtures
  except `generated_at`.

## 6. Polish & submission
- [ ] README "how Kiro was used" write-up (specs, hooks, steering, MCP if used)
- [ ] Demo snapshot + 3-min video script
- [ ] Final checklist: `.kiro` present & not ignored, LICENSE detectable, repo public, English

## 7. Live ingestion with a mandatory agent + Step Functions (requirements story 6)
- [x] `sources.py` — `PER_FEED_LIMIT` 25 + `--per-feed-limit` / `PER_FEED_LIMIT` /
      `PerFeedLimit`; `is_concrete_url` rejects non-article segments anywhere in the path;
      `is_reportable_incident` (deny-list + incident signal) on live RSS only
- [x] `agent_extract.py` — mandatory sole extractor: strict `StrikeDossier`, country rule
      order, `DossierValidationError` on invalid / `ZZ` / `XX` / unknown-centroid codes,
      impact dedupe (`"Impact not disclosed."`), `ensure_agent_ready` preflight
- [x] `extract.py` / `geolocate.py` — heuristics removed; curated overrides > agent;
      geolocate is ISO → centroid + jitter only
- [x] `transform.py` / `cli.py` — discard on failure (no local retries),
      `DISCARD_THRESHOLD` 0.20 (exit 3); preflight failure → exit 2; `--use-agent`
      removed (threshold semantics reworked in section 8: a rejected batch still
      publishes the accumulated report)
- [x] `stages.py` — Lambda stages `preflight` / `fetch` / `extract` / `assemble`, S3
      staging, Timeline rows (`published` / `rejected` since section 8); `handler.py`
      re-export alias
- [x] `infra/statemachine/rebellion.asl.json` + `infra/template.yaml` — Map
      (`MaxConcurrency` 5, Retry `MaxAttempts` 2 / `IntervalSeconds` 10 / `BackoffRate` 2,
      Catch → discarded), schedule on the state machine, Bedrock IAM only on Preflight and
      Extract, no SQS / `UseAgent` / `EnableAgent`
- [x] Tests: stub agent + stub boto3 only (`test_stages.py`, `test_statemachine.py`, and
      updated pipeline/source/agent tests); committed fixtures verified unchanged
- [x] Docs: steering `agent-enrichment.md` + `tech.md`, AGENTS.md, README, this spec
- [x] Review v1 fixes: Discard keeps only `$.error.Error` (256 KB limit); word-boundary
      incident filter; `is_incident` → `NotAnIncident` skip; conditional Timeline put
      guarding published days; Bedrock IAM split per function (the zero-article rule was
      replaced in section 8: an empty day publishes the accumulated report)
- [x] Packaging: the Lambdas are built from a dedicated folder: `infra/build-lambda.sh`
      creates `infra/.build/lambda` (gitignored, `requirements.txt` at its root, no
      tests) and every function uses `CodeUri: .build/lambda`; run the script before
      `sam build`
- [x] CloudFront bucket policy scoped to `index.html`, `assets/*`, `geo/*`, and
      `snapshots/*`, so `staging/` objects are never served by the CDN
- [ ] `sam validate` / deploy and a live Step Functions run (not available locally)

## 8. Rolling 7-day Insurgency Report (requirements story 2 AC4/AC5, story 6 AC10/AC12/AC13)
- [x] `transform.py` — `RECENCY_WINDOW_DAYS` 7; `ReportOutcome(report, accepted,
      fetched, discarded, new, carried, expired)`; `drop_known` before extraction (known
      URLs never reach the agent, fully curated rows are rebuilt, in-batch URL dedupe);
      `assemble(results, report_date, previous, max_age_days)` carries unexpired strikes
      first, then new ones, ids `1..N`, carried strikes keep their coordinates; zero
      articles publishes the accumulated set; a rejected batch (> 20% discarded) adds no
      new strikes but the cleaned accumulated report is still published
- [x] `cli.py` — accumulates onto `--out/snapshot.json` unless `--fresh`; exit codes 0,
      2, 3 (batch rejected, report still written), 4 (invalid previous snapshot or one
      dated after `--date`, nothing written, checked before the preflight);
      `--max-age-days` default 7
- [x] `stages.py` — `Storage.get_optional`; Fetch skips URLs already in
      `snapshots/latest/`; Assemble always publishes `snapshots/{date}/` and
      `snapshots/latest/`; Timeline `published` / `rejected` with a conditional put that
      never replaces a published day
- [x] `infra/` — `AcceptedChoice` → `BatchRejectedFail` (`Error: BatchRejected`); Fetch and
      Assemble IAM `s3:GetObject` on `snapshots/latest/*` + unconditioned `s3:ListBucket`
      on the bucket (a `s3:prefix` condition never matches the `GetObject` check)
- [x] Review v1 follow-up — curated rebuilds replace their stored copy in place and count
      as carried (outside `fetched`/`new` and the discard ratio); `check_report_order` /
      `PreviousSnapshotAhead` refuse a previous report dated after the report date (CLI
      exit 4, Fetch and Assemble fail without writing); repeat agent calls for skipped
      non-incidents and unserialized overlapping executions are documented as accepted
- [x] `sources.py` — `non_incident_reason` and the
      `[sources] filtered ({witness}): {title} ({reason})` log line for dropped RSS items
- [x] Committed fixtures regenerated at 2026-11-14 with `--fresh` semantics: 5 strikes
      (the French supermarket fridges and SolarWinds fall outside the 7-day window)
- [x] Tests: accumulation, expiry bounds, URL dedupe with zero agent calls, curated
      rebuilds, zero-article runs, rejected batches, CLI `--fresh` / exit 3 / exit 4,
      stage storage and Timeline guards, ASL and IAM shape
- [x] Docs: steering, this spec, README, AGENTS.md, hooks; the lost ingestion report is
      restored as `docs/report-ingestion-news.md`
- [x] `cargo test` on the regenerated fixture (8 passed)

## 9. Rust/WASM core in production
- [x] `wasm-loader.ts` loads the package through `import.meta.glob`, so Vite bundles it as a
      lazy chunk and emits the `.wasm` into `dist/assets/`. The previous `@vite-ignore`
      dynamic import was never bundled, so production always fell back to the TS decoder
- [x] Build without the package still succeeds and falls back to TS, with a console warning
- [x] Deploy docs (README, steering `tech.md`, AGENTS.md): `npm run wasm` before
      `npm run build`, then invalidate `/index.html` on CloudFront
- [x] Lambda runtime and SAM build method moved to `python3.13`; `test_statemachine.py`
      asserts both
