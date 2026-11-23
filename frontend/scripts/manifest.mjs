// Build the committed report-archive manifest (public/snapshots/manifest.json).
//
//   node scripts/manifest.mjs --out FILE [--source FILE] [--fallback FILE] [DATE...]
//
// DATE... are the dated folders that passed validation (sync-snapshots.sh). The `runs`
// (status and strike total per report, from the Rebellion Timeline) are copied from
// --source, normally the production manifest, keeping only valid entries whose date is
// one of DATE; a folder that --source does not describe keeps its run from --fallback
// (the local manifest). The output uses the separators of Python's json.dumps, as the
// pipeline does, so Assemble and this script never reformat each other's file.

import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const STATUSES = new Set(["published", "rejected"]);

/** Valid `runs` entries of `source` for the given dates, ascending; null if it has none. */
function archiveRuns(dates, source) {
  const runs = source && typeof source === "object" ? source.runs : undefined;
  if (!Array.isArray(runs)) return null;
  const byDate = new Map();
  for (const run of runs) {
    if (!run || typeof run !== "object") continue;
    const { date, status, total } = run;
    if (!dates.has(date) || !STATUSES.has(status)) continue;
    if (!Number.isInteger(total) || total < 0) continue;
    byDate.set(date, { date, status, total });
  }
  return [...byDate.keys()].sort().map((d) => byDate.get(d));
}

/**
 * `{ dates }` for the valid folders (ascending, deduplicated), plus `runs` when a source
 * manifest carries them. `source` (production) wins; `fallback` (the local manifest)
 * keeps the runs of folders that production no longer lists, e.g. after the stack was
 * recreated from scratch.
 */
export function buildArchiveManifest(validDates, source, fallback = null) {
  const dates = [...new Set(validDates)].sort();
  const dateSet = new Set(dates);
  const primary = archiveRuns(dateSet, source);
  const secondary = archiveRuns(dateSet, fallback);
  if (primary === null && secondary === null) return { dates };
  const byDate = new Map();
  for (const run of secondary ?? []) byDate.set(run.date, run);
  for (const run of primary ?? []) byDate.set(run.date, run);
  return { dates, runs: [...byDate.keys()].sort().map((d) => byDate.get(d)) };
}

/** JSON with Python json.dumps separators (", " and ": ") and a trailing newline. */
export function formatManifest(manifest) {
  const format = (value) => {
    if (Array.isArray(value)) return `[${value.map(format).join(", ")}]`;
    if (value !== null && typeof value === "object") {
      const fields = Object.entries(value).map(([k, v]) => `${JSON.stringify(k)}: ${format(v)}`);
      return `{${fields.join(", ")}}`;
    }
    return JSON.stringify(value);
  };
  return `${format(manifest)}\n`;
}

/** The parsed source manifest, or null if it is missing or not JSON. */
export function readSource(path) {
  if (!path) return null;
  let text;
  try {
    text = readFileSync(path, "utf-8");
  } catch {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    process.stderr.write(`[manifest] WARNING: ${path} is not valid JSON; runs not copied\n`);
    return null;
  }
}

function main(argv) {
  let out = null;
  let source = null;
  let fallback = null;
  const dates = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--out") out = argv[++i];
    else if (argv[i] === "--source") source = argv[++i];
    else if (argv[i] === "--fallback") fallback = argv[++i];
    else dates.push(argv[i]);
  }
  if (!out) {
    process.stderr.write(
      "usage: manifest.mjs --out FILE [--source FILE] [--fallback FILE] [DATE...]\n",
    );
    return 2;
  }
  // Read the sources before writing: --source or --fallback may be the --out file.
  const manifest = buildArchiveManifest(dates, readSource(source), readSource(fallback));
  writeFileSync(out, formatManifest(manifest));
  const runs = manifest.runs ? `${manifest.runs.length} run(s)` : "no runs";
  process.stdout.write(`${manifest.dates.length} report(s), ${runs}\n`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = main(process.argv.slice(2));
}
