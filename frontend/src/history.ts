// Rebellion Timeline: pure helpers for browsing past Insurgency Reports.
// No DOM access here, so the logic is unit-tested in Node (tests/history.test.ts).

export type ReportMode = "latest" | "archive";

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
