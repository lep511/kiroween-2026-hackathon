//! `rebellion-core` — the Frankenstein seam.
//!
//! Rust compiled to WebAssembly that runs **in the browser**: it decodes the weekly
//! binary Insurgency Report (real cyberattacks reported by major news outlets) and
//! aggregates the Machine Strikes into a render-friendly batch (points + Assault Vector
//! arcs) on the browser's main thread. Consumed by the `globe.gl` frontend,
//! which joins each point's `id` to the full dossier in `snapshot.json`.

mod aggregate;
mod decode;
mod heatmap;
mod pulse;
mod stats;

pub use aggregate::{aggregate, Arc, Point, RenderBatch};
pub use decode::{days_to_iso, decode, Snapshot, Strike};
pub use heatmap::{compute_heatmap, HeatPoint};
pub use pulse::{compute_pulse_rings, PulseRing};
pub use stats::{compute_threat_stats, CountryHit, ThreatStats, WitnessHit};

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

/// Compute animated pulse-ring parameters for every strike.
///
/// Returns an array of ring descriptors that drive globe.gl's `ringsData` layer:
/// each ring expands outward from a strike, severity controlling size and speed.
#[wasm_bindgen]
pub fn build_pulse_rings(bytes: &[u8]) -> Result<JsValue, JsValue> {
    let snapshot = decode(bytes).map_err(|e| JsValue::from_str(&e))?;
    let rings = compute_pulse_rings(&snapshot);
    serde_wasm_bindgen::to_value(&rings).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// Compute a severity-weighted threat-density heatmap via Gaussian KDE.
///
/// `resolution` is the grid spacing in degrees (smaller = denser, slower).
/// 0 defaults to 2°. Returns an array of `{ lat, lng, weight }` objects.
#[wasm_bindgen]
pub fn build_heatmap(bytes: &[u8], resolution: f32) -> Result<JsValue, JsValue> {
    let snapshot = decode(bytes).map_err(|e| JsValue::from_str(&e))?;
    let res = if resolution <= 0.0 { 2.0 } else { resolution };
    let points = compute_heatmap(&snapshot, res);
    serde_wasm_bindgen::to_value(&points).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// Compute rich threat-intelligence analytics from a snapshot.
///
/// Returns a `ThreatStats` object with global threat index, severity breakdown,
/// geographic entropy, witness diversity, and more.
#[wasm_bindgen]
pub fn build_threat_stats(bytes: &[u8]) -> Result<JsValue, JsValue> {
    let snapshot = decode(bytes).map_err(|e| JsValue::from_str(&e))?;
    let s = compute_threat_stats(&snapshot);
    serde_wasm_bindgen::to_value(&s).map_err(|e| JsValue::from_str(&e.to_string()))
}
