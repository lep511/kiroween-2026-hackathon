# Spec — Attack Globe · Design

## Architecture

```
          EventBridge (daily cron)
                   │
                   ▼
        ┌──────────────────────┐   news RSS: BBC · WaPo · NYT ·
        │  Python Lambda        │◄── The Hacker News · HackerNoon
        │  (pipeline)           │   (offline: curated real incidents)
        │  fetch→extract→skin   │
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
        │   render arcs/points on 3D globe;         │
        │   join snapshot.json dossier by `id`      │
        └─────────────────────────────────────────┘
```

## Pipeline stages

1. **`sources.py`** — fetch & normalize RSS from six outlets into `RawArticle`s; keep only
   items that read like a cyber incident. Offline mode reads `fixtures/curated_incidents.json`
   (hand-verified real incidents, each able to pin fields via `overrides`).
2. **`extract.py`** — deterministic heuristics turn headline+summary into a dossier:
   attack type → a standard mitigation ("the ward"), data/sector detection, scale/fallout,
   severity tier, and attacker attribution (e.g. "North Korean" → origin KP). Overrides win.
   **`agent_extract.py`** (optional) — a Strands Agent on Amazon Bedrock classifies the
   incident and completes the dossier via LLM structured output. Opt-in (`--use-agent` /
   `USE_AGENT=1`); precedence is curated overrides > agent > heuristic, and it degrades
   to the heuristic on any failure so offline/test runs stay deterministic.
3. **`geolocate.py`** — resolve a country name/demonym in the text → ISO code → a
   representative coordinate (with deterministic jitter so same-country strikes don't stack).
4. **`binary.py` / `transform.py`** — emit the two artifacts.

## Data model

One record per Machine Strike (reported cyberattack):

| Field            | Type          | Notes                                                  |
| ---------------- | ------------- | ------------------------------------------------------ |
| `id`             | u32           | join key between `.bin` and the JSON dossier.          |
| `lat` / `lon`    | f32           | ground zero (where the attack landed).                 |
| `origin_lat/lon` | f32           | attributed attacker origin (== ground zero if unknown).|
| `severity`       | u8 (0–3)      | 0 Tremor · 1 Breach · 2 Siege · 3 Dominion |
| `witness`        | u8 (0–5)      | BBC · WaPo · NYT · The Hacker News · HackerNoon · other |
| `country`        | 2 ASCII bytes | ISO-3166 alpha-2 of ground zero.                       |
| `published`      | u32           | article publication date, days since Unix epoch.       |
| _dossier (JSON)_ | strings       | title, location, data_affected, impact, prevention, summary, url, attack_type |

## Snapshot contract (`schema/`)

Two artifacts per day:
- `snapshot.json` — human-readable; carries the **full dossier** per strike (and is the
  no-WASM fallback / join source for the detail panel).
- `snapshot.bin` — compact binary (v2) decoded by the Rust/WASM core. Layout (little-endian):

```
Header:
  magic       4 bytes  = "RBMN"
  version     u8       = 2
  _pad        3 bytes  = 0
  date_days   u32      (report date, days since Unix epoch)
  count       u32      (number of strike records)
Records (count × 28 bytes):
  id u32 | lat f32 | lon f32 | origin_lat f32 | origin_lon f32 |
  severity u8 | witness u8 | country[2] u8 | published u32
```

JSON Schema lives at `schema/snapshot.schema.json`; the binary layout at
`schema/binary-layout.md`. Both are the single contract shared by `pipeline/` and
`rebellion-core/`.

## Rust/WASM core (`rebellion-core`)

- `decode(bytes) -> Snapshot` — validate magic/version=2, parse header + 28-byte records.
- `aggregate(snapshot, opts) -> RenderBatch` — one point per strike (carrying `id` + witness),
  build arcs origin→ground zero, bucket by severity, LOD cap. Flat typed arrays for globe.gl.
- Exposed to JS via `wasm-bindgen`; structures serialized with `serde`.

## Frontend

- `globe.gl` with a dark earth, custom arc/point colors per severity, pulse for high tiers,
  scanline/glitch post-processing (off under `prefers-reduced-motion`).
- Startup: themed loader → fetch `snapshot.bin` + `snapshot.json` in parallel →
  `rebellion-core.decode + aggregate` → render → join dossiers by `id` for the detail panel.
- Tooltip (location + tier) + dossier panel (data hit, fallout, the ward, article link).

## Error handling

- Missing today's snapshot → fall back to the latest available.
- Bad/short/wrong-version binary → WASM returns a typed error; frontend falls back to TS decoder.
- A failed feed or a bad row in the pipeline → skip it, log, continue (never fail the day).

## Narrative skin

All names and copy follow `steering/narrative-tone.md` (Machine Strike, Witness, Ground Zero,
Data hit, Fallout, The ward, severity tiers, …). Facts stay faithful to the reporting.
