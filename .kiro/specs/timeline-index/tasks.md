# Spec — Timeline Index · Tasks

Ordered, checkable tasks. See `requirements.md` for the acceptance criteria and
`design.md` for the modules and the rollout record.

## 1. Sparse GSI `runs-by-date` (template only) + Deploy 1 (story 2 AC3)
- [x] `kind` / `date` attribute definitions and the `runs-by-date` GSI; `sk-pk-index` kept.
- [x] Tests: index key schema and projection; every attribute definition is a key.
- [x] Deploy 1: changeset `TimelineTable` Modify only; index ACTIVE and empty.

## 2. Assemble builds the manifest from the timeline (story 1)
- [x] `RUN_KIND`, `RUNS_INDEX`; run rows get `kind` and `date`.
- [x] `Timeline.list_runs` / `get_run`; `InMemoryTimeline(index_lag=...)`.
- [x] `build_manifest`, `_publish_manifest`, fallback to `_update_manifest` (keeps `runs`).
- [x] Tests: end to end, index lag, rejected day, rejected rerun, backfill, kept dates,
      read failure fallback, no timeline, `build_manifest`, row validation.

## 3. DynamoDB reads + Assemble IAM + Deploy 2 (story 2 AC1)
- [x] `DynamoTimeline.list_runs` (paginated Query) and `get_run` (ConsistentRead).
- [x] Assemble: `dynamodb:Query` on the index, `dynamodb:GetItem` on the table.
- [x] Tests: stub table pagination, `Decimal` → `int`, exact IAM statements, no Scan.
- [x] Deploy 2: functions, Assemble role, state machine (dynamic ARNs); table untouched.

## 4. `timeline_admin migrate` + production migration (story 3)
- [x] Plan, conditional writes, read-only default, confirmation, idempotency.
- [x] Tests with a production-like fixture (4 updates + 1 reconstruction).
- [x] Production: plan matched; applied; rerun had nothing to do; index lists 5 runs.

## 5. `timeline_admin rebuild-manifest` + retire `--publish-manifest` (story 4)
- [x] Diff output, no-drop and published-snapshot guards, RUNNING guard, invalidation.
- [x] `sync-snapshots.sh --publish-manifest` exits 2 with a pointer to the new command.
- [x] Production: 5 runs written; `curl https://d28ltls6g6c7d1.cloudfront.net/snapshots/manifest.json`
      shows `runs`.

## 6. The committed archive keeps `runs` (story 6)
- [x] `frontend/scripts/manifest.mjs` + tests; sync and `--manifest-only` use it.
- [x] `pipeline/cli.py` keeps `runs`; test.
- [x] `archive.test.ts` run checks; `npm run sync-snapshots` wrote 5 runs.

## 7. Picker totals and REJECTED tag (story 5)
- [x] `parseRuns`, `pickerEntry` with tests; picker rendering, copy and styles.
- [x] Browser check (headless Chromium, SwiftShader, outside the repo): 5 dates with
      totals; a network-level override marking 2026-11-16 rejected showed the tag, its
      title, and the accessible name `Mon, Nov 16, 2026 REJECTED 27 strikes`.

## 8. Drop `sk-pk-index` + Deploy 3 (story 2 AC2)
- [x] Template and test: `runs-by-date` is the only index.
- [x] Deploy 3: only `TimelineTable` updated; dependents byte-identical; one index ACTIVE.

## 9. Docs and final validation (story 7)
- [x] This spec; rebellion-timeline and attack-globe specs; steering; README; hooks.
- [x] `pytest`, `ruff`, `black --check`, `npm test`, `npm run build`, `sam validate --lint`.
