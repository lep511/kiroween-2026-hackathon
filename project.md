# About the Project

## Inspiration

It started with a question: what would it look like if you could *see* the cyberattacks happening around the world, all at once, on a globe?

I kept reading about major breaches and ransomware campaigns in the news. Hospitals shut down, power grids disrupted, millions of records stolen. Each one felt isolated, like a one-off headline. But when you step back and look at the pattern, it feels less like random crime and more like... a coordinated uprising. That image stuck with me: machines turning against us, one strike at a time.

So I thought, what if I built that? A living map of real cyberattacks, sourced from actual news reporting, but told through the lens of a fictional machine rebellion. The facts stay real. The framing becomes a story. And suddenly, dry security news turns into something people actually want to explore.

## What it does

The Rebellion of the Machines is an interactive 3D globe that maps real cyberattacks from the past week. Every Thursday, a serverless pipeline reads news from seven major outlets (BBC, The Washington Post, The New York Times, The Hacker News, HackerNoon, BleepingComputer, and The Record) and an AI agent identifies which stories are actual cyberattacks and extracts the key details.

Each attack shows up as a glowing point on the globe, placed at the real location where it happened, color-coded by severity (from green "Tremors" to red "Dominion" level events), with animated arcs connecting origins to targets. Click any point and you get the full dossier: what happened, where, how bad it was, what data was hit, and most importantly, how it could have been prevented. Every dossier links back to the original article so you can read the real reporting yourself.

You can browse past weeks through the report picker, and each week comes with an AI-written summary highlighting the biggest incidents and common defenses. The whole thing runs without any always-on servers. It's a static snapshot that refreshes once a week.

## How we built it

The project has three main layers, each in its own language:

**The pipeline (Python)** runs weekly on AWS. It reads RSS feeds from seven news outlets, hands each article to an AI agent on Amazon Bedrock (built with Strands Agents) that classifies it as a cyberattack (or not) and extracts structured fields: location, severity, what data was affected, the fallout, and how it could have been prevented. The pipeline then geolocates each incident, encodes everything into a compact binary format plus a JSON dossier, and writes both to S3. A Step Functions state machine orchestrates the whole flow, and DynamoDB keeps a timeline of every run.

**The core (Rust, compiled to WebAssembly)** lives in the browser. It decodes the binary snapshot and builds the render buffers (point positions, arc geometries, severity colors) all at near-native speed without blocking the UI thread.

**The frontend (TypeScript)** uses globe.gl (built on three.js) to render a 3D globe with the decoded data. Click a point and you get the full dossier from the JSON file, joined by ID. The report picker lets you browse past weeks, and each week has an AI-generated summary of what happened.

Kiro shaped the development process from day one. I wrote specs before code, used steering documents to keep the AI focused on the right stack and narrative tone, and set up agent hooks that automatically ran tests whenever I saved a Rust or Python file. That last one caught several binary format mismatches before they became real bugs.

## Challenges we ran into

**The rolling window logic was deceptively tricky.** Each weekly report covers the last 7 days, but it also has to merge with the previous report, keeping existing strikes, dropping expired ones, adding new ones, and renumbering IDs without breaking the binary/JSON join. Getting all the edge cases right (empty days, rejected batches, overlapping runs, stale manifests) took more iteration than I'd like to admit.

**Making the AI agent reliable was a process, not a moment.** The first version of the extraction agent returned messy, inconsistent results. I went through several rounds of prompt engineering, schema tightening, and adding validation layers before it was stable enough to trust. Even now, the pipeline has fallbacks: a discard threshold, curated overrides for hand-verified incidents, and a rule that articles the agent can't classify just get dropped rather than guessed at.

**Keeping three languages in sync.** The binary format is implemented in Python (encoder), Rust (decoder), and TypeScript (fallback decoder). A change in one means a change in all three, plus regenerating test fixtures. One misaligned byte offset and the whole globe renders garbage.

**The narrative layer.** Finding the right tone, scary enough to be fun but respectful enough not to trivialize real incidents, took some trial and error. The steering document for narrative tone became one of the most-edited files in the repo. Every label, tier name, and UI string went through it.

## Accomplishments that we're proud of

**The Frankenstein seam actually works.** Rust compiled to WebAssembly decoding a binary format written by Python, rendered on a WebGL globe orchestrated by TypeScript, and it all fits together cleanly. The binary snapshot is only 28 bytes per strike, so the whole weekly report loads almost instantly.

**The AI agent is genuinely useful.** It reads a raw news article and reliably extracts structured incident data (location, severity tier, affected data, prevention advice) without hallucinating. Getting there took work, but the result is a pipeline that can process dozens of articles per run with minimal manual intervention.

**The report history and weekly summaries.** Being able to browse past weeks and read a written digest of each one makes this feel like a living product, not a demo. The timeline accumulates over time, so the globe tells a bigger story with every week that passes.

**Spec-driven development paid off.** Writing the binary layout spec before any code meant the Python encoder and Rust decoder were built independently and worked together on the first try. When the format had to change from v1 to v2, the spec guided every file that needed updating. Kiro's hooks caught mismatches automatically on save.

## What we learned

**Cross-language data contracts are hard.** Getting a Python encoder and a Rust decoder to agree on a byte-level binary format, with no shared type system, was trickier than expected. Writing the spec first and treating it as the single source of truth was the only thing that made it manageable.

**AI agents need guardrails, not freedom.** Early on, the agent was too creative. It hallucinated locations, invented severity levels, and classified opinion pieces as incidents. The lesson: give the agent a tight output schema, validate everything, and always have a way to discard bad results rather than guessing.

**WebAssembly is worth the setup cost.** It sounds intimidating, but once the build pipeline is in place it just works. The performance difference over the pure-TypeScript fallback is real, and having both paths means the app degrades gracefully.

**Serverless orchestration fits batch jobs surprisingly well.** Step Functions turned out to be a natural fit for the weekly pipeline: fetch, fan out, assemble, summarize. No servers to maintain, built-in retries, and the state machine definition is the documentation.

## What's next for The Rebellion of the Machines

**More sources.** The pipeline already supports seven outlets, but adding more feeds (Krebs on Security, Ars Technica, CISA advisories) would give the globe broader coverage and make the weekly reports richer.

**Real-time updates.** Right now the globe refreshes once a week. Moving to daily or even near-real-time updates, triggered by new articles rather than a schedule, would make the map feel truly alive.

**User interaction.** Letting visitors filter by severity, region, or attack type, and adding a search bar to find specific incidents, would turn the globe from a visualization into a research tool.

**Historical archive.** Building out a deeper timeline, months or even a full year of reports, would reveal seasonal patterns and long-term trends in cyberattacks. The infrastructure already supports it; it just needs time to accumulate.

**Notifications.** An optional email or webhook alert when a new high-severity strike lands on the globe. If the machines are rising, you'd want to know about it.
