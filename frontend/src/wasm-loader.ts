// Loads the Rust/WASM core if it has been built into ./wasm (via `npm run wasm`),
// and otherwise falls back to the pure-TS decoder. Either way the rest of the app
// just calls `buildRenderBatch(bytes)` and gets a RenderBatch.

import { buildRenderBatchJS, type RenderBatch } from "./snapshot";

type WasmModule = {
  default: (input?: unknown) => Promise<unknown>;
  build_render_batch: (bytes: Uint8Array, maxArcs: number) => RenderBatch;
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
