# Steering — Agent Enrichment (Strands → Bedrock)

> Single source of truth for the **optional AI seam**: a Strands Agents agent on Amazon
> Bedrock that extracts incident dossiers. This file tells Kiro **how** to work on
> `pipeline/agent_extract.py` and what invariants must never break. See also
> `steering/tech.md` (stack) and `steering/narrative-tone.md` (voice).

## What it is

On top of the deterministic heuristic extractor (`pipeline/extract.py`), an **opt-in**
[Strands Agents](https://strandsagents.com) agent reads one reported cyberattack (headline
+ reported summary from a named outlet) and returns a **structured incident dossier** via
LLM structured output. It classifies the attack, writes a faithful summary, and completes
every dossier field. This is the project's fourth Frankenstein seam: an LLM agent fused
into a pipeline that is otherwise deterministic Python + Rust/WASM + WebGL.

## Non-negotiable invariants

- **Opt-in only.** The agent runs *only* when enabled (`--use-agent` / `USE_AGENT=1`).
  The default pipeline, the offline snapshot, the committed fixtures, and the whole test
  suite stay **deterministic** and need no model, network, or AWS account.
- **Precedence: curated `overrides` > agent > heuristic.** Hand-verified reporting always
  wins; the agent only fills fields a curated incident left blank; the heuristic is the
  final fallback. A fully-curated incident skips the agent call entirely.
- **Graceful degradation.** Any failure (missing SDK, no Bedrock credentials, a model or
  validation error) makes `StrandsExtractor.enrich()` return `{}` so the heuristic takes
  over. It must never raise and never abort the batch.
- **No new required dependencies.** `strands`, `pydantic`, and `boto3` are imported
  **lazily**, inside the functions that need them. Importing `agent_extract` with none of
  them installed must still succeed (the test suite relies on this).
- **English only.** Every field, comment, prompt, and instruction is in English, per
  `steering/tech.md`. The agent must stay faithful to the reporting — the machine-uprising
  framing is a cosmetic skin applied elsewhere, never in the extracted facts.

## Model configuration

- Default model: **Claude Opus 4.8** on Bedrock, pinned in the `DEFAULT_MODEL_ID` constant
  (`us.anthropic.claude-opus-4-8` — the US cross-region inference profile; needs a US
  region such as `us-east-1`/`us-west-2`).
- Change the model in one of three ways (highest precedence first):
  1. CLI flag `--agent-model <id>`
  2. Env var `AGENT_MODEL_ID` (local, or the Lambda / SAM `AgentModelId` parameter)
  3. Edit the `DEFAULT_MODEL_ID` constant
- **No temperature** (or other sampling params) is set — left to the model/Bedrock
  defaults. Region is resolved from the AWS environment unless `--agent-region` /
  `AGENT_REGION` is given.

## Structured-output contract

The agent returns a Pydantic `StrikeDossier` (built lazily in `_dossier_model()`), mapped
to an override-shaped dict by `_to_overrides()` with sanitization:

| Field            | Constraint                                                        |
| ---------------- | ----------------------------------------------------------------- |
| `attack_type`    | `Literal` of `extract.ATTACK_TYPES` (`"unknown"` → drop, heuristic decides) |
| `severity`       | `Literal` of the `Severity` tiers (`tremor`/`breach`/`siege`/`dominion`)    |
| `summary`        | one or two neutral, factual sentences                             |
| `data_affected`  | data/systems compromised                                          |
| `impact`         | who/what was affected and scale of the fallout                    |
| `prevention`     | one concrete, actionable mitigation ("the ward")                  |
| `location`       | human-readable ground zero                                        |
| `country`        | ISO-3166 alpha-2, uppercased; placeholders (`ZZ`/`XX`) → drop     |
| `origin_country` | ISO-3166 alpha-2 or `null` (unattributed → arc collapses)         |

Keep the taxonomy in sync: `agent_extract.ATTACK_TYPES` is derived from
`extract._ATTACK_SIGNATURES`, and `SEVERITY_LABELS` from the `Severity` enum — never
hard-code a divergent list.

## Wiring

- `extract.build_strike(article, idx, geo, extractor=None)` — applies precedence + skip guard.
- `transform.build_report(..., extractor=None)` and `transform.run(..., use_agent, agent_model, agent_region)`.
- `cli.py` — `--use-agent`, `--agent-model`, `--agent-region`.
- `handler.py` — `USE_AGENT`, `AGENT_MODEL_ID`, `AGENT_REGION` env vars.
- `infra/template.yaml` — `UseAgent`/`AgentModelId`/`AgentRegion` params; Bedrock
  `InvokeModel`/`Converse` IAM is granted **only** under the `EnableAgent` condition.

## Testing

- Unit tests inject a **stub agent** (duck-typed `structured_output`) — no network, no
  Bedrock, no required deps. Cover mapping/sanitization, precedence, skip guard, and
  degradation.
- The real Pydantic schema test is gated on `pydantic` being importable (`pytest.skipif`).
- Live Bedrock calls are **never** made in tests; verify the live path manually.

```bash
# Local, deterministic (default)
python -m pipeline.cli --out ./sample --offline

# With the agent (needs AWS credentials + Bedrock model access)
pip install -e '.[agent]'
python -m pipeline.cli --out ./sample --use-agent            # Opus 4.8
python -m pipeline.cli --out ./sample --use-agent --agent-model global.anthropic.claude-opus-4-8
```
