# Report: Testing the Ingestion of Additional News Articles with the Existing Codebase

**Test date:** 2026-11-14 (report date in the system).  
**Scope:** Read-only testing. No code or version-controlled fixtures were modified. All output files were written to `/tmp`.

## What Was Tested

1. **Baseline:** `pytest pipeline/tests` passes completely.
2. **Live pipeline, as currently implemented:** `python -m pipeline.cli --out /tmp/live_run` (RSS feeds from all 5 sources).
3. **Live pipeline, without per-feed limit:** The same `sources.parse_rss` parser was used with `limit=100` instead of the default `limit=8` used by `fetch_all`. Then `transform.build_report` was executed.
4. **Curated pipeline:** `curated_incidents.json` was copied to a temporary file, and 2 real news articles from The Hacker News RSS feed (Operation Endgame and SilentAir) were added. The copy was then loaded using `sources.load_curated`.
5. **Binary round trip:** `binary.encode` followed by `binary.decode` was executed against the expanded dataset.

## Results

| Scenario | Input Articles | Strikes in Report | Observation |
|---|---:|---:|---|
| Offline (current fixture) | 7 | 6 | 1 excluded by the 90-day window (`2020-12-13`) |
| Fixture + 2 additional articles | 9 | 8 | The curated pipeline accepts new entries without code changes |
| Live, actual `fetch_all` | 18 | 18 | Limit of 8 articles per feed |
| Live, without limit (`limit=100`) | 59 | 59 | Full pool currently available |

Source breakdown, using the complete pool of 59 articles:

- The Hacker News: 44
- HackerNoon: 13
- BBC: 1
- NYT: 1
- The Washington Post: 0

Severity distribution across the 59-article pool: tremor 15, breach 14, siege 14, dominion 16.

The binary round trip works with 59 strikes: all 59 are successfully decoded, and their IDs match.

## Findings

### 1. The limit of 8 articles per feed restricts ingestion (critical for "more news")

`fetch_all` calls `parse_rss(witness, bytes)` without passing a `limit` argument, so the default value of 8 is used. The feeds contain between 13 and 44 valid cybersecurity-related articles. This limit excludes 66% of the currently available pool.

To ingest more articles, this call would need to be modified (or `limit` exposed as a parameter in `fetch_all`). I did not make this change because it would alter the pipeline's behavior.

### 2. 83% of strikes have no country assigned (ZZ)

In the 59-article pool, 49 strikes have `country = "ZZ"`. The extractor cannot identify a country in either the headline or the summary.

`geolocate.Geolocator` returns `(0.0, 0.0)` for unknown countries (`_DEFAULT`), meaning these strikes are plotted on "Null Island" (Gulf of Guinea), with only ±0.6° of jitter. On the globe, they appear as attacks located in West Africa.

This undermines the product's core promise: "placed where it struck."

Possible options:
- Exclude strikes from the globe when no country is available.
- Display them in a separate "Unknown Location" layer.

This requires your decision.

### 3. Non-attack articles are being ingested (filter false positives)

`_looks_like_cyber` searches for broad substrings such as `"cyber"`, `"hack"`, `"attack"`, `"vulnerabilit"`, and `"ransomware"`. The following examples pass the filter:

- "Tech Life" (BBC): a podcast. It passes because `is_concrete_url` accepts any final URL segment containing digits (`/sounds/play/w3ct8jys`), even when the preceding segment is `sounds`.
- "The HackerNoon Newsletter: ..." (3 cases): newsletters, not incidents.
- "Webinar: See How Identity Blind Spots Put Your SOC at Risk...": promotional material.
- "Microsoft Says Outage Disrupting Outlook Is Improving" (NYT): an outage, not a confirmed attack.
- "What Is Web Cache Deception and How Can Attackers Exploit It?" (HackerNoon): an explanatory article, not an incident.
- "How Visual Programming Could Solve Three Major AI Cybersecurity Problems": an opinion piece.

I estimate there are approximately 8 false positives among the 59 articles, meaning roughly 14% of the pool should not be displayed as strikes.

### 4. The feeds degrade gracefully

- The "concrete URL" rule works: no section pages were ingested.
- The Washington Post: 13 valid items were found in the XML, but 0 passed the filter. None contain cybersecurity-related keywords; they are business news about Nvidia and Microsoft. The filter is working as intended, but this feed contributes almost no relevant incidents.
- HackerNoon's regex fallback worked (13 items), confirming that the lenient parser is necessary.

### 5. The curated pipeline is the natural extension point

Adding verified articles to `curated_incidents.json` worked without code changes. `load_curated` validates URLs using `is_concrete_url`, while `build_report` and the binary pipeline process the resulting data successfully.

This is the recommended approach for expanding the fixture through manual verification, which is the project's established rule.

### 6. Other design observations

- The 90-day window correctly excluded the curated article from 2020.
- Feed dates range from 2026-10-27 to 2026-11-14, so the live pool qualifies as "recent" under the current rule.
- BBC and NYT summaries sometimes contain the same text as the `impact` field, resulting in duplicated content in the panel.

## Recommendations (Not Implemented)

1. Pass `limit` from `fetch_all` (or increase it) to ingest the complete available pool.
2. Decide how to handle `ZZ` strikes: exclude them or mark them as "Unknown Location."
3. Exclude newsletters, webinars, podcasts, and explanatory articles. A title-based pattern or rejecting `/sounds/` in `is_concrete_url` would cover the cases observed.
4. Improve country detection in `extract.py` by using actor-based or source-based attribution when the headline does not explicitly mention a location.
5. Keep the curated fixture as the source of truth for the demo. Live ingestion is already useful, but the filters above should be improved before it is published.

## Repository Status

- `pytest pipeline/tests`: passes.
- No code, fixtures, or version-controlled snapshots were modified.
- Test output files: `/tmp/live_run`, `/tmp/offline_run`, and a temporary curated file under `/tmp`.
- This report is the only new file in the repository. It can be removed if it should not be version-controlled.
