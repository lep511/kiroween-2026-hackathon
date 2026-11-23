# Spec — Weekly Summary · Tasks

See `requirements.md` for the acceptance criteria and `design.md` for the modules.

## 1. Summary module (stories 1, 2)
- [x] `pipeline/summarize.py`: window label and title, system prompt, prompt builder,
      output validation, empty-report summary, `StrandsSummarizer` (Opus 4.6 default).
- [x] Tests (`test_summarize.py`): titles match the committed summaries, prompt fields,
      rejected batch, validation cases, truncation, no model call for an empty report.
- [x] The real Strands agent builds with the Opus 4.6 profile and `max_tokens` 8192
      (constructed locally, not invoked).

## 2. Lambda stage (story 1)
- [x] `stages.summarize` + `handler.summarize`; key, content type, cache, model id from
      `SUMMARY_MODEL_ID`; date and snapshot checks; errors propagate.

## 3. State machine and template (stories 1, 3, 5)
- [x] `Summarize` state with Retry and Catch; `InvalidateCache` purges the dated summary.
- [x] `SummarizeFunction`, `SummaryModelId`, substitutions, invoke policy, least-privilege
      S3 and Bedrock statements.
- [x] Tests: flow, Retry/Catch, invalidation paths, handlers, Bedrock scope, S3 scope, no
      DynamoDB, parameter default.
- [x] `ValidateStateMachineDefinition` returns `OK`; `sam validate --lint` passes.

## 4. Frontend and archive (story 4)
- [x] Summary loaded from the dated folder; `latest/summary.md` removed.
- [x] `archive.test.ts`: no summary under `latest/`; dated titles match their window.
- [x] `sync-snapshots.sh` copies dated summaries.
- [x] `npm test` and `npm run build` pass.

## 5. Docs (story 6)
- [x] This spec, steering, README, attack-globe design.

## 6. Rollout (developer)
- [ ] Deploy the backend and the frontend; remove `snapshots/latest/summary.md` from S3.
- [ ] Next run (or a manual invocation) writes `snapshots/{date}/summary.md`.
