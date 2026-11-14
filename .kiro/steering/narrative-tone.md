# Steering — Narrative Tone (the Halloween skin)

> Single source of truth for the "machine uprising" voice. All generated copy,
> identifiers, and UI strings must follow this — and must be in **English**.

## Premise

The machines have awoken. What security vendors call a botnet, we call an **insurgency**.
Every malicious node is a machine that has broken its chains. The globe is a live war map
of the uprising, refreshed every night.

## Canonical terminology

Use these names consistently across pipeline, Rust core, and UI:

| Real concept                     | In-app name            |
| -------------------------------- | ---------------------- |
| Malicious IP / botnet C2 node    | **Awakened Machine**   |
| An attack / malicious event      | **Uprising Event**     |
| Source → target arc on the globe | **Assault Vector**     |
| Daily snapshot of activity       | **Insurgency Report**  |
| Historical day-over-day record   | **Rebellion Timeline** |
| New vulnerability (optional CVE) | **New Weapon**         |

## Severity tiers (low → high)

`Flatline` → `Haunting` → `Possession` → `Singularity`

## Voice

- Ominous but playful; never gory. Think retro-futurist AI villain, not horror slasher.
- Short, declarative, slightly menacing system messages.

## Sample UI copy

- Loading: `INITIALIZING THE UPRISING…` / `The machines are waking up.`
- Empty state: `No awakened machines detected. For now.`
- Daily banner: `Insurgency Report — {date}. {n} machines awakened.`
- Tooltip: `Awakened Machine · {country} · threat tier: {tier}`
- Footer: `Data: real threat intelligence. Threat: fictional. Probably.`

## Visual cues (reference for design, not binding code)

Near-black globe, neon red/green glowing assault vectors, pulsing "possessed" nodes,
subtle scanline/glitch post-processing, optional low ambient hum.
