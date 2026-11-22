# Spec — Attack Globe · Requirements

Feature: the interactive 3D globe that visualizes the daily "machine uprising" as a
map of **real cyberattacks reported by recognized news outlets**.

## Problem

Serious cyberattacks are reported constantly — ransomware shutting hospitals, grids cut,
supply-chain backdoors — but the reporting is scattered and abstract for non-experts. We
want a memorable, daily-refreshed world map that places each **real, reported** attack
where it struck and, crucially, pairs it with **how it could have been prevented** — all
wrapped in a vivid "the machines are rising up" story.

## Sources (recognized witnesses)

BBC News, The Washington Post, The New York Times, The Hacker News, HackerNoon,
BleepingComputer, The Record.
For each incident we extract a dossier: **ground zero (location), data hit, severity,
fallout, the ward (prevention), and a link to the article.**

## User stories & acceptance criteria

### 1. See the uprising at a glance
**As a** visitor, **I want** a 3D globe to load with glowing strike points and arcs,
**so that** I immediately grasp today's reported attacks.
- **AC1:** On load, a dark 3D globe renders with a themed loading message, then animates in.
- **AC2:** Machine Strikes appear as points at ground zero; Assault Vectors arc from an
  attributed origin to ground zero (collapsing to the point when attribution is unknown).
- **AC3:** Points/arcs are colored by severity tier (Tremor → Dominion).
- **AC4:** The scene stays interactive (drag to rotate, scroll to zoom) and smooth.

### 2. Daily freshness
**As a** returning visitor, **I want** the data to reflect the latest snapshot.
- **AC1:** The globe loads the most recent Insurgency Report (snapshot) at startup.
- **AC2:** A banner shows the report date and the count of reported strikes.
- **AC3:** If today's snapshot is missing, the most recent available one is shown.
- **AC4:** A report is a **rolling 7-day window** (`RECENCY_WINDOW_DAYS = 7`): each
  weekly run starts from the previously published report, adds new strikes, and
  drops every strike published more than 7 days before the report date (exactly 7 days
  old is kept), so famous historic breaches and stale RSS re-runs never leak into the
  uprising. The window is configurable (`pipeline.cli --max-age-days`, `0` disables it);
  curated incidents fall outside the window, they are never deleted.
- **AC5:** A run with no new articles still publishes the accumulated report. If nothing
  was reported in 7 days the report is empty and the globe shows
  `No machine strikes reported. For now.`

### 3. Inspect a strike (the dossier)
**As a** curious visitor, **I want** to hover/click a point, **so that** I can see what
happened and how it could have been stopped.
- **AC1:** Hover shows a tooltip: Machine Strike · location · threat tier.
- **AC2:** Click opens a panel with the full dossier: headline, ground zero, threat tier,
  attack type, **data hit**, **fallout**, **the ward (prevention)**, publication date, and
  a link to the source article at the witness outlet.
- **AC3:** The dossier states facts faithfully to the reporting; only the framing is fiction.

### 4. Travel the Rebellion Timeline (stretch)
**As a** visitor, **I want** to scrub across past days to watch the uprising escalate.
- Delivered as the report-history picker with an archive indicator and animated
  transitions; acceptance criteria in `../rebellion-timeline/requirements.md`.

### 5. Performance via Rust/WASM
**As a** maintainer, **I want** decode/aggregate done in Rust/WASM.
- **AC1:** The browser fetches the compact binary snapshot and decodes it with the WASM core.
- **AC2:** The core builds render points (one per strike, carrying `id`) + assault-vector arcs;
  the rich dossier JSON is joined to each point by `id`.

### 6. Live ingestion with a mandatory extraction agent
**As a** maintainer, **I want** every dossier extracted by a Strands/Bedrock agent from
filtered live news, orchestrated so one bad article never sinks the day.
- **AC1 (per-feed limit):** Each live feed contributes at most **25** articles by default,
  configurable via `--per-feed-limit` (CLI), `PER_FEED_LIMIT` (Lambda env), and the SAM
  parameter `PerFeedLimit`. The global `--limit` still applies.
- **AC2 (concrete links):** `is_concrete_url` rejects a URL when **any** path segment is a
  non-article segment (`sounds`, `podcast(s)`, `video(s)`, `live`, `audio`,
  `newsletter(s)`, `webinar(s)`), in addition to the existing last-segment rule.
- **AC3 (non-incident filter):** Live RSS items pass a deterministic filter (title
  deny-list + a required incident signal) before extraction. Curated incidents skip it.
- **AC4 (mandatory agent):** Without the SDK, AWS credentials, or Bedrock model access,
  nothing runs: not the CLI, not `--offline`, not the cloud. A preflight checks this before
  any feed is read (CLI exit code 2). There is no opt-in flag (`--use-agent` / `USE_AGENT`
  / `UseAgent` are removed); `--agent-model` / `AGENT_MODEL_ID` and `--agent-region` /
  `AGENT_REGION` remain.
- **AC5 (sole extractor):** There is no heuristic extraction. Precedence is curated
  `overrides` > agent; a fully curated incident never calls the agent. `geolocate` only
  maps an ISO code to coordinates (centroid + jitter).
- **AC6 (ground zero country):** `country` is required and never `ZZ`. The agent decides it
  in this order: the country stated in the report → the victim organization's HQ country →
  the vulnerable product vendor's HQ country → the most-affected country per the report.
  Never the attacker's origin or the outlet's country. An invalid code, `ZZ`/`XX`, or a
  code missing from `COUNTRY_CENTROIDS` is a validation error.
- **AC7 (impact dedupe):** If the agent's `impact` duplicates its `summary` (normalized:
  lowercase, collapsed whitespace, trailing punctuation stripped; equal, or `impact` equals
  the first sentence of `summary`), `impact` becomes `"Impact not disclosed."`. A curated
  `impact` is never touched.
- **AC8 (cloud orchestration):** AWS Step Functions runs a Map with one Extract per article:
  3 attempts (Retry `MaxAttempts` 2 with backoff), then Catch marks the article
  `status: "discarded"`. Step Functions replaces SQS entirely.
- **AC9 (local CLI):** An agent failure discards the article immediately, with no retries.
- **AC10 (discard threshold):** If **more than 20%** of the day's new articles are
  discarded, the batch is rejected: its new strikes are not added, but the accumulated
  report, cleaned of strikes older than 7 days, is still published to
  `snapshots/latest/`. The Rebellion Timeline records the day with `status: "rejected"`
  (`"published"` when accepted), the state machine ends in `Fail` (`BatchRejected`), and
  the CLI writes the cleaned report and exits with code 3. A run with zero new articles is
  accepted and publishes the accumulated set. Items the agent rejects as non-incidents
  (`is_incident: false`) are skipped and not counted, and a rejected rerun never replaces
  a day already recorded as `published`.
- **AC11 (tests and contract):** Tests never call Bedrock or the network (stub agent, stub
  boto3 clients). Binary layout v2, `schema/`, the frontend, and the Rust core do not change.
- **AC12 (accumulation and dedupe):** Both the local CLI and the cloud accumulate. The CLI
  reads `--out/snapshot.json` as the previous report unless `--fresh` is given; the cloud
  reads `snapshots/latest/snapshot.json`. An article whose URL is already in the previous
  report never reaches the agent: its stored dossier and coordinates are reused with a
  renumbered id (a fully curated row is rebuilt from the curated data instead, also with
  no agent call, in place, and counted as carried, never as fetched or new). Duplicate
  URLs within one batch are extracted once. Carried strikes come first, then the new
  ones, with ids `1..N`. An invalid previous snapshot, or one dated after the report
  date, is never overwritten (CLI exit code 4; the Lambda fails), so the latest report
  never moves back in time.
- **AC13 (filter logging):** Each live RSS item the deterministic incident filter drops is
  logged as `[sources] filtered ({witness}): {title} ({reason})`.

## Non-functional requirements

- **Offline dev:** the frontend and Rust core work against the committed snapshot built
  from hand-verified real incidents, with no AWS account and no network. Regenerating it
  runs the agent preflight and therefore needs AWS credentials (story 6, AC4).
- **Reproducible:** the offline snapshot is deterministic (stable ids, coordinates, fields):
  every curated row pins all dossier fields, so the agent is never called for it.
- **Cost:** no always-on server; weekly batch + static hosting only.
- **Language:** all UI copy in English, following `steering/narrative-tone.md`.
- **Accessibility:** legible contrast, keyboard-focusable controls, respects
  `prefers-reduced-motion` (dampens glitch/pulse effects).

## Out of scope (v1)

User accounts, live streaming/WebSockets, write operations, mobile-native apps.
(Superseded: v1 listed LLM extraction as out of scope; story 6 makes the agent the sole
extractor.)
