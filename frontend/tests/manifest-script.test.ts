// scripts/manifest.mjs builds the committed archive manifest for sync-snapshots.sh.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { buildArchiveManifest, formatManifest } from "../scripts/manifest.mjs";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "../scripts/manifest.mjs");

describe("buildArchiveManifest", () => {
  it("sorts and dedupes the valid dates and keeps no runs without a source", () => {
    expect(buildArchiveManifest(["2026-11-17", "2026-11-05", "2026-11-17"], null)).toEqual({
      dates: ["2026-11-05", "2026-11-17"],
    });
    expect(buildArchiveManifest(["2026-11-05"], { dates: ["2026-11-05"] })).toEqual({
      dates: ["2026-11-05"],
    });
  });

  it("copies only valid runs of valid folders, sorted, last entry winning", () => {
    const source = {
      dates: ["2026-11-05", "2026-11-14", "2026-11-17"],
      runs: [
        { date: "2026-11-17", status: "published", total: 36 },
        { date: "2026-11-14", status: "published", total: 5 }, // no folder
        { date: "2026-11-05", status: "pending", total: 26 },
        { date: "2026-11-05", status: "published", total: -1 },
        { date: "2026-11-05", status: "published", total: 2.5 },
        { date: "2026-11-05", status: "published", total: "26" },
        null,
        "2026-11-05",
        { date: "2026-11-05", status: "rejected", total: 26 },
        { date: "2026-11-17", status: "published", total: 37, extra: true },
      ],
    };
    expect(buildArchiveManifest(["2026-11-17", "2026-11-05"], source)).toEqual({
      dates: ["2026-11-05", "2026-11-17"],
      runs: [
        { date: "2026-11-05", status: "rejected", total: 26 },
        { date: "2026-11-17", status: "published", total: 37 },
      ],
    });
  });

  it("keeps an empty runs list when the source has one", () => {
    expect(buildArchiveManifest([], { dates: [], runs: [] })).toEqual({ dates: [], runs: [] });
  });

  it("keeps the fallback runs of folders the source does not describe", () => {
    // A stack rebuilt from scratch: production only knows its new report.
    const production = { dates: ["2026-11-26"], runs: [{ date: "2026-11-26", status: "published", total: 4 }] };
    const local = {
      dates: ["2026-11-05", "2026-11-19"],
      runs: [
        { date: "2026-11-05", status: "published", total: 26 },
        { date: "2026-11-19", status: "published", total: 44 },
        { date: "2026-11-26", status: "rejected", total: 1 }, // production wins
      ],
    };
    expect(buildArchiveManifest(["2026-11-05", "2026-11-19", "2026-11-26"], production, local))
      .toEqual({
        dates: ["2026-11-05", "2026-11-19", "2026-11-26"],
        runs: [
          { date: "2026-11-05", status: "published", total: 26 },
          { date: "2026-11-19", status: "published", total: 44 },
          { date: "2026-11-26", status: "published", total: 4 },
        ],
      });
    expect(buildArchiveManifest(["2026-11-05"], null, local)).toEqual({
      dates: ["2026-11-05"],
      runs: [{ date: "2026-11-05", status: "published", total: 26 }],
    });
  });
});

describe("formatManifest", () => {
  it("matches Python json.dumps plus a newline", () => {
    const manifest = {
      dates: ["2026-11-05", "2026-11-15"],
      runs: [{ date: "2026-11-05", status: "published", total: 26 }],
    };
    expect(formatManifest(manifest)).toBe(
      '{"dates": ["2026-11-05", "2026-11-15"], "runs": [{"date": "2026-11-05", ' +
        '"status": "published", "total": 26}]}\n',
    );
    expect(formatManifest({ dates: [] })).toBe('{"dates": []}\n');
  });
});

describe("manifest.mjs CLI", () => {
  let dir: string | null = null;
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = null;
  });

  it("rewrites the manifest in place, keeping the runs of valid folders", () => {
    dir = mkdtempSync(join(tmpdir(), "manifest-"));
    const file = join(dir, "manifest.json");
    const runs = [
      { date: "2026-11-05", status: "published", total: 26 },
      { date: "2026-11-14", status: "published", total: 5 },
    ];
    writeFileSync(file, JSON.stringify({ dates: ["2026-11-05", "2026-11-14"], runs }));
    const out = execFileSync(
      process.execPath,
      [SCRIPT, "--out", file, "--source", file, "2026-11-05"],
      { encoding: "utf-8" },
    );
    expect(out.trim().split("\n").pop()).toBe("1 report(s), 1 run(s)");
    expect(readFileSync(file, "utf-8")).toBe(
      '{"dates": ["2026-11-05"], "runs": [{"date": "2026-11-05", "status": "published", ' +
        '"total": 26}]}\n',
    );
  });

  it("treats a missing source as no runs", () => {
    dir = mkdtempSync(join(tmpdir(), "manifest-"));
    const file = join(dir, "manifest.json");
    execFileSync(process.execPath, [SCRIPT, "--out", file, "--source", join(dir, "none.json")]);
    expect(readFileSync(file, "utf-8")).toBe('{"dates": []}\n');
  });
});
