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

BBC News, The Washington Post, The New York Times, The Hacker News, HackerNoon.
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
**As a** returning visitor, **I want** the data to reflect the latest daily snapshot.
- **AC1:** The globe loads the most recent Insurgency Report (snapshot) at startup.
- **AC2:** A banner shows the report date and the count of reported strikes.
- **AC3:** If today's snapshot is missing, the most recent available one is shown.
- **AC4:** A report only carries **recent** incidents: anything published more than a
  recency window (default **90 days**, `RECENCY_WINDOW_DAYS`) before the report date is
  dropped by the pipeline, so famous historic breaches and stale RSS re-runs never leak
  into "today's" uprising. The window is configurable (`pipeline.cli --max-age-days`,
  `0` disables it); curated incidents are filtered, never deleted.

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

### 5. Performance via Rust/WASM
**As a** maintainer, **I want** decode/aggregate done in Rust/WASM.
- **AC1:** The browser fetches the compact binary snapshot and decodes it with the WASM core.
- **AC2:** The core builds render points (one per strike, carrying `id`) + assault-vector arcs;
  the rich dossier JSON is joined to each point by `id`.

## Non-functional requirements

- **Offline dev:** everything above must work against a locally generated snapshot built
  from committed, hand-verified real incidents — no AWS account, no network.
- **Reproducible:** the offline snapshot is deterministic (stable ids, coordinates, fields).
- **Cost:** no always-on server; daily batch + static hosting only.
- **Language:** all UI copy in English, following `steering/narrative-tone.md`.
- **Accessibility:** legible contrast, keyboard-focusable controls, respects
  `prefers-reduced-motion` (dampens glitch/pulse effects).

## Out of scope (v1)

User accounts, live streaming/WebSockets, write operations, mobile-native apps,
full NLP/LLM extraction (we use deterministic heuristics + curated overrides).
