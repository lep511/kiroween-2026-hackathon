//! Aggregate a decoded snapshot into a render-friendly batch for globe.gl.
//!
//! - Points are de-duplicated by a coarse geo cell, keeping the highest severity,
//!   so thousands of co-located machines don't blow up the scene.
//! - Assault Vectors (arcs) are built source -> target, highest severity first,
//!   and capped to a level-of-detail limit.

use crate::decode::{days_to_iso, Snapshot};
use serde::Serialize;

/// A glowing node on the globe.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Point {
    pub lat: f32,
    pub lng: f32,
    pub severity: u8,
    pub source: u8,
    pub country: String,
    /// How many machines collapsed into this cell (drives node size).
    pub weight: u32,
}

/// An Assault Vector arc between a source and a command-center target.
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
    /// Count per severity tier: [flatline, haunting, possession, singularity].
    pub counts: [u32; 4],
    pub total: u32,
}

const DEFAULT_MAX_ARCS: usize = 1500;

fn cell_key(lat: f32, lon: f32) -> (i32, i32) {
    // ~1 degree cells.
    (lat.round() as i32, lon.round() as i32)
}

/// Build the render batch. `max_arcs` caps arcs for level-of-detail (None = default).
pub fn aggregate(snapshot: &Snapshot, max_arcs: Option<usize>) -> RenderBatch {
    let max_arcs = max_arcs.unwrap_or(DEFAULT_MAX_ARCS);

    let mut counts = [0u32; 4];
    for m in &snapshot.machines {
        counts[m.severity.min(3) as usize] += 1;
    }

    // De-duplicate points by coarse cell, keeping the highest severity seen.
    let mut keys: Vec<(i32, i32)> = Vec::new();
    let mut points: Vec<Point> = Vec::new();
    for m in &snapshot.machines {
        let key = cell_key(m.lat, m.lon);
        if let Some(idx) = keys.iter().position(|k| *k == key) {
            let p = &mut points[idx];
            p.weight += 1;
            if m.severity > p.severity {
                p.severity = m.severity;
                p.source = m.source;
            }
        } else {
            keys.push(key);
            points.push(Point {
                lat: m.lat,
                lng: m.lon,
                severity: m.severity.min(3),
                source: m.source.min(2),
                country: m.country_str(),
                weight: 1,
            });
        }
    }

    // Build arcs, highest severity first, then cap.
    let mut ordered: Vec<&_> = snapshot.machines.iter().collect();
    ordered.sort_by(|a, b| b.severity.cmp(&a.severity));
    let arcs: Vec<Arc> = ordered
        .into_iter()
        .take(max_arcs)
        .map(|m| Arc {
            start_lat: m.lat,
            start_lng: m.lon,
            end_lat: m.tgt_lat,
            end_lng: m.tgt_lon,
            severity: m.severity.min(3),
        })
        .collect();

    RenderBatch {
        date: days_to_iso(snapshot.date_days),
        points,
        arcs,
        counts,
        total: snapshot.machines.len() as u32,
    }
}
