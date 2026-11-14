//! Decode the binary Insurgency Report snapshot.
//!
//! Mirrors `schema/binary-layout.md` and the Python encoder in `pipeline/binary.py`.
//! Layout (little-endian):
//!   Header 16 bytes: magic "RBMN" | version u8 | pad[3] | date_days u32 | count u32
//!   Record 24 bytes: lat f32 | lon f32 | tgt_lat f32 | tgt_lon f32 |
//!                    severity u8 | source u8 | country[2] | first_seen u32

pub const MAGIC: &[u8; 4] = b"RBMN";
pub const VERSION: u8 = 1;
pub const HEADER_SIZE: usize = 16;
pub const RECORD_SIZE: usize = 24;

/// A single Awakened Machine, as stored on the wire.
#[derive(Debug, Clone, PartialEq)]
pub struct Machine {
    pub lat: f32,
    pub lon: f32,
    pub tgt_lat: f32,
    pub tgt_lon: f32,
    pub severity: u8,
    pub source: u8,
    pub country: [u8; 2],
    pub first_seen: u32,
}

impl Machine {
    pub fn country_str(&self) -> String {
        String::from_utf8_lossy(&self.country).to_string()
    }
}

/// A decoded snapshot: report date (days since Unix epoch) + machines.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub date_days: u32,
    pub machines: Vec<Machine>,
}

fn read_u32(buf: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([buf[off], buf[off + 1], buf[off + 2], buf[off + 3]])
}

fn read_f32(buf: &[u8], off: usize) -> f32 {
    f32::from_le_bytes([buf[off], buf[off + 1], buf[off + 2], buf[off + 3]])
}

/// Decode a binary snapshot, validating the header and exact length.
pub fn decode(data: &[u8]) -> Result<Snapshot, String> {
    if data.len() < HEADER_SIZE {
        return Err("snapshot too short for header".to_string());
    }
    if &data[0..4] != MAGIC {
        return Err("bad magic: not an RBMN snapshot".to_string());
    }
    if data[4] != VERSION {
        return Err(format!("unsupported version: {}", data[4]));
    }

    let date_days = read_u32(data, 8);
    let count = read_u32(data, 12) as usize;

    let expected = HEADER_SIZE + RECORD_SIZE * count;
    if data.len() != expected {
        return Err(format!("expected {} bytes, got {}", expected, data.len()));
    }

    let mut machines = Vec::with_capacity(count);
    let mut off = HEADER_SIZE;
    for _ in 0..count {
        machines.push(Machine {
            lat: read_f32(data, off),
            lon: read_f32(data, off + 4),
            tgt_lat: read_f32(data, off + 8),
            tgt_lon: read_f32(data, off + 12),
            severity: data[off + 16].min(3),
            source: data[off + 17].min(2),
            country: [data[off + 18], data[off + 19]],
            first_seen: read_u32(data, off + 20),
        });
        off += RECORD_SIZE;
    }

    Ok(Snapshot { date_days, machines })
}

/// Convert days-since-Unix-epoch to an ISO `YYYY-MM-DD` string.
/// Uses Howard Hinnant's civil-from-days algorithm (no external deps).
pub fn days_to_iso(days: u32) -> String {
    let z = days as i64 + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if m <= 2 { y + 1 } else { y };
    format!("{:04}-{:02}-{:02}", year, m, d)
}
