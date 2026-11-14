//! Aggregate a decoded snapshot into a render-friendly batch for globe.gl.
//!
//! - Each Machine Strike becomes one glowing point carrying its `id` (so the frontend
//!   can join it to the full dossier in snapshot.json for the detail panel).
//! - Assault Vectors (arcs) are built origin -> ground zero, highest severity first,
//!   and capped to a level-of-detail limit.

use crate::decode::{days_to_iso, Snapshot};
use serde::Serialize;

/// A glowing node on the globe (ground zero of one strike).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Point {
    /// Join key into snapshot.json (the strike's dossier).
    pub id: u32,
    pub lat: f32,
    pub lng: f32,
    pub severity: u8,
    pub witness: u8,
    pub country: String,
    /// Kept for UI symmetry (always 1: strikes are not merged).
    pub weight: u32,
}

/// An Assault Vector arc from an attributed origin to ground zero.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Arc {
    pub start_lat: f32,
    pub start_lng: f32,
    pub end_lat: f32,
    pub end_lng: f32,
    pub severity: u8,
}

/// Everything the frontend needs to render one Insurgency Report.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderBatch {
    pub date: String,
    pub points: Vec<Point>,
    pub arcs: Vec<Arc>,
    /// Count per severity tier: [tremor, breach, siege, dominion].
    pub counts: [u32; 4],
    pub total: u32,
}

const DEFAULT_MAX_ARCS: usize = 1500;

/// Build the render batch. `max_arcs` caps arcs for level-of-detail (None = default).
pub fn aggregate(snapshot: &Snapshot, max_arcs: Option<usize>) -> RenderBatch {
    let max_arcs = max_arcs.unwrap_or(DEFAULT_MAX_ARCS);

    let mut counts = [0u32; 4];
    for s in &snapshot.strikes {
        counts[s.severity.min(3) as usize] += 1;
    }

    // One point per strike, carrying its id so the UI can open the dossier.
    let points: Vec<Point> = snapshot
        .strikes
        .iter()
        .map(|s| Point {
            id: s.id,
            lat: s.lat,
            lng: s.lon,
            severity: s.severity.min(3),
            witness: s.witness.min(6),
            country: s.country_str(),
            weight: 1,
        })
        .collect();

    // Build arcs origin -> ground zero, highest severity first, then cap.
    let mut ordered: Vec<&_> = snapshot.strikes.iter().collect();
    ordered.sort_by(|a, b| b.severity.cmp(&a.severity));
    let arcs: Vec<Arc> = ordered
        .into_iter()
        .take(max_arcs)
        .map(|s| Arc {
            start_lat: s.origin_lat,
            start_lng: s.origin_lon,
            end_lat: s.lat,
            end_lng: s.lon,
            severity: s.severity.min(3),
        })
        .collect();

    RenderBatch {
        date: days_to_iso(snapshot.date_days),
        points,
        arcs,
        counts,
        total: snapshot.strikes.len() as u32,
    }
}
