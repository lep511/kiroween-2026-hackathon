// Rebellion Timeline: pure helpers for browsing past Insurgency Reports.
// No DOM access here, so the logic is unit-tested in Node (tests/history.test.ts).

import { COPY } from "./theme";

export type ReportMode = "latest" | "archive";

/** One report's verdict and strike total, from the manifest's `runs` (the timeline). */
export interface RunInfo {
  status: "published" | "rejected";
  total: number;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True for a `YYYY-MM-DD` string that names a real calendar day (UTC). */
function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const m = ISO_DATE.exec(value);
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toISOString().slice(0, 10) === value;
}

/**
 * Read the `{ dates: [...] }` report manifest. Keeps valid calendar dates only, drops
 * duplicates, and returns them newest first. Anything malformed yields `[]`.
 */
export function parseManifest(raw: unknown): string[] {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return [];
  const dates = (raw as { dates?: unknown }).dates;
  if (!Array.isArray(dates)) return [];
  return [...new Set(dates.filter(isIsoDate))].sort().reverse();
}

/**
 * Read the manifest's optional `runs` (`[{ date, status, total }]`) into a map by date.
 * Entries with an invalid date, an unknown status or a total that is not a non-negative
 * integer are ignored; a later entry for the same date wins. Anything malformed yields
 * an empty map, so the picker simply shows the dates.
 */
export function parseRuns(raw: unknown): Map<string, RunInfo> {
  const runs = new Map<string, RunInfo>();
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return runs;
  const list = (raw as { runs?: unknown }).runs;
  if (!Array.isArray(list)) return runs;
  for (const entry of list) {
    if (entry === null || typeof entry !== "object") continue;
    const { date, status, total } = entry as Record<string, unknown>;
    if (!isIsoDate(date)) continue;
    if (status !== "published" && status !== "rejected") continue;
    if (typeof total !== "number" || !Number.isInteger(total) || total < 0) continue;
    runs.set(date, { status, total });
  }
  return runs;
}

export interface PickerEntry {
  /** Strike total shown next to the date, or null when the run is unknown. */
  meta: string | null;
  /** True when the day's batch was rejected (shown with a REJECTED tag). */
  rejected: boolean;
}

/** What the report picker shows next to a date. */
export function pickerEntry(run: RunInfo | undefined): PickerEntry {
  if (run === undefined) return { meta: null, rejected: false };
  return { meta: COPY.pickerStrikes(run.total), rejected: run.status === "rejected" };
}

/**
 * The shown report is the latest one only when its date equals the date of the report
 * served at `/snapshots/latest/`. The newest manifest date is not used, because a
 * backfill adds a date without touching `latest/`.
 */
export function reportMode(loadedDate: string, latestDate: string | null): ReportMode {
  return latestDate !== null && loadedDate === latestDate ? "latest" : "archive";
}

/** Base URL of a report's artifacts: `latest/` for null, the dated folder otherwise. */
export function snapshotBase(date: string | null): string {
  return date === null ? "/snapshots/latest" : `/snapshots/${date}`;
}

export interface Sequencer {
  /** Start a new request; every older token stops being current. */
  next(): number;
  /** True only for the most recently issued token. */
  isCurrent(token: number): boolean;
}

/** Last-request-wins guard for overlapping report loads. */
export function createSequencer(): Sequencer {
  let current = 0;
  return {
    next: () => ++current,
    isCurrent: (token) => token > 0 && token === current,
  };
}
