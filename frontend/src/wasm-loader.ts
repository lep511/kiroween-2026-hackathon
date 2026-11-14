// Loads the Rust/WASM core if it has been built into ./wasm (via `npm run wasm`),
// and otherwise falls back to the pure-TS decoder. Either way the rest of the app
// just calls `buildRenderBatch(bytes)` and gets a RenderBatch.

import { buildRenderBatchJS, type RenderBatch } from "./snapshot";

type WasmModule = {
  default: (input?: unknown) => Promise<unknown>;
  build_render_batch: (bytes: Uint8Array, maxArcs: number) => RenderBatch;
  core_version: () => string;
};

let wasm: WasmModule | null = null;
let engine: "wasm" | "js" = "js";

export async function initCore(): Promise<"wasm" | "js"> {
  try {
    // Built by: wasm-pack build rebellion-core --target web --out-dir frontend/src/wasm
    // The specifier is computed so the bundler keeps it as a runtime import: the
    // package may not exist (no Rust toolchain), in which case we fall back to TS.
    const spec = ["./wasm", "rebellion_core.js"].join("/");
    const mod = (await import(/* @vite-ignore */ spec)) as WasmModule;
    await mod.default();
    wasm = mod;
    engine = "wasm";
    console.info(`[core] Rust/WASM core v${mod.core_version()} online.`);
  } catch (err) {
    engine = "js";
    console.warn("[core] WASM core unavailable, using TS fallback.", err);
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
