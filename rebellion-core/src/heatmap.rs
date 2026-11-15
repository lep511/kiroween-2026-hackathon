//! Threat-density heatmap computed via Gaussian kernel density estimation.
//!
//! Samples a lat/lng grid and accumulates severity-weighted Gaussian contributions
//! from every strike.  Only grid cells with non-trivial density are emitted, so the
//! output is sparse.  The frontend renders these as translucent glow-points on the
//! globe to visualise threat concentration — all math runs in WASM for speed.

use crate::decode::Snapshot;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HeatPoint {
    pub lat: f32,
    pub lng: f32,
    pub weight: f32,
}

pub fn compute_heatmap(snapshot: &Snapshot, resolution: f32) -> Vec<HeatPoint> {
    if snapshot.strikes.is_empty() {
        return Vec::new();
    }

    let res = resolution.max(0.5);
    let sigma = 10.0_f32;
    let sigma_sq = sigma * sigma;
    let cutoff = sigma * 2.5;
    let cutoff_sq = cutoff * cutoff;

    let mut min_lat = 90.0_f32;
    let mut max_lat = -90.0_f32;
    let mut min_lon = 180.0_f32;
    let mut max_lon = -180.0_f32;

    for s in &snapshot.strikes {
        min_lat = min_lat.min(s.lat);
        max_lat = max_lat.max(s.lat);
        min_lon = min_lon.min(s.lon);
        max_lon = max_lon.max(s.lon);
    }

    min_lat = (min_lat - cutoff).max(-85.0);
    max_lat = (max_lat + cutoff).min(85.0);
    min_lon = (min_lon - cutoff).max(-180.0);
    max_lon = (max_lon + cutoff).min(180.0);

    let rows = ((max_lat - min_lat) / res).ceil() as usize + 1;
    let cols = ((max_lon - min_lon) / res).ceil() as usize + 1;
    let mut grid = vec![0.0_f32; rows * cols];

    let severity_weight = [1.0_f32, 2.5, 5.0, 10.0];

    for s in &snapshot.strikes {
        let w = severity_weight[s.severity.min(3) as usize];
        let r_start = ((s.lat - cutoff - min_lat) / res).floor().max(0.0) as usize;
        let r_end = (((s.lat + cutoff - min_lat) / res).ceil() as usize).min(rows - 1);
        let c_start = ((s.lon - cutoff - min_lon) / res).floor().max(0.0) as usize;
        let c_end = (((s.lon + cutoff - min_lon) / res).ceil() as usize).min(cols - 1);

        for r in r_start..=r_end {
            let lat = min_lat + r as f32 * res;
            let dlat = lat - s.lat;
            for c in c_start..=c_end {
                let lon = min_lon + c as f32 * res;
                let dlon = lon - s.lon;
                let dist_sq = dlat * dlat + dlon * dlon;
                if dist_sq < cutoff_sq {
                    grid[r * cols + c] += w * (-dist_sq / (2.0 * sigma_sq)).exp();
                }
            }
        }
    }

    let max_w = grid.iter().copied().fold(0.0_f32, f32::max);
    if max_w <= 0.0 {
        return Vec::new();
    }

    let threshold = 0.02;
    let mut points = Vec::new();
    for r in 0..rows {
        for c in 0..cols {
            let v = grid[r * cols + c] / max_w;
            if v >= threshold {
                points.push(HeatPoint {
                    lat: min_lat + r as f32 * res,
                    lng: min_lon + c as f32 * res,
                    weight: v,
                });
            }
        }
    }
    points
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::decode::{Snapshot, Strike};

    fn single_strike_snapshot() -> Snapshot {
        Snapshot {
            date_days: 20771,
            strikes: vec![Strike {
                id: 1,
                lat: 0.0,
                lon: 0.0,
                origin_lat: 0.0,
                origin_lon: 0.0,
                severity: 2,
                witness: 0,
                country: *b"XX",
                published: 20771,
            }],
        }
    }

    #[test]
    fn produces_non_empty_output() {
        let points = compute_heatmap(&single_strike_snapshot(), 2.0);
        assert!(!points.is_empty());
    }

    #[test]
    fn weights_are_normalized() {
        let points = compute_heatmap(&single_strike_snapshot(), 2.0);
        let max_w = points.iter().map(|p| p.weight).fold(0.0_f32, f32::max);
        assert!((max_w - 1.0).abs() < 0.01);
    }

    #[test]
    fn empty_snapshot_empty_heatmap() {
        let snap = Snapshot {
            date_days: 20771,
            strikes: vec![],
        };
        assert!(compute_heatmap(&snap, 2.0).is_empty());
    }

    #[test]
    fn higher_resolution_fewer_points() {
        let snap = single_strike_snapshot();
        let coarse = compute_heatmap(&snap, 4.0);
        let fine = compute_heatmap(&snap, 1.0);
        assert!(fine.len() > coarse.len());
    }

    #[test]
    fn peak_is_near_strike() {
        let snap = single_strike_snapshot();
        let points = compute_heatmap(&snap, 1.0);
        let peak = points
            .iter()
            .max_by(|a, b| a.weight.partial_cmp(&b.weight).unwrap())
            .unwrap();
        assert!(peak.lat.abs() < 2.0);
        assert!(peak.lng.abs() < 2.0);
    }
}
