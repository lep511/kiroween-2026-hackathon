import { describe, expect, it } from "vitest";
import {
  createSequencer,
  parseManifest,
  reportMode,
  snapshotBase,
} from "../src/history";

describe("parseManifest", () => {
  it("returns the dates newest first", () => {
    expect(parseManifest({ dates: ["2026-11-05", "2026-11-19", "2026-11-17"] })).toEqual([
      "2026-11-19",
      "2026-11-17",
      "2026-11-05",
    ]);
  });

  it("drops duplicates", () => {
    expect(parseManifest({ dates: ["2026-11-17", "2026-11-17", "2026-11-05"] })).toEqual([
      "2026-11-17",
      "2026-11-05",
    ]);
  });

  it("drops malformed strings and non-strings", () => {
    const raw = {
      dates: ["2026-11-17", "2026-1-5", "latest", "../etc", "2026-11-17T00:00", 20261117, null],
    };
    expect(parseManifest(raw)).toEqual(["2026-11-17"]);
  });

  it("drops impossible calendar dates", () => {
    expect(parseManifest({ dates: ["2026-02-30", "2026-13-01", "2026-00-10", "2028-02-29"] }))
      .toEqual(["2028-02-29"]);
  });

  it("returns [] for a missing or invalid dates field", () => {
    expect(parseManifest({})).toEqual([]);
    expect(parseManifest({ dates: "2026-11-17" })).toEqual([]);
    expect(parseManifest(null)).toEqual([]);
    expect(parseManifest(undefined)).toEqual([]);
    expect(parseManifest(["2026-11-17"])).toEqual([]);
    expect(parseManifest("nope")).toEqual([]);
  });
});

describe("reportMode", () => {
  it("is latest when the shown date is the latest report's date", () => {
    expect(reportMode("2026-11-19", "2026-11-19")).toBe("latest");
  });

  it("is archive for any other date", () => {
    expect(reportMode("2026-11-17", "2026-11-19")).toBe("archive");
    // A backfilled date newer than latest/ is still an archived report.
    expect(reportMode("2026-11-20", "2026-11-19")).toBe("archive");
  });

  it("is archive when the latest date is unknown", () => {
    expect(reportMode("2026-11-19", null)).toBe("archive");
  });
});

describe("snapshotBase", () => {
  it("points at latest/ for null and at the dated folder otherwise", () => {
    expect(snapshotBase(null)).toBe("/snapshots/latest");
    expect(snapshotBase("2026-11-17")).toBe("/snapshots/2026-11-17");
  });
});

describe("createSequencer", () => {
  it("keeps the newest token current and invalidates every older one", () => {
    const seq = createSequencer();
    const a = seq.next();
    expect(seq.isCurrent(a)).toBe(true);
    const b = seq.next();
    const c = seq.next();
    expect(seq.isCurrent(a)).toBe(false);
    expect(seq.isCurrent(b)).toBe(false);
    expect(seq.isCurrent(c)).toBe(true);
  });

  it("never reports a token as current before it was issued", () => {
    const seq = createSequencer();
    expect(seq.isCurrent(0)).toBe(false);
    expect(seq.isCurrent(1)).toBe(false);
  });

  it("keeps separate sequencers independent", () => {
    const one = createSequencer();
    const two = createSequencer();
    const t = one.next();
    two.next();
    two.next();
    expect(one.isCurrent(t)).toBe(true);
  });
});
