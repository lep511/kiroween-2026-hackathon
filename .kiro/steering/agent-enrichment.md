---
inclusion: fileMatch
fileMatchPattern: "{pipeline/**/*.py,pipeline/fixtures/curated_incidents.json}"
---

# Steering — Agent Extraction (Strands → Bedrock)

> Single source of truth for the **AI seam**: a Strands Agents agent on Amazon Bedrock
> that extracts every incident dossier. This file tells Kiro **how** to work on
> `pipeline/agent_extract.py` and what invariants must never break. See also
> `steering/tech.md` (stack) and `steering/narrative-tone.md` (voice).

## What it is

A [Strands Agents](https://strandsagents.com) agent reads one reported cyberattack
(headline + reported summary from a named outlet) and returns a **structured incident
dossier** via LLM structured output. It classifies the attack, writes a faithful summary,
and completes every dossier field. It is the **mandatory and only** extractor: there is no
heuristic fallback. This is the project's fourth Frankenstein seam: an LLM agent fused into
a pipeline of Python + Rust/WASM + WebGL.

## Non-negotiable invariants

- **Mandatory.** Without the SDK, valid AWS credentials, or Bedrock model access, nothing
  runs: not the CLI, not `--offline`, not the cloud. There is no `--use-agent` flag, no
  `USE_AGENT` env var, and no `UseAgent` / `EnableAgent` SAM parameter or condition.
- **Sole extractor.** No heuristic extraction exists. `geolocate.py` only maps an ISO code
  to coordinates (country centroid + deterministic jitter).
- **Precedence: curated `overrides` > agent.** Hand-verified reporting always wins; the
  agent only fills fields a curated incident left blank. A fully curated incident
  (`extract.needs_agent()` is false) skips the agent call entirely.
- **Preflight before any fetch.** `ensure_agent_ready()` checks, in order: `strands` and
  `pydantic` import; `sts:GetCallerIdentity` succeeds; the model is visible
  (`bedrock:GetInferenceProfile` for profile ids, `bedrock:GetFoundationModel` otherwise).
  The first failure raises `AgentUnavailable`. It spends no model tokens.
- **Failures discard, never degrade.** `StrandsExtractor.extract()` raises on any model or
  validation error. The article is discarded (it is not filled in by other means).
- **Non-incidents are skipped, never fabricated.** When the agent answers
  `is_incident: false`, `extract()` raises `NotAnIncident` (not a `DossierValidationError`).
  The article is skipped: it is not retried and does not count toward the discard
  threshold. The agent cannot veto a curated incident: for a curated row that verdict
  becomes a `DossierValidationError` (discard).
- **Lazy imports.** `strands`, `pydantic`, and `boto3` are imported inside the functions
  that need them, so `import pipeline.agent_extract` succeeds without them (the test suite
  relies on this). They are still required runtime dependencies.
- **English only.** Every field, comment, prompt, and instruction is in English, per
  `steering/tech.md`. The agent must stay faithful to the reporting: the machine-uprising
  framing is a cosmetic skin applied elsewhere, never in the extracted facts.

## Structured-output contract

The agent returns a Pydantic `StrikeDossier` (built lazily in `_dossier_model()`). Every
field is required except `origin_country`, which is nullable. `_to_overrides()` checks
`is_incident` first (`false` raises `NotAnIncident`), then maps the rest to an
override-shaped dict and raises `DossierValidationError` on any violation.

| Field            | Constraint                                                          |
| ---------------- | ------------------------------------------------------------------- |
| `is_incident`    | `bool`; `false` = not one concrete cyber incident → skipped         |
| `attack_type`    | `Literal` of `models.ATTACK_TYPES` (no `"unknown"`)                 |
| `severity`       | `Literal` of `SEVERITY_LABELS` (`tremor`/`breach`/`siege`/`dominion`) |
| `summary`        | one or two neutral, factual sentences                               |
| `data_affected`  | data/systems compromised                                            |
| `impact`         | who/what was affected and the scale of the fallout                  |
| `prevention`     | one concrete, actionable mitigation ("the ward")                    |
| `location`       | human-readable ground zero                                          |
| `country`        | ISO-3166 alpha-2, required, must exist in `COUNTRY_CENTROIDS`       |
| `origin_country` | ISO-3166 alpha-2 or `null` (unattributed → arc collapses)           |

Keep the taxonomy in sync: `ATTACK_TYPES` lives in `models.py` and `SEVERITY_LABELS` is
derived from the `Severity` enum. Never hard-code a divergent list.

### Country rule (ground zero)

`country` is always the victim's side. The prompt orders the rules and the agent stops at
the first that applies:

1. The country the report states the attack hit.
2. The headquarters country of the named victim organization.
3. The headquarters country of the vulnerable or abused product's vendor.
4. The most-affected country according to the report.

Never the attacker's origin or the outlet's country. An invalid code, a placeholder
(`ZZ`, `XX`), or a code missing from `COUNTRY_CENTROIDS` is a `DossierValidationError`.

### Impact dedupe

If the agent's `impact` duplicates its `summary` (after lowercasing, collapsing whitespace,
and stripping trailing punctuation, the two are equal or `impact` equals the first sentence
of `summary`), `impact` becomes `"Impact not disclosed."` (`IMPACT_NOT_DISCLOSED`). A
curated `impact` is never touched.

## Model configuration

- Default model: **Claude Sonnet 4.6** on Bedrock, pinned in `DEFAULT_MODEL_ID`
  (`global.anthropic.claude-sonnet-4-6`, the global cross-region inference profile).
- Change the model (highest precedence first):
  1. CLI flag `--agent-model <id>`
  2. Env var `AGENT_MODEL_ID` (local, or the Lambda / SAM `AgentModelId` parameter)
  3. Edit the `DEFAULT_MODEL_ID` constant
- Region: `--agent-region` / `AGENT_REGION` (SAM `AgentRegion`), otherwise resolved from
  the AWS environment.
- **No temperature** (or other sampling params) is set.

## Runs, accumulation, and the discard threshold

The Insurgency Report is a **rolling 7-day window** (`transform.RECENCY_WINDOW_DAYS = 7`).
Every run, local or cloud, does the same thing:

1. **Start from the previous report.** The last published `snapshot.json` is the starting
   point (locally `--out/snapshot.json`, in the cloud `snapshots/latest/snapshot.json`).
2. **Dedupe by URL before extraction.** `transform.drop_known` drops every article whose
   URL is already in the previous report, so a known URL **never reaches the agent** and
   its stored strike (dossier and coordinates) is reused. A fully curated row
   (`needs_agent()` is false) is the exception: it is rebuilt from the curated data at
   zero agent cost, so a curated edit stays authoritative. The rebuild replaces the stored
   copy in place and counts as **carried**, never as fetched or new, so it neither
   inflates `new` nor dilutes the discard ratio. Duplicate URLs inside one batch keep the
   first occurrence. Only stored strikes are remembered: a skipped non-incident, a
   discarded article, and every article of a rejected batch reach the agent again on the
   next run while they stay in a feed. For non-incidents that repeat cost is accepted
   (bounded by feed retention and `PER_FEED_LIMIT`, after the deterministic filter);
   persisting verdicts would need a new artifact outside the `schema/` contract.
3. **Expire.** A strike published more than 7 days before the report date is dropped
   (exactly 7 days old is kept, see `within_window`).
4. **Renumber.** Carried strikes come first, then the day's new ones, with ids `1..N`.
   Carried strikes keep their stored coordinates; only their id changes.
5. **Never go back in time.** A previous report dated **after** the report date raises
   `PreviousSnapshotAhead` (a `PreviousSnapshotInvalid`) before any agent call or write
   (`transform.check_report_order`); the same date (a rerun) is allowed. A backfill
   therefore needs `--fresh` locally and cannot run against `snapshots/latest/` in the
   cloud.

`transform.assemble` returns a `ReportOutcome(report, accepted, fetched, discarded, new,
carried, expired)`. `transform.DISCARD_THRESHOLD = 0.20`: if **more than** 20% of the
day's new articles are discarded, the batch is **rejected** (`accepted` is false). A
rejected batch adds none of its new strikes, but the accumulated report, cleaned of
expired strikes, is still published, so the globe never shows a strike older than 7
days. Skipped non-incidents are left out of both counts. A day with **zero** new articles
is accepted and publishes the accumulated set, which may be empty (the globe then shows
`No machine strikes reported. For now.`).

- **Local CLI.** The CLI reads `--out/snapshot.json` as the previous report unless
  `--fresh` is given (`--fresh` ignores it, used to regenerate the committed fixtures). An
  invalid previous snapshot, or one dated after `--date`, exits **4** and writes nothing;
  this check runs before the
  preflight. Then preflight: on `AgentUnavailable` the CLI exits **2** before reading any
  feed. A failing article is discarded immediately, with **no retries**. The report is
  always written; the CLI exits **0** when the batch was accepted and **3** when it was
  rejected.
- **Cloud (Step Functions).** EventBridge starts `RebellionStateMachine`
  (`infra/statemachine/rebellion.asl.json`):
  `Preflight → Fetch → ExtractEach (Map, MaxConcurrency 5) → Assemble → Summarize →
  InvalidateCache → AcceptedChoice`.
  Fetch drops every URL already in `snapshots/latest/` before staging. Each Map item
  invokes the Extract Lambda with `Retry` on `States.ALL` (`MaxAttempts 2`,
  `IntervalSeconds 10`, `BackoffRate 2`, so 3 attempts in total), then `Catch` marks the
  item `status: "discarded"`, keeping only the error name (`$.error.Error`) so a
  mass-failure run stays under the 256 KB state payload limit. A non-incident returns
  `status: "skipped"` without a retry. Assemble merges the results with the latest report
  and **always** publishes `snapshots/{date}/` and `snapshots/latest/`. The Rebellion
  Timeline records the day as `published` (accepted) or `rejected`. The `rejected` row is
  a conditional put, so a rejected rerun never replaces a day already recorded as
  `published`. Summarize (a separate Lambda, with its own model) then writes
  `snapshots/{date}/summary.md` for the published report, rejected batches included; it
  retries twice, and its `Catch` stores the error in `$.summary_error` and moves on, so a
  failed summary never fails the run. `AcceptedChoice` routes a rejected batch to the
  `BatchRejectedFail` state
  (`Error: BatchRejected`); an accepted one ends in `Done`. An invalid
  `snapshots/latest/snapshot.json` (`PreviousSnapshotInvalid`), or one dated after the
  run's report date (`PreviousSnapshotAhead`, raised in Fetch before any feed is read and
  again in Assemble), fails the Lambda without overwriting it. Overlapping executions are
  not serialized: the later Assemble wins and the other execution's new strikes return on
  a later run while they stay in the feeds. That is accepted for a weekly schedule. Step
  Functions replaces any queue: there is no SQS.

## Wiring

- `sources.py` — `fetch_all(offline, limit, per_feed_limit)`; `PER_FEED_LIMIT = 25`;
  `is_concrete_url` rejects non-article segments anywhere in the path;
  `is_reportable_incident` filters live RSS only (in `_emit`), never `load_curated`; its
  keyword and signal lists match on word boundaries ("hackathon" is not a hack).
  `non_incident_reason(title, summary)` explains each rejection, and `_emit` logs
  `[sources] filtered ({witness}): {title} ({reason})` for every dropped article.
- `extract.py` — `REQUIRED_FIELDS`, `curated_fields`, `needs_agent`, `finalize_dossier`
  (precedence + impact dedupe), `build_strike(article, dossier, idx, geo)`.
- `transform.py` — `RECENCY_WINDOW_DAYS = 7`, `ReportOutcome`, `drop_known`,
  `fetch_articles(..., known_urls=None)`, `extract_one`,
  `assemble(results, report_date, previous, max_age_days)`,
  `build_report(articles, extractor, ..., previous)`,
  `run(..., agent_model, agent_region, extractor=None, ready_check=None, previous=None)`,
  `read_previous`, `load_snapshot_json`, `check_report_order`, `PreviousSnapshotInvalid`,
  `PreviousSnapshotAhead`.
- `cli.py` — `--summary` (step 7: `summary.md` in `--out`, refused when `--out` is named
  `latest`; a failure warns and keeps the exit code) and `--summary-model`
  (`SUMMARY_MODEL_ID`, else Opus 4.6), `--per-feed-limit`, `--max-age-days` (default 7),
  `--fresh`, `--agent-model`, `--agent-region`; exit codes 2, 3, and 4.
- `stages.py` — Lambda stages `preflight`, `fetch`, `extract`, `assemble`, `summarize`
  (`S3Storage`, `DynamoTimeline`, `PER_FEED_LIMIT` env). `Storage.get_optional` returns
  `None` for a missing key; Fetch and Assemble both read `snapshots/latest/snapshot.json`.
  Run rows carry `kind = "RUN"` (`RUN_KIND`) and `date`, so the sparse GSI `runs-by-date`
  (`RUNS_INDEX`) lists them. After the timeline writes, Assemble rebuilds
  `snapshots/manifest.json` with `build_manifest`: `DynamoTimeline.list_runs()` (one
  paginated Query on the index, eventually consistent) plus `get_run(date)` (a
  `ConsistentRead` GetItem for the run just written). A date already in the published
  manifest is never dropped, and a timeline read failure falls back to updating the S3
  manifest in place. `handler.py` re-exports the stages.
- `summarize.py` — the weekly summary, a second agent seam that never touches the
  dossiers: `StrandsSummarizer` (Strands on Bedrock, `DEFAULT_SUMMARY_MODEL_ID` =
  `global.anthropic.claude-opus-4-6-v1`, overridden by `SUMMARY_MODEL_ID`, `max_tokens`
  8192, no sampling params), `build_prompt` (title, window, counts, verdict, one JSON
  dossier per line, no URLs), `finalize_summary` (strips a code fence, requires a `# `
  title and a body, caps the length, pins the title `# Weekly Cyber Incident Summary
  ({window})`), and `generate_summary` (a report without strikes gets a fixed summary and
  no model call). A truncated answer (`stop_reason` other than `end_turn`) raises
  `SummaryError`. The summary is factual, never in the uprising voice.
- `timeline_admin.py` — operator CLI: `migrate` (backfills `kind`/`date` on run rows and
  rebuilds missing run rows from published snapshots) and `rebuild-manifest` (rewrites
  the production manifest from the timeline). Read-only unless `--apply`.
- `infra/template.yaml` — five functions (`pipeline.stages.*`, `CodeUri: .build/lambda`,
  built by `infra/build-lambda.sh` before `sam build`), the state machine with the weekly
  schedule, parameters `PerFeedLimit` (default `"25"`), `AgentModelId`, `AgentRegion`,
  `SummaryModelId` (default Claude Opus 4.6, the Summarize Lambda's `SUMMARY_MODEL_ID`).
  Bedrock IAM is granted **only** to the Preflight function (`GetInferenceProfile`,
  `GetFoundationModel`), the Extract function and the Summarize function (`InvokeModel*`,
  `Converse*`). Summarize reads only `snapshots/*/snapshot.json` and writes only
  `snapshots/*/summary.md`. Fetch and
  Assemble get `s3:GetObject` on `snapshots/latest/*` and an unconditioned `s3:ListBucket`
  on the bucket (so a first run sees `NoSuchKey`, not `AccessDenied`). It must not carry
  an `s3:prefix` condition: the implicit ListBucket check behind a `GetObject` has no
  prefix, so the condition would never match. Confirm after deploy with
  `aws s3api get-object` on a missing key under the function role. On the timeline,
  Assemble has `DynamoDBWritePolicy` plus exactly `dynamodb:Query` on
  `${TimelineTable.Arn}/index/runs-by-date` and `dynamodb:GetItem` on the table (no
  `Scan`); no other function touches DynamoDB. Index changes go in their own deploy:
  CloudFormation creates or deletes at most one index per stack update.

## Testing

- Unit tests inject a **stub agent** and **stub boto3 clients**. Tests never call Bedrock
  or the network. Cover mapping/validation, the country rule, impact dedupe, precedence,
  the skip guard, non-incident skips, preflight failures, discards, the threshold
  (rejected batch publishes the cleaned accumulated report), accumulation and the 7-day
  expiry, URL dedupe with zero agent calls for known URLs, curated rebuilds (counted as
  carried, outside the discard ratio), zero-article runs, the report-date ordering guard,
  CLI `--fresh` and exit codes 3/4, and the rejected-rerun Timeline guard.
- The summary tests (`test_summarize.py`) use a stub summarizer: prompt contents, title
  window, output validation, truncation, the empty-report shortcut, and the stage's key,
  content type and model id. The CLI `--summary` tests (`test_pipeline.py`) inject one
  through `cli.main(summarizer=...)`.
- The real Pydantic schema test is gated on `pydantic` being importable (`pytest.skipif`).
- Verify the live path manually.

```bash
# Every run needs AWS credentials + Bedrock model access, including --offline
pip install -e '.[dev]'
python -m pipeline.cli --out ./sample --offline
python -m pipeline.cli --out ./sample --per-feed-limit 25
python -m pipeline.cli --out ./sample --summary      # also writes summary.md
python -m pipeline.cli --out ./sample --agent-model global.anthropic.claude-opus-4-8
```
