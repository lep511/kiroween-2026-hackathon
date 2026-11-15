// The Halloween skin — single source of truth for colors + copy on the client.
// Mirrors .kiro/steering/narrative-tone.md. All strings are in English.

export const SEVERITY_LABELS = [
  "tremor",
  "breach",
  "siege",
  "dominion",
] as const;

// Recognized witnesses (news outlets), indexed by the binary `witness` byte (0..5).
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

// Warm "harvest" palette, indexed by severity tier (0..3): calm sage -> hot peach.
// Source palette: FCB97D EDD892 C6B89E B5B8A3 AABA9E.
export const SEVERITY_COLORS = [
  "#AABA9E", // tremor   — calm sage, the first tremor
  "#C6B89E", // breach   — warm taupe, a wall is breached
  "#EDD892", // siege    — soft gold, under active assault
  "#FCB97D", // dominion — hot peach, total dominion
] as const;

// Map palette — the globe reads as sea vs. land, with glowing coastlines.
export const MAP = {
  ocean: "#0c0e0b",
  oceanEmissive: "#15130c",
  land: "rgba(181, 184, 163, 0.16)", // B5B8A3 sage-gray, low alpha
  landSide: "rgba(181, 184, 163, 0.1)",
  coastline: "#B5B8A3", // sage-gray coastline, distinct from the warmer tiers
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

export const COPY = {
  bannerReport: (date: string, n: number) =>
    `Insurgency Report — ${date}. ${n} machine strikes reported.`,
  emptyState: "No machine strikes reported. For now.",
  tooltip: (location: string, tier: string) =>
    `Machine Strike · ${location} · threat tier: ${tier}`,
  country: (name: string, n: number) =>
    n === 0 ? `${name} · no strikes` : `${name} · ${n} strike(s)`,
  countryClear: (name: string) =>
    `${name} stands clear. No machine strikes reported. For now.`,
};
