# AGENTS.md

Guidance for Kiro (IDE, CLI, Web) when working in this repository.
Detailed context lives in `.kiro/steering/`; read it before making changes.

## What this repository is

Kiroween 2026 hackathon submission, "The Rebellion of the Machines".
Category: **Frankenstein**. Deadline: **Friday, December 4, 2026, 2:00 PM Pacific**.
Reference docs at the repo root: `OVERVIEW.md`, `RULES.md` (binding; it wins over
`OVERVIEW.md`), `skills-lock.json` (pins the `hackathon-guide` skill).

## Hard submission constraints (non-negotiable, risk of disqualification)

- The repo root must contain `/.kiro` (specs, hooks, steering). **Never add `/.kiro`
  or its subfolders to `.gitignore`.**
- New work only (Oct 30 – Dec 4, 2026). Disclose any pre-existing code.
- Public GitHub repo with an open-source license file detectable at the top level.
- All submission materials in English.

## Language policy

All project artifacts (code, identifiers, comments, docstrings, docs, tests, commit
messages, logs, errors, config) are written in English. Conversation with the developer
stays in the developer's language. This never affects generated files.

## Judging priorities

Five equal criteria: Potential Impact, Technological Implementation, Design,
Innovation, Presentation. Favor visible, varied Kiro usage (specs, hooks, steering,
MCP, custom agents, property-based testing, powers) and document it in `/.kiro`.

## Working notes

Git repo on `main`. The public GitHub remote is not set up yet.