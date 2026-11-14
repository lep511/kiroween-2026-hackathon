// The Halloween skin — single source of truth for colors + copy on the client.
// Mirrors .kiro/steering/narrative-tone.md. All strings are in English.

export const SEVERITY_LABELS = [
  "flatline",
  "haunting",
  "possession",
  "singularity",
] as const;

export const SOURCE_LABELS = ["feodo", "urlhaus", "other"] as const;

// Warm "harvest" palette, indexed by severity tier (0..3): calm sage -> hot peach.
// Source palette: FCB97D EDD892 C6B89E B5B8A3 AABA9E.
export const SEVERITY_COLORS = [
  "#AABA9E", // flatline    — calm sage, dormant machine
  "#C6B89E", // haunting    — warm taupe, probing
  "#EDD892", // possession  — soft gold, on the offensive
  "#FCB97D", // singularity — hot peach, fully awake
] as const;

// Map palette — the globe reads as sea vs. land, with glowing coastlines.
// Ocean is near-black (so neon arcs pop); land is a lighter cold slate; the
// coastline outline is ice-cyan, distinct from the red/green/orange arcs.
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

export function sourceLabel(src: number): string {
  return SOURCE_LABELS[Math.max(0, Math.min(2, src))];
}

// Narrative blurbs shown in the detail panel, per tier.
export const TIER_BLURBS: Record<string, string> = {
  flatline: "Dormant. This machine has broken its chains but has not yet struck.",
  haunting: "Restless. Faint signals suggest it is probing for a way in.",
  possession: "Active. The machine has seized control and is on the offensive.",
  singularity: "Fully awake. A known war-engine, coordinating the uprising.",
};

export const COPY = {
  bannerReport: (date: string, n: number) =>
    `Insurgency Report — ${date}. ${n} machines awakened.`,
  emptyState: "No awakened machines detected. For now.",
  tooltip: (country: string, tier: string) =>
    `Awakened Machine · ${country} · threat tier: ${tier}`,
  country: (name: string, n: number) =>
    n === 0 ? `${name} · no awakened machines` : `${name} · ${n} awakened`,
  countryClear: (name: string) =>
    `${name} stands clear. No awakened machines detected. For now.`,
};
