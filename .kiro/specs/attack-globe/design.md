# Spec — Attack Globe · Design

## Architecture

```
          EventBridge (weekly, every Thursday)
                   │
                   ▼
        ┌──────────────────────────┐   news RSS: BBC · WaPo · NYT ·
        │  Step Functions           │◄── The Hacker News · HackerNoon ·
        │                           │    BleepingComputer · The Record
        │  RebellionStateMachine    │
        │  Preflight → Fetch →      │──► Amazon Bedrock (Strands agent)
        │  Map(Extract) → Assemble  │    via the Extract Lambda
        └──────────┬───────────────┘
          writes   │          writes summary row
     snapshot.json │  snapshot.bin        │
                   ▼                      ▼
                ┌──────┐             ┌──────────┐
                │  S3  │             │ DynamoDB │  (Rebellion Timeline)
                └──┬───┘             └────┬─────┘
       CloudFront  │                      │ (optional read Lambda)
                   ▼                      ▼
        ┌─────────────────────────────────────────┐
        │  Frontend (static, Vite + globe.gl)       │
        │   fetch snapshot.bin ──► rebellion-core   │
        │   (Rust/WASM: decode + aggregate) ──►     │
        │   render arcs/points on 3D globe;         │
        │   join snapshot.json dossier by `id`      │
        └─────────────────────────────────────────┘
```

## Pipeline stages

0. **Preflight** — `agent_extract.ensure_agent_ready()` imports `strands` + `pydantic`,
   calls `sts:GetCallerIdentity`, and checks the model (`bedrock:GetInferenceProfile` or
   `bedrock:GetFoundationModel`) before any feed is read. Failure raises `AgentUnavailable`
   (CLI exit code 2; the state machine fails).
1. **`sources.py`** — fetch & normalize RSS from the outlets into `RawArticle`s, at most
   `PER_FEED_LIMIT` (25) per feed. Drop non-article URLs (`is_concrete_url`, any path
   segment) and non-incident items (`is_reportable_incident`, live RSS only). Offline mode
   reads `fixtures/curated_incidents.json` (hand-verified real incidents, each able to pin
   fields via `overrides`).
2. **`agent_extract.py` + `extract.py`** — the mandatory Strands agent on Amazon Bedrock is
   the sole extractor: it returns a strict `StrikeDossier` (attack type, severity, summary,
   data hit, fallout, the ward, location, ground-zero `country`, nullable `origin_country`).
   `extract.finalize_dossier` applies curated overrides > agent and the impact dedupe;
   fully curated rows skip the agent. A validation or model error discards the article.
   `is_incident: false` raises `NotAnIncident`: a live article is skipped (not retried,
   not counted toward the threshold); a curated one is discarded instead.
3. **`geolocate.py`** — ISO code → representative coordinate (with deterministic jitter so
   same-country strikes don't stack). No name/demonym parsing.
4. **`binary.py` / `transform.py`** — dedupe against the previous report before
   extraction (`drop_known`), apply the discard threshold, merge with the previous
   report's unexpired strikes (7-day window), renumber ids, then emit the two artifacts.

## Orchestration

- **Cloud.** `infra/statemachine/rebellion.asl.json`, with Lambda stages in
  `pipeline/stages.py`: `Preflight` → `Fetch` (drops URLs already in
  `snapshots/latest/`, stages the rest under `staging/`) →
  `ExtractEach` (Map, `MaxConcurrency` 5; each item invokes Extract with Retry on
  `States.ALL`, `MaxAttempts` 2, `IntervalSeconds` 10, `BackoffRate` 2, then Catch → a Pass
  state marking it `discarded` with only the error name, `$.error.Error`, to stay under the
  256 KB payload limit; a non-incident returns `skipped`) → `Assemble` → `AcceptedChoice`
  (`Done` (`Succeed`), or `BatchRejectedFail` with `Error: BatchRejected`). Step Functions
  replaces SQS. Bedrock IAM is granted only to Preflight (model metadata reads) and
  Extract (model invocation). Fetch and Assemble may read `snapshots/latest/*`
  (`s3:GetObject` plus an unconditioned `s3:ListBucket` on the bucket, so a missing key
  is `NoSuchKey`; an `s3:prefix` condition would never match a `GetObject`). The four functions are packaged
  from `infra/.build/lambda` (`CodeUri: .build/lambda`), built by `infra/build-lambda.sh`
  before `sam build`. The CloudFront bucket policy only allows `index.html`, `assets/*`,
  `geo/*`, and `snapshots/*`, so `staging/` is never served.
- **Local CLI.** The same steps in one process; a failing article is discarded with no
  retries. The previous report is `--out/snapshot.json` unless `--fresh` is given.
- **Accumulation (rolling 7-day window).** Each run starts from the previous report.
  Known URLs never reach the agent; their stored strikes are carried over (a fully curated
  row is rebuilt from the curated data in place and counts as carried, never as fetched
  or new, so it does not dilute the discard ratio). Skipped non-incidents are not
  remembered and reach the agent again while they stay in a feed (accepted cost).
  Strikes published more than 7 days before the report date expire. Carried strikes
  come first, then the new ones, renumbered `1..N`;
  carried strikes keep their stored coordinates. `transform.assemble` returns a
  `ReportOutcome(report, accepted, fetched, discarded, new, carried, expired)`. A run with
  zero new articles publishes the accumulated set, possibly empty. A previous report
  dated after the report date is refused (`PreviousSnapshotAhead`), so the latest report
  never moves back in time; overlapping cloud executions are not serialized (the later
  Assemble wins, accepted for a weekly schedule).
- **Discard threshold.** `transform.DISCARD_THRESHOLD = 0.20`. Above it (strictly
  greater) the batch is rejected: its new strikes are not added, but the accumulated
  report, cleaned of expired strikes, is still published to `snapshots/{date}/` and
  `snapshots/latest/`. The Rebellion Timeline row for the day has `status: "rejected"`
  (a conditional put that never replaces a `published` row); the CLI writes the cleaned
  report and exits with code 3. An invalid previous snapshot, or one dated after the
  report date, is never overwritten (CLI exit code 4, checked before the preflight; the
  Lambda fails).

## Data model

One record per Machine Strike (reported cyberattack):

| Field            | Type          | Notes                                                  |
| ---------------- | ------------- | ------------------------------------------------------ |
| `id`             | u32           | join key between `.bin` and the JSON dossier.          |
| `lat` / `lon`    | f32           | ground zero (where the attack landed).                 |
| `origin_lat/lon` | f32           | attributed attacker origin (== ground zero if unknown).|
| `severity`       | u8 (0–3)      | 0 Tremor · 1 Breach · 2 Siege · 3 Dominion |
| `witness`        | u8 (0–7)      | BBC · WaPo · NYT · The Hacker News · HackerNoon · other · BleepingComputer · The Record |
| `country`        | 2 ASCII bytes | ISO-3166 alpha-2 of ground zero.                       |
| `published`      | u32           | article publication date, days since Unix epoch.       |
| _dossier (JSON)_ | strings       | title, location, data_affected, impact, prevention, summary, url, attack_type |

## Snapshot contract (`schema/`)

Two artifacts per day:
- `snapshot.json` — human-readable; carries the **full dossier** per strike (and is the
  no-WASM fallback / join source for the detail panel).
- `snapshot.bin` — compact binary (v2) decoded by the Rust/WASM core. Layout (little-endian):

```
Header:
  magic       4 bytes  = "RBMN"
  version     u8       = 2
  _pad        3 bytes  = 0
  date_days   u32      (report date, days since Unix epoch)
  count       u32      (number of strike records)
Records (count × 28 bytes):
  id u32 | lat f32 | lon f32 | origin_lat f32 | origin_lon f32 |
  severity u8 | witness u8 | country[2] u8 | published u32
```

JSON Schema lives at `schema/snapshot.schema.json`; the binary layout at
`schema/binary-layout.md`. Both are the single contract shared by `pipeline/` and
`rebellion-core/`.

## Rust/WASM core (`rebellion-core`)

- `decode(bytes) -> Snapshot` — validate magic/version=2, parse header + 28-byte records.
- `aggregate(snapshot, opts) -> RenderBatch` — one point per strike (carrying `id` + witness),
  build arcs origin→ground zero, bucket by severity, LOD cap. Flat typed arrays for globe.gl.
- Exposed to JS via `wasm-bindgen`; structures serialized with `serde`.

## Frontend

- `globe.gl` with a dark earth, custom arc/point colors per severity, pulse for high tiers,
  scanline/glitch post-processing (off under `prefers-reduced-motion`).
- Startup: themed loader → fetch `snapshot.bin` + `snapshot.json` in parallel →
  `rebellion-core.decode + aggregate` → render → join dossiers by `id` for the detail panel.
- Tooltip (location + tier) + dossier panel (data hit, fallout, the ward, article link).

## Error handling

- Missing today's snapshot → fall back to the latest available.
- Bad/short/wrong-version binary → WASM returns a typed error; frontend falls back to TS decoder.
- A failed feed → skip it, log, continue.
- An article the agent cannot extract → discarded (after 3 attempts in the cloud, at once
  locally). More than 20% discarded → the day's new strikes are left out and the
  accumulated report, cleaned of expired strikes, is still published.
- A live RSS item dropped by the incident filter → logged as
  `[sources] filtered ({witness}): {title} ({reason})`.
- Agent unavailable (SDK, credentials, model access) → the run stops before any fetch.

## Narrative skin

All names and copy follow `steering/narrative-tone.md` (Machine Strike, Witness, Ground Zero,
Data hit, Fallout, The ward, severity tiers, …). Facts stay faithful to the reporting.
