# Spec — Rebellion Timeline · Requirements

Feature: browse past Insurgency Reports on the globe, with a clear archive indicator,
animated transitions between reports, and a local copy of the production archive.
Delivers story 4 ("Travel the Rebellion Timeline") of `../attack-globe/requirements.md`.

## Problem

The report history of the globe UI is confusing and brittle:

- The LATEST button is always visible, even on the latest report. The CSS rule
  `.btn-latest { display: inline-flex }` overrides the `hidden` attribute.
- Nothing tells the visitor whether they are looking at the latest Insurgency Report or an
  archived one.
- Changing the date swaps the markers instantly: pins pop in and out, and only new arcs
  grow (three-globe's 1000 ms default).
- Rapid clicks can leave the UI on a stale report, and the heatmap toggle breaks after a
  few date changes (a new click listener is added on every load).
- Locally, only `latest/` exists, plus a symlink `frontend/public/snapshots/2026-11-14 ->
  latest`. The latest report is dated 2026-11-19, so picking "2026-11-14" shows
  2026-11-19 data.
- Production S3 holds 5 dated reports, but its `manifest.json` lists only 3.

## User stories & acceptance criteria

### 1. Know when I am looking at the past
**As a** visitor, **I want** the globe to tell me when I am viewing an archived report,
**so that** I never mistake old strikes for the current uprising.
- **AC1 (latest mode unchanged):** When the latest report is shown, the banner looks exactly
  as before: no archive chip and no LATEST button.
- **AC2 (archive mode):** When a past report is shown, an amber/gold chip
  `ARCHIVE · {Wkd, Mon D, YYYY}` (e.g. `ARCHIVE · Tue, Nov 17, 2026`) appears in the banner,
  and the LATEST button is visible.
- **AC3 (return):** The LATEST button returns to the latest report and both the chip and the
  button disappear.
- **AC4 (accessibility):** Mode changes are announced to screen readers through an
  always-present `role="status"` live region (`#report-status`): entering archive mode
  announces the archived date, returning announces the latest report. The initial load
  announces nothing.
- **AC5 (definition of latest):** The latest date is the `date` inside the report served at
  `/snapshots/latest/`, read on the initial load. It is not the newest manifest date,
  because a backfill adds a date without touching `latest/`. Picking that same date from
  the picker counts as latest mode.
- **AC6 (picker highlight):** The picker highlights the date being shown, including on the
  initial load.

### 2. Watch the uprising change between reports
**As a** visitor, **I want** the markers to animate when I change the date,
**so that** I can see one report replace the other.
- **AC1 (exit):** Current pins sink into the surface and current arcs flatten to the ground.
- **AC2 (swap):** The banner, archive chip, country chips, threat HUD and dossier data change
  at the moment the markers are swapped, never before.
- **AC3 (enter):** New pins emerge staggered, highest severity first, and new arcs grow from
  the ground.
- **AC4 (reduced motion):** Under `prefers-reduced-motion: reduce` the swap is instant.
- **AC5 (interaction lock):** Pin hover and click are ignored during a transition, and the
  tooltip is hidden.

### 3. Switch reports reliably
**As a** visitor, **I want** date switching to always land where I clicked last.
- **AC1 (last wins):** Rapid clicks never leave the UI on a stale report; the response for
  the most recent request wins, and an interrupted transition never applies its data.
- **AC2 (failure):** A failed load keeps the current view and logs the error.
- **AC3 (heatmap):** The heatmap toggle works after any number of date changes and is reset
  to off on every report change.
- **AC4 (no-op):** Picking the report already shown does nothing.

### 4. Test history locally with real data
**As a** maintainer, **I want** the production archive in my working copy,
**so that** I can test the history UI without AWS access.
- **AC1 (sync script):** `frontend/scripts/sync-snapshots.sh` (`npm run sync-snapshots`)
  copies every dated report folder from the snapshot bucket. It only reads from S3 and never
  touches `latest/`, which stays managed by the fixture regen hooks.
- **AC2 (validation):** Each local `YYYY-MM-DD/` folder must be a real directory with
  `snapshot.json` and `snapshot.bin`; the `.bin` must have magic `RBMN`, version 2, a size of
  `16 + 28 × count` bytes, and a header date equal to the folder name. Invalid folders are
  reported, left out of the manifest, and make the script exit non-zero.
- **AC3 (manifest):** The script regenerates `frontend/public/snapshots/manifest.json` from
  the valid folders, in the pipeline format (`{"dates": [...]}`, ascending).
  `--manifest-only` does this without AWS.
- **AC4 (committed archive):** The dated folders are committed so the history works in any
  clone. The stale `2026-11-14` symlink is removed.

### 5. Production lists every archived report
**As a** visitor of the deployed site, **I want** the picker to list every published report.
- **AC1:** The production `snapshots/manifest.json` lists every dated report folder in S3
  that has both artifacts and passes validation (adds 2026-11-15 and 2026-11-16).
- **AC2:** The write never drops a date already listed, is preceded by a dry run and a check
  that no state machine execution is running, and requires explicit confirmation.
- **AC3:** `/snapshots/manifest.json` is invalidated on CloudFront after the write.

### 6. Tests and docs
- **AC1 (vitest):** The frontend has `npm test` (vitest). It covers manifest parsing, mode
  detection, snapshot paths, the request sequencer, the easing and scale math, and the
  tween runner.
- **AC2 (archive integrity):** A test checks that every manifest date has a real folder,
  decodes with the TS decoder to the same date, and has matching JSON and binary strike
  ids; that every date-named folder is listed; and that `latest/` decodes.
- **AC3 (docs):** This spec, the steering (`structure.md`, `tech.md`, `data-contract.md`),
  the regen hooks, the README and the attack-globe spec reflect the new behavior.

## Decisions (from the planning conversation)

| Question                | Decision                                                        |
| ----------------------- | --------------------------------------------------------------- |
| Mode indicator          | Archive-only chip + LATEST button. No LIVE badge, no global tint, no URL state. |
| Animation               | Exit then enter (sink, swap, emerge).                           |
| Snapshots               | Reusable sync script; the dated folders are committed.          |
| Tests                   | Add vitest to the frontend.                                     |
| Production manifest     | Fix it in S3 after explicit confirmation.                       |
| `latest/` in the sync   | Not synced; dated folders only.                                 |

## Non-functional requirements

- **Reduced motion:** every new animation (pins, arcs, chip fade) is disabled under
  `prefers-reduced-motion: reduce`.
- **Accessibility:** mode changes are announced (`#report-status`, `role="status"`);
  controls stay keyboard focusable; the active picker date carries `aria-current`.
- **No contract change:** `pipeline/`, `rebellion-core/`, `schema/` and the binary layout v2
  are not modified.
- **Language:** all code, docs and UI copy in English, following
  `steering/narrative-tone.md`.
- **Least privilege:** the sync is read-only on S3; the only production write is the
  confirmed manifest fix plus one CloudFront invalidation.

## Out of scope

Deploying the new frontend to CloudFront, a date in the URL or deep links, a global tint in
archive mode, a LIVE badge, pipeline / Rust / binary layout changes, and changing how the
pipeline writes the manifest.
