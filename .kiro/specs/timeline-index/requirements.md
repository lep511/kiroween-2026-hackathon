# Spec — Timeline Index · Requirements

Feature: build the report manifest (`snapshots/manifest.json`) from the Rebellion
Timeline in DynamoDB through a sparse global secondary index, and show each report's
verdict and strike total in the report picker. Follows `../rebellion-timeline/`.

## Problem

- `stages._update_manifest` read-modify-wrote `snapshots/manifest.json` in S3. Two
  overlapping executions could each read the old list and the later write would drop the
  other's date for good (`../rebellion-timeline/design.md`, "Manifest race").
- The picker could not tell a `published` day from a `rejected` one, nor how many strikes
  a report holds, although the timeline records both.
- The DynamoDB table was write-only. Its only index, `sk-pk-index` (partition `sk`,
  projection `ALL`), had no reader and doubled every write.
- Production had run rows for 2026-11-05, 16, 17 and 19, but none for 2026-11-15, whose
  report is published in S3 and listed in the manifest.

## User stories & acceptance criteria

### 1. The manifest comes from the timeline
**As a** maintainer, **I want** Assemble to derive the manifest from DynamoDB,
**so that** overlapping executions cannot lose a report date.
- **AC1:** Run rows carry `kind = "RUN"` and `date` (`YYYY-MM-DD`). A sparse GSI
  `runs-by-date` (partition `kind`, sort `date`, projection `INCLUDE [status, total]`)
  holds only them; country and `LATEST` rows stay out.
- **AC2:** After the timeline writes, Assemble lists every run with one paginated Query on
  the index and overlays the run just written with a `ConsistentRead` GetItem, because
  index reads are eventually consistent.
- **AC3:** The manifest is `{"dates": [...], "runs": [{date, status, total}]}`, both
  ascending. `dates` keeps its old meaning, so old readers keep working.
- **AC4:** A date already in the published manifest is never dropped; one without a run
  row is kept and logged (`[manifest] kept {date}: no timeline row`).
- **AC5:** If the timeline cannot be read, Assemble logs it and updates the S3 manifest in
  place as before (keeping its `runs`). Write errors still fail the stage.
- **AC6:** A rejected rerun over a published day keeps `published` in the manifest.
- **AC7:** Without `TIMELINE_TABLE` (local runs, tests) the old `{"dates"}` behavior stays.

### 2. Least privilege and one index
- **AC1:** Assemble gets `dynamodb:Query` on `${TimelineTable.Arn}/index/runs-by-date` and
  `dynamodb:GetItem` on the table, on top of `DynamoDBWritePolicy`. No `Scan`; no other
  function touches DynamoDB.
- **AC2:** `sk-pk-index` is removed; `runs-by-date` is the table's only index.
- **AC3:** Each index change ships in a deploy of its own (CloudFormation creates or
  deletes at most one index per update) whose changeset modifies only the table.

### 3. Migrate production
- **AC1:** `python -m pipeline.timeline_admin migrate` adds `kind`/`date` to every run row
  that lacks them and rebuilds the run row of every published report that has none, from
  its `snapshot.json` (`status: "published"`, `reconstructed: true`). It is read-only
  unless `--apply`, asks before writing unless `--yes`, uses conditional writes, and is
  idempotent.
- **AC2:** In production the plan is exactly 4 updates (2026-11-05, 16, 17, 19) and 1
  reconstruction (2026-11-15); afterwards the index lists 5 runs.

### 4. Repair the production manifest from the timeline
- **AC1:** `python -m pipeline.timeline_admin rebuild-manifest` prints the current and
  target dates, the added and kept dates, and the runs. It is read-only unless `--apply`.
- **AC2:** It never drops a current date, refuses a date without a published snapshot,
  refuses to write while an execution is running, writes `application/json` with
  `max-age=300`, and invalidates `/snapshots/manifest.json` on CloudFront.
- **AC3:** `sync-snapshots.sh --publish-manifest` is removed; it now exits 2 and points to
  this command.

### 5. The picker shows verdicts and totals
**As a** visitor, **I want** to see how big each past report is and which days were
rejected.
- **AC1:** Each picker date shows its strike total (`1 strike`, `44 strikes`).
- **AC2:** A rejected day shows a `REJECTED` tag whose title explains the discard
  threshold. The button text (date, tag, total) is its accessible name.
- **AC3:** A missing or malformed `runs` field leaves the picker as before (dates only).

### 6. The committed archive keeps the runs
- **AC1:** `npm run sync-snapshots` copies the `runs` of the valid folders from the
  production manifest; `--manifest-only` and the pipeline CLI keep them.
- **AC2:** `archive.test.ts` checks that every run date is listed, runs are ascending with
  a valid status, and each `total` equals the strikes of that folder's `snapshot.json`.

### 7. Tests and docs
- **AC1:** Tests never touch AWS (in-memory timeline, stub boto3 clients).
- **AC2:** Steering, the README, the regen hooks, and the attack-globe and
  rebellion-timeline specs describe the new flow.

## Decisions (from the planning conversation)

| Question                      | Decision                                                  |
| ----------------------------- | --------------------------------------------------------- |
| How Assemble lists the runs   | New sparse GSI `runs-by-date` + consistent GetItem overlay |
| Existing `sk-pk-index`        | Delete it, in its own deploy                              |
| Frontend scope                | Picker shows totals and REJECTED; archive keeps `runs`    |
| Staging stack                 | No; deploy to production in three separate updates       |
| Confirmations                 | None: the developer authorized the whole rollout          |

## Non-functional requirements

- **Backward compatible:** `dates` is unchanged; `runs` is additive.
- **No contract change:** binary layout v2, `schema/`, and the Rust core are untouched.
- **Language:** all code, docs and UI copy in English (`steering/narrative-tone.md`).

## Out of scope

A Lambda or API that serves the timeline to the browser, per-country history in the UI,
deploying the new frontend to CloudFront, and a JSON Schema for the manifest.
