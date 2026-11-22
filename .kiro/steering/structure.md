---
inclusion: always
---

# Steering — Structure

> This file tells Kiro where things live and the rules for the repo layout.

## Layout

```
/
├── .kiro/                 # Kiro specs, hooks, steering, agents (REQUIRED — never gitignore)
│   ├── agents/aws-expert.json
│   ├── hooks/*.json
│   ├── settings/mcp.json
│   ├── specs/attack-globe/{requirements,design,tasks}.md
│   └── steering/{product,tech,structure,data-contract,narrative-tone,agent-enrichment}.md
├── frontend/              # Vite + TypeScript + globe.gl globe UI
├── rebellion-core/        # Rust → WASM crate (snapshot decode + arc aggregation)
├── pipeline/              # Python news pipeline: sources, agent extraction, Lambda stages
│   └── fixtures/          # curated_incidents.json — committed real incidents (offline)
├── infra/                 # AWS SAM template + statemachine/ (Step Functions ASL)
│   ├── build-lambda.sh    # packages pipeline/ into infra/.build/lambda (run before sam build)
│   └── .build/            # generated Lambda package (gitignored)
├── schema/                # Shared snapshot contract (JSON Schema + binary layout v2)
├── docs/                  # Historical reports (e.g. report-ingestion-news.md)
├── LICENSE                # MIT
├── README.md
└── AGENTS.md              # Guidance for coding agents
```

## Rules

- **Keep runtimes separated.** Rust lives only in `rebellion-core/`, Python only in
  `pipeline/`, TypeScript only in `frontend/`. The only cross-boundary contract is `schema/`.
- **`/.kiro` is sacred.** It must stay at the repo root and must never be added to
  `.gitignore` — doing so can disqualify the Kiroween submission.
- **Generated artifacts are not committed.** `target/`, `pkg/`, `dist/`, and
  `infra/.build/` (the Lambda package built by `infra/build-lambda.sh`) are
  gitignored; commit curated/fixture data under a clearly named fixtures path. The
  demo snapshot under `frontend/public/snapshots/latest/` is committed so the globe
  always has data to show.
- **One source of truth for the narrative skin:** see `steering/narrative-tone.md`.
- **One source of truth for the AI seam:** see `steering/agent-enrichment.md`
  (Strands → Bedrock extraction; mandatory, the sole extractor).
