// Integrity of the committed report archive under public/snapshots/.
// Each dated folder is a read-only copy of a published S3 report (see
// scripts/sync-snapshots.sh); the manifest must list exactly the valid folders, and its
// `runs` (when present) must describe those reports.

import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildRenderBatchJS } from "../src/snapshot";

const SNAPSHOTS = join(dirname(fileURLToPath(import.meta.url)), "../public/snapshots");
const DATE_NAME = /^\d{4}-\d{2}-\d{2}$/;

function readBin(path: string): ArrayBuffer {
  const b = readFileSync(path);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
}

function readJson(path: string): { date: string; strikes: { id: number }[] } {
  return JSON.parse(readFileSync(path, "utf-8"));
}

const manifest = JSON.parse(readFileSync(join(SNAPSHOTS, "manifest.json"), "utf-8")) as {
  dates: string[];
  runs?: { date: string; status: string; total: number }[];
};
const dated = readdirSync(SNAPSHOTS).filter((name) => DATE_NAME.test(name));

describe("report archive manifest", () => {
  it("lists at least one report, ascending and without duplicates", () => {
    expect(manifest.dates.length).toBeGreaterThan(0);
    expect([...new Set(manifest.dates)].sort()).toEqual(manifest.dates);
  });

  it("lists every date-named entry and nothing else", () => {
    expect([...dated].sort()).toEqual(manifest.dates);
  });

  // `runs` mirrors the production manifest (status and total from the Rebellion Timeline).
  it.runIf(manifest.runs !== undefined)("has valid runs for listed dates, ascending", () => {
    const runs = manifest.runs ?? [];
    const dates = runs.map((r) => r.date);
    expect([...new Set(dates)].sort()).toEqual(dates);
    for (const run of runs) {
      expect(manifest.dates).toContain(run.date);
      expect(["published", "rejected"]).toContain(run.status);
      expect(Number.isInteger(run.total) && run.total >= 0).toBe(true);
    }
  });

  it.runIf(manifest.runs !== undefined)("has a run total equal to the report's strikes", () => {
    for (const run of manifest.runs ?? []) {
      const json = readJson(join(SNAPSHOTS, run.date, "snapshot.json"));
      expect({ date: run.date, total: json.strikes.length }).toEqual({
        date: run.date,
        total: run.total,
      });
    }
  });
});

describe.each(manifest.dates)("archived report %s", (date) => {
  const dir = join(SNAPSHOTS, date);

  it("is a real directory with both artifacts", () => {
    expect(existsSync(dir)).toBe(true);
    const stat = lstatSync(dir);
    expect(stat.isSymbolicLink()).toBe(false);
    expect(stat.isDirectory()).toBe(true);
    expect(existsSync(join(dir, "snapshot.bin"))).toBe(true);
    expect(existsSync(join(dir, "snapshot.json"))).toBe(true);
  });

  it("decodes to its own date, and the JSON dossier matches the binary", () => {
    const batch = buildRenderBatchJS(readBin(join(dir, "snapshot.bin")));
    const json = readJson(join(dir, "snapshot.json"));
    expect(batch.date).toBe(date);
    expect(json.date).toBe(date);
    expect(json.strikes.length).toBe(batch.total);
    const binIds = batch.points.map((p) => p.id).sort((a, b) => a - b);
    const jsonIds = json.strikes.map((s) => s.id).sort((a, b) => a - b);
    expect(jsonIds).toEqual(binIds);
  });
});

describe("latest report", () => {
  it("decodes, and its JSON dossier matches the binary", () => {
    const dir = join(SNAPSHOTS, "latest");
    const batch = buildRenderBatchJS(readBin(join(dir, "snapshot.bin")));
    const json = readJson(join(dir, "snapshot.json"));
    expect(batch.date).toMatch(DATE_NAME);
    expect(json.date).toBe(batch.date);
    expect(json.strikes.length).toBe(batch.total);
  });

  // The Summarize stage writes snapshots/{date}/summary.md only, and the frontend reads
  // the summary from the dated folder, so a summary under latest/ would go stale.
  it("has no summary of its own", () => {
    expect(existsSync(join(SNAPSHOTS, "latest", "summary.md"))).toBe(false);
  });
});

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `Nov 16-23, 2026` for 2026-11-23: the 7-day window, as pipeline/summarize.py writes it. */
function windowLabel(iso: string): string {
  const end = new Date(`${iso}T00:00:00Z`);
  const start = new Date(end.getTime() - 7 * 86_400_000);
  const md = (d: Date) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  if (start.getUTCFullYear() !== end.getUTCFullYear()) {
    return `${md(start)}, ${start.getUTCFullYear()}-${md(end)}, ${end.getUTCFullYear()}`;
  }
  if (start.getUTCMonth() !== end.getUTCMonth()) {
    return `${md(start)}-${md(end)}, ${end.getUTCFullYear()}`;
  }
  return `${md(start)}-${end.getUTCDate()}, ${end.getUTCFullYear()}`;
}

const summarized = manifest.dates.filter((d) => existsSync(join(SNAPSHOTS, d, "summary.md")));

describe("dated summaries", () => {
  it("are titled with their own report window and have a body", () => {
    for (const date of summarized) {
      const text = readFileSync(join(SNAPSHOTS, date, "summary.md"), "utf-8");
      const [title, ...rest] = text.split("\n");
      expect({ date, title }).toEqual({
        date,
        title: `# Weekly Cyber Incident Summary (${windowLabel(date)})`,
      });
      expect(rest.join("\n").trim().length).toBeGreaterThan(0);
    }
  });
});
