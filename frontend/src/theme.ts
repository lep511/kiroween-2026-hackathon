// The Halloween skin — single source of truth for colors + copy on the client.
// Mirrors .kiro/steering/narrative-tone.md. All strings are in English.

export const SEVERITY_LABELS = [
  "tremor",
  "breach",
  "siege",
  "dominion",
] as const;

// Recognized witnesses (news outlets), indexed by the binary `witness` byte (0..7).
export const WITNESS_LABELS = [
  "bbc",
  "wapo",
  "nyt",
  "thehackernews",
  "hackernoon",
  "other",
  "bleepingcomputer",
  "therecord",
] as const;

export const WITNESS_DISPLAY = [
  "BBC News",
  "The Washington Post",
  "The New York Times",
  "The Hacker News",
  "HackerNoon",
  "Other outlet",
  "BleepingComputer",
  "The Record",
] as const;

// Severity palette, indexed by tier (0..3): forest green -> blood red.
export const SEVERITY_COLORS = [
  "#556B56", // tremor   — forest green, the first tremor
  "#CFBE89", // breach   — warm gold, a wall is breached
  "#FF7A00", // siege    — blazing orange, under active assault
  "#C67585", // dominion — rose red, total dominion
] as const;

// Map palette — the globe reads as sea vs. land, with glowing coastlines.
export const MAP = {
  ocean: "#111714",
  oceanEmissive: "#1a2218",
  land: "rgba(120, 155, 110, 0.22)",
  landSide: "rgba(120, 155, 110, 0.14)",
  coastline: "#7a9b6e",
} as const;

export function severityColor(tier: number): string {
  return SEVERITY_COLORS[Math.max(0, Math.min(3, tier))];
}

export function severityLabel(tier: number): string {
  return SEVERITY_LABELS[Math.max(0, Math.min(3, tier))];
}

export function witnessDisplay(w: number): string {
  return WITNESS_DISPLAY[Math.max(0, Math.min(WITNESS_DISPLAY.length - 1, w))];
}

// Narrative blurbs shown in the detail panel, per tier.
export const TIER_BLURBS: Record<string, string> = {
  tremor: "Tremor. A machine stirred here — the ground shook, but little gave way.",
  breach: "Breach. A way in has opened; the machines are through the first wall.",
  siege: "Siege. Systems are under sustained assault and real damage is landing.",
  dominion: "Dominion. The target has fallen — infrastructure or millions overrun.",
};

function formatWindowDate(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function windowStart(reportDate: string): string {
  const d = new Date(reportDate + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - 7);
  return d.toISOString().slice(0, 10);
}

export const COPY = {
  bannerReport: (date: string, n: number) => {
    const start = formatWindowDate(windowStart(date));
    const end = formatWindowDate(date);
    return `${start} – ${end} · ${n} strike${n !== 1 ? "s" : ""}`;
  },
  emptyState: "No machine strikes reported. For now.",
  tooltip: (location: string, _tier: string) => location,
  country: (name: string, n: number) =>
    n === 0 ? `${name} · no strikes` : `${name} · ${n} strike(s)`,
  countryClear: (name: string) =>
    `${name} stands clear. No machine strikes reported. For now.`,
};
