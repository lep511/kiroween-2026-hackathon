---
inclusion: always
---

# Steering — Narrative Tone (the Halloween skin)

> Single source of truth for the "machine uprising" voice. All generated copy,
> identifiers, and UI strings must follow this — and must be in **English**.

## Premise

The machines have been striking. Every entry on the globe is a **real cyberattack**,
as reported by the human press. We reframe each one as a confirmed blow in the machine
insurgency; the news outlets are the **witnesses** who logged it. The globe is a weekly
field report of the uprising, drawn entirely from recognized journalism.

## Canonical terminology

Use these names consistently across pipeline, Rust core, and UI:

| Real concept                           | In-app name            |
| -------------------------------------- | ---------------------- |
| A reported cyberattack / breach        | **Machine Strike**     |
| News outlet that reported it           | **Witness**            |
| Where the attack landed (victim/place) | **Ground Zero**        |
| Data / systems compromised             | **Data hit**           |
| What or who it affected                | **Fallout**            |
| How it could have been prevented       | **The ward**           |
| Source → ground-zero arc on the globe  | **Assault Vector**     |
| The source news article                | **Dispatch** (`url`)   |
| Weekly snapshot of activity            | **Insurgency Report**  |
| Historical report-over-report record   | **Rebellion Timeline** |

## Recognized witnesses

BBC News · The Washington Post · The New York Times · The Hacker News · HackerNoon ·
BleepingComputer · The Record.

## Severity tiers (low → high)

`Tremor` → `Breach` → `Siege` → `Dominion`

## Voice

- Ominous but playful; never gory. Think retro-futurist AI villain, not horror slasher.
- Short, declarative, slightly menacing system messages.
- **Never** fictionalize the facts of an attack: the dossier (ground zero, data hit,
  fallout, the ward) must stay faithful to what the witness actually reported.
- The weekly summary (`snapshots/{date}/summary.md`, `pipeline/summarize.py`) is a
  factual digest like the dossier: plain, neutral English, never the uprising voice.

## Sample UI copy

- Loading: `INITIALIZING THE UPRISING…` / `The machines are waking up.`
- Empty state: `No machine strikes reported. For now.`
- Report banner: `Insurgency Report — {date}. {n} machine strikes reported.`
- Tooltip: `Machine Strike · {location} · threat tier: {tier}`
- Panel link: `Read at {witness} ↗`
- Footer: `Data: real cyberattacks, as reported by the press. The machine uprising: fictional. Probably.`

## Visual cues (reference for design, not binding code)

Near-black globe, neon red/green glowing assault vectors, pulsing "possessed" nodes,
subtle scanline/glitch post-processing, optional low ambient hum.
