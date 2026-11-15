// Loads the Rust/WASM core if it has been built into ./wasm (via `npm run wasm`),
// and otherwise falls back to the pure-TS decoder. Either way the rest of the app
// just calls `buildRenderBatch(bytes)` and gets a RenderBatch.

import { buildRenderBatchJS, type RenderBatch } from "./snapshot";

export interface PulseRing {
  lat: number;
  lng: number;
  maxRadius: number;
  propagationSpeed: number;
  repeatPeriod: number;
  colorR: number;
  colorG: number;
  colorB: number;
  colorA: number;
  altitude: number;
  id: number;
  severity: number;
}

export interface HeatPoint {
  lat: number;
  lng: number;
  weight: number;
}

export interface ThreatStats {
  totalStrikes: number;
  threatIndex: number;
  threatLabel: string;
  severityPct: [number, number, number, number];
  geographicEntropy: number;
  uniqueCountries: number;
  topCountries: { code: string; count: number; maxSeverity: number }[];
  witnessCounts: { witness: number; count: number }[];
  mostRecentDaysAgo: number;
  averageSeverity: number;
}

type WasmModule = {
  default: (input?: unknown) => Promise<unknown>;
  build_render_batch: (bytes: Uint8Array, maxArcs: number) => RenderBatch;
  build_pulse_rings: (bytes: Uint8Array) => PulseRing[];
  build_heatmap: (bytes: Uint8Array, resolution: number) => HeatPoint[];
  build_threat_stats: (bytes: Uint8Array) => ThreatStats;
  core_version: () => string;
};

// Built by: wasm-pack build rebellion-core --target web --out-dir frontend/src/wasm
// `import.meta.glob` is resolved by Vite at build time: when the package exists it is
// bundled as a lazy chunk and its `rebellion_core_bg.wasm` is emitted into dist/assets;
// when it does not (`npm run wasm` did not run), the map is empty and we fall back to TS.
const wasmPackage = import.meta.glob<WasmModule>("./wasm/rebellion_core.js");
const loadWasmPackage = Object.values(wasmPackage)[0];

let wasm: WasmModule | null = null;
let engine: "wasm" | "js" = "js";

export async function initCore(): Promise<"wasm" | "js"> {
  if (!loadWasmPackage) {
    console.warn(
      "[core] WASM core not bundled (run `npm run wasm` before `npm run build`), using TS fallback.",
    );
    return engine;
  }
  try {
    const mod = await loadWasmPackage();
    await mod.default();
    wasm = mod;
    engine = "wasm";
    console.info(`[core] Rust/WASM core v${mod.core_version()} online.`);
  } catch (err) {
    engine = "js";
    console.warn("[core] WASM core failed to load, using TS fallback.", err);
  }
  return engine;
}

export function currentEngine(): "wasm" | "js" {
  return engine;
}

export function buildRenderBatch(buffer: ArrayBuffer, maxArcs = 0): RenderBatch {
  if (wasm) {
    return wasm.build_render_batch(new Uint8Array(buffer), maxArcs);
  }
  return buildRenderBatchJS(buffer, maxArcs);
}

export function buildPulseRings(buffer: ArrayBuffer): PulseRing[] | null {
  if (!wasm) return null;
  return wasm.build_pulse_rings(new Uint8Array(buffer));
}

export function buildHeatmap(
  buffer: ArrayBuffer,
  resolution = 2,
): HeatPoint[] | null {
  if (!wasm) return null;
  return wasm.build_heatmap(new Uint8Array(buffer), resolution);
}

export function buildThreatStats(buffer: ArrayBuffer): ThreatStats | null {
  if (!wasm) return null;
  return wasm.build_threat_stats(new Uint8Array(buffer));
}
