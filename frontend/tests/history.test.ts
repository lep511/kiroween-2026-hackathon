import { describe, expect, it } from "vitest";
import {
  createSequencer,
  parseManifest,
  parseRuns,
  pickerEntry,
  reportMode,
  snapshotBase,
} from "../src/history";

describe("parseRuns", () => {
  it("maps each valid run by date", () => {
    const runs = parseRuns({
      dates: ["2026-11-05", "2026-11-19"],
      runs: [
        { date: "2026-11-05", status: "published", total: 26 },
        { date: "2026-11-19", status: "rejected", total: 0 },
      ],
    });
    expect([...runs]).toEqual([
      ["2026-11-05", { status: "published", total: 26 }],
      ["2026-11-19", { status: "rejected", total: 0 }],
    ]);
  });

  it("ignores entries with an unknown status, a bad total or an invalid date", () => {
    const runs = parseRuns({
      runs: [
        { date: "2026-11-05", status: "pending", total: 26 },
        { date: "2026-11-06", status: "published", total: -1 },
        { date: "2026-11-07", status: "published", total: 2.5 },
        { date: "2026-11-08", status: "published", total: "26" },
        { date: "2026-11-09", status: "published" },
        { date: "2026-02-30", status: "published", total: 1 },
        { date: "latest", status: "published", total: 1 },
        null,
        "2026-11-10",
        { date: "2026-11-11", status: "published", total: 3 },
      ],
    });
    expect([...runs.keys()]).toEqual(["2026-11-11"]);
  });

  it("lets a later entry for the same date win", () => {
    const runs = parseRuns({
      runs: [
        { date: "2026-11-05", status: "rejected", total: 1 },
        { date: "2026-11-05", status: "published", total: 2 },
      ],
    });
    expect(runs.get("2026-11-05")).toEqual({ status: "published", total: 2 });
  });

  it("returns an empty map for a missing or invalid runs field", () => {
    for (const raw of [{}, { dates: ["2026-11-05"] }, { runs: "x" }, { runs: {} }, null, [], 7]) {
      expect(parseRuns(raw).size).toBe(0);
    }
  });
});

describe("pickerEntry", () => {
  it("shows the strike total, singular or plural", () => {
    expect(pickerEntry({ status: "published", total: 1 })).toEqual({
      meta: "1 strike",
      rejected: false,
    });
    expect(pickerEntry({ status: "published", total: 44 })).toEqual({
      meta: "44 strikes",
      rejected: false,
    });
    expect(pickerEntry({ status: "published", total: 0 }).meta).toBe("0 strikes");
  });

  it("flags a rejected day", () => {
    expect(pickerEntry({ status: "rejected", total: 3 })).toEqual({
      meta: "3 strikes",
      rejected: true,
    });
  });

  it("shows nothing extra for an unknown run", () => {
    expect(pickerEntry(undefined)).toEqual({ meta: null, rejected: false });
  });
});

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
