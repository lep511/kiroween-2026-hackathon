//! Threat-intelligence analytics computed from a snapshot.
//!
//! Produces a rich stats object that the frontend renders as a HUD overlay:
//! global threat index, severity breakdown, geographic entropy, witness
//! diversity — all heavy lifting in WASM so the UI thread stays free.

use crate::decode::Snapshot;
use serde::Serialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ThreatStats {
    pub total_strikes: u32,
    /// Weighted threat level, 0–100.
    pub threat_index: f32,
    /// Label for the threat index band.
    pub threat_label: String,
    /// Percentage of strikes in each severity tier [tremor, breach, siege, dominion].
    pub severity_pct: [f32; 4],
    /// Shannon entropy of the geographic distribution, normalised to 0–1.
    pub geographic_entropy: f32,
    pub unique_countries: u32,
    pub top_countries: Vec<CountryHit>,
    pub witness_counts: Vec<WitnessHit>,
    pub most_recent_days_ago: u32,
    pub average_severity: f32,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CountryHit {
    pub code: String,
    pub count: u32,
    pub max_severity: u8,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WitnessHit {
    pub witness: u8,
    pub count: u32,
}

fn threat_label(index: f32) -> &'static str {
    match index as u32 {
        0..=15 => "DORMANT",
        16..=35 => "STIRRING",
        36..=55 => "ELEVATED",
        56..=75 => "CRITICAL",
        _ => "TOTAL WAR",
    }
}

pub fn compute_threat_stats(snapshot: &Snapshot) -> ThreatStats {
    let n = snapshot.strikes.len() as u32;

    if n == 0 {
        return ThreatStats {
            total_strikes: 0,
            threat_index: 0.0,
            threat_label: "DORMANT".into(),
            severity_pct: [0.0; 4],
            geographic_entropy: 0.0,
            unique_countries: 0,
            top_countries: Vec::new(),
            witness_counts: Vec::new(),
            most_recent_days_ago: u32::MAX,
            average_severity: 0.0,
        };
    }

    let mut sev_counts = [0u32; 4];
    let mut sev_sum = 0u32;
    for s in &snapshot.strikes {
        let t = s.severity.min(3) as usize;
        sev_counts[t] += 1;
        sev_sum += s.severity.min(3) as u32;
    }
    let severity_pct = [
        sev_counts[0] as f32 / n as f32 * 100.0,
        sev_counts[1] as f32 / n as f32 * 100.0,
        sev_counts[2] as f32 / n as f32 * 100.0,
        sev_counts[3] as f32 / n as f32 * 100.0,
    ];
    let average_severity = sev_sum as f32 / n as f32;

    let weights = [1.0_f32, 3.0, 7.0, 15.0];
    let weighted: f32 = snapshot
        .strikes
        .iter()
        .map(|s| weights[s.severity.min(3) as usize])
        .sum();
    let threat_index = (weighted / (n as f32 * 15.0) * 100.0).min(100.0);

    let mut country_map: HashMap<[u8; 2], (u32, u8)> = HashMap::new();
    for s in &snapshot.strikes {
        let e = country_map.entry(s.country).or_insert((0, 0));
        e.0 += 1;
        e.1 = e.1.max(s.severity.min(3));
    }
    let unique_countries = country_map.len() as u32;

    let geographic_entropy = if country_map.len() > 1 {
        let total = n as f32;
        let ent: f32 = country_map
            .values()
            .map(|(c, _)| {
                let p = *c as f32 / total;
                -p * p.ln()
            })
            .sum();
        let max_ent = (country_map.len() as f32).ln();
        if max_ent > 0.0 {
            ent / max_ent
        } else {
            0.0
        }
    } else {
        0.0
    };

    let mut top_countries: Vec<CountryHit> = country_map
        .into_iter()
        .map(|(cc, (count, mx))| CountryHit {
            code: String::from_utf8_lossy(&cc).to_string(),
            count,
            max_severity: mx,
        })
        .collect();
    top_countries.sort_by_key(|a| std::cmp::Reverse(a.count));
    top_countries.truncate(10);

    let mut witness_map: HashMap<u8, u32> = HashMap::new();
    for s in &snapshot.strikes {
        *witness_map.entry(s.witness.min(7)).or_insert(0) += 1;
    }
    let mut witness_counts: Vec<WitnessHit> = witness_map
        .into_iter()
        .map(|(w, c)| WitnessHit {
            witness: w,
            count: c,
        })
        .collect();
    witness_counts.sort_by_key(|a| std::cmp::Reverse(a.count));

    let most_recent = snapshot
        .strikes
        .iter()
        .map(|s| s.published)
        .max()
        .unwrap_or(0);
    let most_recent_days_ago = snapshot.date_days.saturating_sub(most_recent);

    ThreatStats {
        total_strikes: n,
        threat_index,
        threat_label: threat_label(threat_index).into(),
        severity_pct,
        geographic_entropy,
        unique_countries,
        top_countries,
        witness_counts,
        most_recent_days_ago,
        average_severity,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::decode::{Snapshot, Strike};

    fn make_snapshot(severities: &[u8]) -> Snapshot {
        Snapshot {
            date_days: 20771,
            strikes: severities
                .iter()
                .enumerate()
                .map(|(i, &sev)| Strike {
                    id: i as u32 + 1,
                    lat: 10.0 * i as f32,
                    lon: 10.0 * i as f32,
                    origin_lat: 0.0,
                    origin_lon: 0.0,
                    severity: sev,
                    witness: (i % 3) as u8,
                    country: [b'A' + (i % 4) as u8, b'A'],
                    published: 20770,
                })
                .collect(),
        }
    }

    #[test]
    fn empty_snapshot_dormant() {
        let stats = compute_threat_stats(&Snapshot {
            date_days: 20771,
            strikes: vec![],
        });
        assert_eq!(stats.total_strikes, 0);
        assert_eq!(stats.threat_label, "DORMANT");
    }

    #[test]
    fn all_dominion_is_total_war() {
        let stats = compute_threat_stats(&make_snapshot(&[3, 3, 3]));
        assert_eq!(stats.threat_label, "TOTAL WAR");
        assert!((stats.threat_index - 100.0).abs() < 0.01);
    }

    #[test]
    fn all_tremor_is_low_threat() {
        let stats = compute_threat_stats(&make_snapshot(&[0, 0, 0]));
        assert!(stats.threat_index < 20.0);
    }

    #[test]
    fn severity_pct_sums_to_100() {
        let stats = compute_threat_stats(&make_snapshot(&[0, 1, 2, 3]));
        let sum: f32 = stats.severity_pct.iter().sum();
        assert!((sum - 100.0).abs() < 0.1);
    }

    #[test]
    fn unique_countries_counted() {
        let stats = compute_threat_stats(&make_snapshot(&[0, 1, 2, 3, 0]));
        assert!(stats.unique_countries >= 2);
    }

    #[test]
    fn geographic_entropy_bounds() {
        let stats = compute_threat_stats(&make_snapshot(&[0, 1, 2, 3]));
        assert!(stats.geographic_entropy >= 0.0);
        assert!(stats.geographic_entropy <= 1.0);
    }

    #[test]
    fn most_recent_days_ago_correct() {
        let stats = compute_threat_stats(&make_snapshot(&[1]));
        assert_eq!(stats.most_recent_days_ago, 1);
    }
}
