//! `rebellion-core` — the Frankenstein seam.
//!
//! Rust compiled to WebAssembly that runs **in the browser**: it decodes the daily
//! binary Insurgency Report (real cyberattacks reported by major news outlets) and
//! aggregates the Machine Strikes into a render-friendly batch (points + Assault Vector
//! arcs) on the browser's main thread. Consumed by the `globe.gl` frontend,
//! which joins each point's `id` to the full dossier in `snapshot.json`.

mod aggregate;
mod decode;

pub use aggregate::{aggregate, Arc, Point, RenderBatch};
pub use decode::{days_to_iso, decode, Snapshot, Strike};

use wasm_bindgen::prelude::*;

/// Decode + aggregate a binary snapshot into a render batch (JS object).
///
/// `max_arcs == 0` means "use the default level-of-detail cap".
#[wasm_bindgen]
pub fn build_render_batch(bytes: &[u8], max_arcs: u32) -> Result<JsValue, JsValue> {
    let snapshot = decode(bytes).map_err(|e| JsValue::from_str(&e))?;
    let cap = if max_arcs == 0 {
        None
    } else {
        Some(max_arcs as usize)
    };
    let batch = aggregate(&snapshot, cap);
    serde_wasm_bindgen::to_value(&batch).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// Lightweight probe used by the frontend to confirm the WASM core loaded.
#[wasm_bindgen]
pub fn core_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

/// Return just the number of strikes in a snapshot (cheap validation helper).
#[wasm_bindgen]
pub fn strike_count(bytes: &[u8]) -> Result<u32, JsValue> {
    decode(bytes)
        .map(|s| s.strikes.len() as u32)
        .map_err(|e| JsValue::from_str(&e))
}
