# Steering — Structure

> This file tells Kiro where things live and the rules for the repo layout.

## Layout

```
/
├── .kiro/                 # Kiro specs, hooks, steering (REQUIRED — never gitignore)
│   ├── specs/attack-globe/{requirements,design,tasks}.md
│   ├── hooks/*.kiro.hook
│   └── steering/{product,tech,structure,narrative-tone}.md
├── frontend/              # Vite + TypeScript + globe.gl globe UI
├── rebellion-core/        # Rust → WASM crate (snapshot decode + arc aggregation)
├── pipeline/              # Python news pipeline: sources.py + extract.py + geolocate.py
│   └── fixtures/          # curated_incidents.json — committed real incidents (offline)
├── infra/                 # AWS SAM template (Lambda, EventBridge, S3, DynamoDB, CloudFront)
├── schema/                # Shared snapshot contract (JSON Schema + binary layout v2)
├── LICENSE                # MIT
├── README.md
└── CLAUDE.md              # Guidance for Claude Code
```

## Rules

- **Keep runtimes separated.** Rust lives only in `rebellion-core/`, Python only in
  `pipeline/`, TypeScript only in `frontend/`. The only cross-boundary contract is `schema/`.
- **`/.kiro` is sacred.** It must stay at the repo root and must never be added to
  `.gitignore` — doing so can disqualify the Kiroween submission.
- **Generated artifacts are not committed.** `target/`, `pkg/`, and `dist/` are
  gitignored; commit curated/fixture data under a clearly named fixtures path. The
  demo snapshot under `frontend/public/snapshots/latest/` is committed so the globe
  always has data to show.
- **One source of truth for the narrative skin:** see `steering/narrative-tone.md`.
