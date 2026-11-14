# Spec — Attack Globe · Design

## Architecture

```
          EventBridge (daily cron)
                   │
                   ▼
        ┌──────────────────────┐      threat feeds (abuse.ch Feodo/URLhaus)
        │  Python Lambda        │◄──── + GeoLite2 offline geolocation
        │  (pipeline)           │
        │  fetch→geo→skin→emit  │
        └──────────┬───────────┘
          writes   │          writes summary row
     snapshot.json │  snapshot.bin        │
                   ▼                      ▼
                ┌──────┐             ┌──────────┐
                │  S3  │             │ DynamoDB │  (Rebellion Timeline)
                └──┬───┘             └────┬─────┘
       CloudFront  │                      │ (optional read Lambda)
                   ▼                      ▼
        ┌─────────────────────────────────────────┐
        │  Frontend (static, Vite + globe.gl)       │
        │   fetch snapshot.bin ──► rebellion-core   │
        │   (Rust/WASM: decode + aggregate) ──►     │
        │   render arcs/points on 3D globe          │
        └─────────────────────────────────────────┘
```

## Data model

Internal record produced by the pipeline (one per Awakened Machine / Uprising Event):

| Field          | Type          | Notes                                              |
| -------------- | ------------- | -------------------------------------------------- |
| `lat` / `lon`  | f32           | Source location (from GeoLite2).                   |
| `tgt_lat/lon`  | f32           | Assault Vector target (assigned command center).   |
| `severity`     | u8 (0–3)      | 0 Flatline · 1 Haunting · 2 Possession · 3 Singularity |
| `source`       | u8 enum       | 0 Feodo · 1 URLhaus · 2 other                      |
| `country`      | 2 ASCII bytes | ISO-3166 alpha-2 (coarse, non-PII).                |
| `first_seen`   | u32           | Days since Unix epoch.                             |

Severity is derived from feed signals (e.g. confidence/online status, malware family count).
Targets are drawn from a small fixed set of "command centers" (major hubs) so Assault Vectors
have somewhere to point without inventing victim PII.

## Snapshot contract (`schema/`)

Two artifacts per day, same logical content:
- `snapshot.json` — human-readable, for debugging, docs, and the no-WASM fallback.
- `snapshot.bin` — compact binary decoded by the Rust/WASM core. Layout (little-endian):

```
Header:
  magic       4 bytes  = "RBMN"
  version     u8       = 1
  _pad        3 bytes  = 0
  date_days   u32      (report date, days since Unix epoch)
  count       u32      (number of event records)
Records (count × 24 bytes):
  lat f32 | lon f32 | tgt_lat f32 | tgt_lon f32 |
  severity u8 | source u8 | country[2] u8 | first_seen u32
```

JSON Schema for `snapshot.json` lives at `schema/snapshot.schema.json`; the binary layout
is documented at `schema/binary-layout.md`. Both are the single contract shared by
`pipeline/` and `rebellion-core/`.

## Rust/WASM core (`rebellion-core`)

- `decode_snapshot(bytes) -> Snapshot` — validate magic/version, parse header + records.
- `aggregate(snapshot, opts) -> RenderBatch` — dedupe by geo cell, build arcs (source→target),
  bucket by severity, cap/level-of-detail for large days. Returns flat typed arrays friendly
  to globe.gl (points[], arcs[], colors by tier).
- Exposed to JS via `wasm-bindgen`; returns structures serialized with `serde`.

## Frontend

- `globe.gl` instance with a dark earth texture, custom arc/point colors per severity, pulse
  shader for `Possession`/`Singularity`, scanline/glitch post-processing (disabled under
  `prefers-reduced-motion`).
- Startup: themed loader → fetch `snapshot.bin` → `rebellion-core.decode + aggregate` →
  feed arrays to globe.gl → reveal with the Insurgency Report banner.
- Tooltip + detail panel per node; optional timeline scrubber (reads history JSON/DynamoDB).

## Error handling

- Missing today's snapshot → fall back to latest available, show its real date.
- Bad/short binary → WASM returns a typed error; frontend falls back to `snapshot.json`.
- Feed/geolocation failures in the pipeline → skip the record, log, continue (never fail the
  whole day for one bad row).

## Narrative skin

All names and copy follow `steering/narrative-tone.md` (Awakened Machine, Assault Vector,
Insurgency Report, severity tiers, etc.).
