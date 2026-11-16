//! Compute animated pulse-ring parameters for each Machine Strike.
//!
//! Each strike emits expanding concentric rings on the globe surface.
//! Severity controls ring size, speed, and color intensity — higher threat
//! tiers pulse faster and wider.  The output feeds globe.gl's `ringsData` layer.

use crate::decode::Snapshot;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PulseRing {
    pub lat: f32,
    pub lng: f32,
    pub max_radius: f32,
    pub propagation_speed: f32,
    pub repeat_period: f32,
    pub color_r: u8,
    pub color_g: u8,
    pub color_b: u8,
    pub color_a: f32,
    pub altitude: f32,
    pub id: u32,
    pub severity: u8,
}

const RING_COLORS: [(u8, u8, u8); 4] = [
    (85, 107, 86),   // tremor  — forest green
    (207, 190, 137), // breach  — gold
    (255, 122, 0),   // siege   — orange
    (198, 117, 133), // dominion — rose red
];

const RING_ALPHA: [f32; 4] = [0.45, 0.55, 0.7, 0.85];

pub fn compute_pulse_rings(snapshot: &Snapshot) -> Vec<PulseRing> {
    snapshot
        .strikes
        .iter()
        .map(|s| {
            let sev = s.severity.min(3) as usize;
            let (r, g, b) = RING_COLORS[sev];

            PulseRing {
                lat: s.lat,
                lng: s.lon,
                max_radius: 2.0 + sev as f32 * 1.8,
                propagation_speed: 1.2 + sev as f32 * 0.6,
                repeat_period: 2800.0 - sev as f32 * 500.0,
                color_r: r,
                color_g: g,
                color_b: b,
                color_a: RING_ALPHA[sev],
                altitude: 0.004 + sev as f32 * 0.002,
                id: s.id,
                severity: s.severity.min(3),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::decode::{Snapshot, Strike};

    fn sample_snapshot() -> Snapshot {
        Snapshot {
            date_days: 20771,
            strikes: vec![
                Strike {
                    id: 1,
                    lat: 48.8,
                    lon: 2.3,
                    origin_lat: 55.7,
                    origin_lon: 37.6,
                    severity: 0,
                    witness: 0,
                    country: *b"FR",
                    published: 20770,
                },
                Strike {
                    id: 2,
                    lat: 40.7,
                    lon: -74.0,
                    origin_lat: 40.7,
                    origin_lon: -74.0,
                    severity: 3,
                    witness: 2,
                    country: *b"US",
                    published: 20771,
                },
            ],
        }
    }

    #[test]
    fn one_ring_per_strike() {
        let snap = sample_snapshot();
        let rings = compute_pulse_rings(&snap);
        assert_eq!(rings.len(), snap.strikes.len());
    }

    #[test]
    fn higher_severity_bigger_rings() {
        let snap = sample_snapshot();
        let rings = compute_pulse_rings(&snap);
        assert!(rings[1].max_radius > rings[0].max_radius);
        assert!(rings[1].propagation_speed > rings[0].propagation_speed);
    }

    #[test]
    fn ring_positions_match_strikes() {
        let snap = sample_snapshot();
        let rings = compute_pulse_rings(&snap);
        for (ring, strike) in rings.iter().zip(snap.strikes.iter()) {
            assert_eq!(ring.lat, strike.lat);
            assert_eq!(ring.lng, strike.lon);
            assert_eq!(ring.id, strike.id);
        }
    }

    #[test]
    fn empty_snapshot_no_rings() {
        let snap = Snapshot {
            date_days: 20771,
            strikes: vec![],
        };
        assert!(compute_pulse_rings(&snap).is_empty());
    }
}
