---
inclusion: always
---

# Product: The Rebellion of the Machines

Web app with an interactive 3D globe. Each point is a real cyberattack reported by a
recognized outlet (BBC News, The Washington Post, The New York Times, The Hacker News,
HackerNoon, BleepingComputer, The Record), placed where it struck and updated weekly (every Thursday), reskinned with an "AI uprising"
narrative. Facts stay faithful to the reporting; only the framing is fiction.

Each incident carries a dossier: ground zero (location), data hit, severity, fallout,
how it could have been prevented ("the ward"), and a link to the article.

## Rules

- Every link must be the concrete article, never a section or generic page
  (`sources.is_concrete_url`, guarded by `pipeline/tests/test_sources.py`).
- The Insurgency Report is a rolling 7-day window (`RECENCY_WINDOW_DAYS` = 7):
  each run starts from the published `snapshot.json`, skips URLs it already holds,
  adds new strikes, drops expired ones, and renumbers ids `1..N`
  (carried strikes first, keeping coordinates). See `pipeline/transform.py`.
- Offline runs use the hand-verified set in `pipeline/fixtures/curated_incidents.json`;
  the cloud run reads each outlet's RSS live. WaPo is wired for live only.

## Category: Frankenstein

Combine seemingly incompatible technologies into one app. Architecture decisions
should lean into unlikely combinations (Rust→WASM in the browser, Python pipeline,
Strands agent on Bedrock, serverless AWS, WebGL globe).