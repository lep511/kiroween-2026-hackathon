---
inclusion: fileMatch
fileMatchPattern: "{schema/**,pipeline/binary.py,pipeline/models.py,rebellion-core/src/decode.rs,frontend/src/snapshot*.ts,frontend/src/theme.ts}"
---

# Data contract invariant

`pipeline/binary.py`, `rebellion-core/src/decode.rs` and `frontend/src/snapshot.ts`
all implement `schema/binary-layout.md` (currently **v2**). Change all three together
and regenerate the committed fixtures in `schema/fixtures/`,
`rebellion-core/tests/fixtures/` and `frontend/public/snapshots/latest/`.

The binary carries only numeric/positional fields plus an `id`. The rich dossier lives
in `snapshot.json` (`schema/snapshot.schema.json`), loaded by
`frontend/src/snapshot-detail.ts` and joined by `id`.

The `witness` enum (outlets, 0–7) is mirrored in `pipeline/models.py`, `decode.rs` and
`frontend/src/theme.ts`; keep them in sync.

## Regenerating fixtures

    .venv/bin/python -m pipeline.cli --out ./frontend/public/snapshots/latest --offline --fresh --date 2026-11-14

Then copy the two files to `schema/fixtures/` and the `.bin` to
`rebellion-core/tests/fixtures/`. Without AWS credentials, use
`transform.run(offline=True, report_date=date(2026, 11, 14), ready_check=<stub>,
extractor=<stub>, previous=None)` plus `transform.write_artifacts(...)`. Output matches
the fixtures except `generated_at`
(`test_offline_run_reproduces_the_committed_snapshot`). At that date the 7-day window
leaves 5 strikes.

The CLI writes only `snapshot.json` and `snapshot.bin` in `--out`. It never touches
`frontend/public/snapshots/manifest.json` or the dated archive folders, so regenerating
the fixture leaves the archive as it was. Afterwards run `cd frontend && npm test`:
`tests/archive.test.ts` decodes every archived report with the TS decoder and checks its
date, folder and JSON/binary ids, and that each run's `total` equals the report's strikes.