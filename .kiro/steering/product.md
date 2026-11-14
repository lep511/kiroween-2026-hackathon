# Steering — Product

> Steering docs give Kiro persistent context about this project. Keep them short,
> factual, and current. This file answers **what** we are building and **why**.

## Product

**The Rebellion of the Machines** is a web app that opens on an interactive 3D globe.
Each point is a **real cyberattack** — a hospital hit by ransomware, a power grid cut,
a supermarket's fridges sabotaged — reported by a recognized news outlet and placed at
the spot it struck. The map **refreshes daily** and shows the machine strikes reported
over the **last 30 days** (a rolling window: each day adds the new strikes and drops the
ones older than 30 days). Every incident is reskinned with a
fiction layer: the machines are rising up, and these are their strikes.

## The data

Real, verifiable cyberattacks sourced from recognized outlets:
**BBC News, The Washington Post, The New York Times, The Hacker News, HackerNoon.**
For each incident the pipeline extracts a dossier:

- **Ground zero** — where the attack landed (place → country → coordinates).
- **Data hit** — what data/systems were compromised.
- **Severity** — a Tremor → Dominion threat tier.
- **Fallout** — what/who it affected.
- **The ward** — how it could have been prevented (a standard, educational mitigation).
- **Dispatch** — a link to the source article.

## Why it exists

- **Real impact:** it turns genuine, consequential breaches into something anyone can
  grasp at a glance — and pairs each with how it could have been stopped.
- **The hook:** the Halloween "AI uprising" narrative makes dry incident reports visceral.

## Hackathon framing (Kiroween 2026)

- **Category:** Frankenstein — stitch together incompatible technologies into one app.
  Our monster fuses **Rust (WASM in the browser)** + **Python (serverless news pipeline
  orchestrated by Step Functions)** + **a Strands/Bedrock extraction agent** +
  **a WebGL globe**, fed by **real journalism reskinned as an AI uprising**.
- **Deadline:** 2026-12-04.
- **Judging priorities we optimize for:** Potential Impact, Technological Implementation
  (visible, varied Kiro usage), Design, Innovation, Presentation.

## Audience

Security-curious developers, hackathon judges, and anyone who enjoys a beautiful,
slightly ominous data visualization grounded in real events.

## Non-goals

- Not a real-time SOC tool or an authoritative threat feed.
- No user accounts, no write-back, no PII collection. We store only coarse,
  already-public facts from published articles.
