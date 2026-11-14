// The Halloween skin — single source of truth for colors + copy on the client.
// Mirrors .kiro/steering/narrative-tone.md. All strings are in English.

export const SEVERITY_LABELS = [
  "flatline",
  "haunting",
  "possession",
  "singularity",
] as const;

export const SOURCE_LABELS = ["feodo", "urlhaus", "other"] as const;

// Neon red/green uprising palette, indexed by severity tier (0..3).
export const SEVERITY_COLORS = [
  "#2e7d5b", // flatline   — dim, dormant machine
  "#39ff14", // haunting   — neon green signal
  "#ff7518", // possession — pumpkin orange
  "#ff1744", // singularity — blood red, fully awake
] as const;

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
};
