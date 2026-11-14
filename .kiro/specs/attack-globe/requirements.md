# Spec — Attack Globe · Requirements

Feature: the interactive 3D globe that visualizes the daily "machine uprising".

## Problem

Public threat intelligence (botnet C2 nodes, malicious hosts) is updated constantly but
is hard for non-experts to feel. We want a memorable, daily-refreshed world map that turns
real threat data into a vivid "the machines are rising up" story.

## User stories & acceptance criteria

### 1. See the uprising at a glance
**As a** visitor, **I want** a 3D globe to load with glowing attack points and arcs,
**so that** I immediately grasp today's global machine activity.
- **AC1:** On load, a dark 3D globe renders with a themed loading message, then animates in.
- **AC2:** Awakened Machines appear as points; Assault Vectors appear as arcs between source
  and (approximate) target regions.
- **AC3:** Points/arcs are colored by severity tier (Flatline → Singularity).
- **AC4:** The scene stays interactive (drag to rotate, scroll to zoom) and smooth with at
  least ~5,000 events on a mid-range laptop.

### 2. Daily freshness
**As a** returning visitor, **I want** the data to reflect the latest daily snapshot,
**so that** the map feels alive.
- **AC1:** The globe loads the most recent Insurgency Report (snapshot) at startup.
- **AC2:** A visible banner shows the report date and the count of awakened machines.
- **AC3:** If today's snapshot is missing, the most recent available one is shown with its
  real date (no crash, no blank globe).

### 3. Inspect a machine
**As a** curious visitor, **I want** to hover/click a node, **so that** I can see details.
- **AC1:** Hover shows a tooltip: Awakened Machine · country · threat tier.
- **AC2:** Click opens a small panel with the narrative blurb and non-identifying metadata
  (country, tier, first-seen date, source feed). No raw PII beyond coarse geo/country.

### 4. Travel the Rebellion Timeline (stretch)
**As a** visitor, **I want** to scrub across past days, **so that** I can watch the uprising
escalate.
- **AC1:** A timeline control lets the user pick a past date and reloads that day's snapshot.

### 5. Performance via Rust/WASM
**As a** maintainer, **I want** decoding/aggregation done in Rust/WASM,
**so that** the UI stays responsive.
- **AC1:** The browser fetches a compact binary snapshot and decodes it with the WASM core.
- **AC2:** Aggregation (dedupe, arc building, severity bucketing) happens in Rust, not JS.

## Non-functional requirements

- **Offline dev:** everything above must work against a locally generated sample snapshot
  with no AWS account.
- **Cost:** no always-on server; daily batch + static hosting only.
- **Language:** all UI copy in English, following `steering/narrative-tone.md`.
- **Accessibility:** legible contrast, keyboard-focusable controls, respects
  `prefers-reduced-motion` (dampens glitch/pulse effects).

## Out of scope (v1)

User accounts, live streaming/WebSockets, write operations, mobile-native apps.
