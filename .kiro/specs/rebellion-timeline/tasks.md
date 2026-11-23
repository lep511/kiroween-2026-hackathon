# Spec — Rebellion Timeline · Tasks

Ordered, checkable implementation tasks. Each should leave the repo runnable.
See `requirements.md` for the acceptance criteria and `design.md` for the modules.

## 0. Spec
- [x] Write this spec (`requirements.md`, `design.md`, `tasks.md`) in English.

## 1. Test harness, sync script, and the local archive (story 4, story 6 AC1-AC2)
- [x] Add vitest (`npm test`), `vitest.config.ts`, and `frontend/tests/`.
- [x] `tests/archive.test.ts` written first; failed on the stale `2026-11-14` symlink
      (it decoded as 2026-11-19).
- [x] `frontend/scripts/sync-snapshots.sh` (sync and `--manifest-only`) +
      `npm run sync-snapshots`.
- [x] Remove the `2026-11-14` symlink; sync the production archive (5 reports, all valid).
- Test: `npm test` and `npm run build` green.
- Demo: the picker lists 2026-11-19, 11-17, 11-16, 11-15, 11-05; each loads its own data.

## 2. Latest vs archive mode and the archive UI (story 1)
- [x] `history.ts` (`parseManifest`, `reportMode`, `snapshotBase`) with tests first.
- [x] `latestDate` from the initial `latest/` batch; `setHistoryUi`; picker highlight on
      the initial load; picking the shown date is a no-op.
- [x] `#banner-archive` chip, `#report-status` live region, scoped `[hidden]` rules, copy
      in `theme.ts`.
- Demo: startup banner unchanged; 2026-11-17 shows `ARCHIVE · Tue, Nov 17, 2026` + LATEST;
  LATEST and picking 2026-11-19 return to latest mode.

## 3. Reliable switching (story 3)
- [x] `createSequencer` with tests first.
- [x] Split `loadReport` into `fetchReport` + `applyReport`; `showReport` drops stale
      responses and keeps the view on failure.
- [x] `wireEffectToggles` wired once; heatmap reset on every report change.
- Demo: 4 quick clicks end on the last date; heatmap works after switches; a blocked
  `snapshot.bin` keeps the current view.

## 4. Pin exit and enter animation (story 2 AC1-AC3)
- [x] `transition.ts` with tests (easing, scales, stagger, order, `runTween`).
- [x] `GlobeView.transitionTo` (pins sink, swap, emerge staggered); initial load = enter only.
- Demo: 2026-11-19 → 2026-11-05: pins sink, banner/chip/country chips change at the swap,
  new pins emerge with Dominion first.

## 5. Arc exit, interruption, interaction lock, reduced motion (story 2 AC4-AC5, story 3 AC1)
- [x] Arcs flatten on exit and grow on enter.
- [x] A new transition cancels the running one; its exit starts from the current scales.
- [x] Pin hover/click ignored during a transition; tooltip hidden.
- [x] Reduced motion: instant swap.
- Browser checklist (`npm run dev`; verified in headless Chromium with SwiftShader):
  1. [x] Arcs flatten, then the new ones grow.
  2. [x] Switching mid-animation leaves no ghost pins or arcs and ends on the last date.
  3. [x] No pin tooltip during a transition.
  4. [x] With `prefers-reduced-motion: reduce` emulated, the swap is instant.
  5. [x] Opening a strike after a switch shows the dossier of the new report.

## 6. Production manifest fix (story 5)
> Superseded by `../timeline-index/`: `--publish-manifest` was removed and the manifest
> is now built from the DynamoDB timeline (`pipeline.timeline_admin rebuild-manifest`).

- [x] `--publish-manifest [--dry-run] [--yes]` in the sync script.
- [x] Dry run: adds 2026-11-15 and 2026-11-16, drops nothing.
- [x] Real write after explicit confirmation from the developer, then CloudFront
      invalidation of `/snapshots/manifest.json` (invalidation `I50UYK29M6SSFBSI94X0E13XPE`
      on `ELSZBF42YYFZN`, completed).
- Demo: `curl -s https://d28ltls6g6c7d1.cloudfront.net/snapshots/manifest.json` lists all
  5 dates.

## 7. Docs and final validation (story 6 AC3)
- [x] Steering (`structure.md`, `tech.md`, `data-contract.md`), regen hooks, README,
      attack-globe spec links.
- [x] `npm test`, `npm run build` (TS fallback only: no Rust toolchain in this env),
      `pytest pipeline/tests -q`.
