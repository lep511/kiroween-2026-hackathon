// Snapshot types + a pure-TypeScript fallback decoder/aggregator.
//
// The PRIMARY path decodes snapshots with the Rust/WASM core (see wasm-loader.ts).
// This fallback mirrors schema/binary-layout.md and rebellion-core/src/aggregate.rs
// so the globe still renders in environments where the WASM package has not been
// built (e.g. no Rust toolchain). Keep it byte-compatible with the Rust decoder.

export interface Point {
  lat: number;
  lng: number;
  severity: number;
  source: number;
  country: string;
  weight: number;
}

export interface Arc {
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  severity: number;
}

export interface RenderBatch {
  date: string;
  points: Point[];
  arcs: Arc[];
  counts: [number, number, number, number];
  total: number;
}

const MAGIC = [0x52, 0x42, 0x4d, 0x4e]; // "RBMN"
const HEADER_SIZE = 16;
const RECORD_SIZE = 24;
const DEFAULT_MAX_ARCS = 1500;

function daysToIso(days: number): string {
  // Days since Unix epoch -> YYYY-MM-DD (UTC).
  const ms = days * 86_400_000;
  return new Date(ms).toISOString().slice(0, 10);
}

interface RawMachine {
  lat: number;
  lon: number;
  tgtLat: number;
  tgtLon: number;
  severity: number;
  source: number;
  country: string;
  firstSeen: number;
}

function decode(buffer: ArrayBuffer): { dateDays: number; machines: RawMachine[] } {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);

  if (bytes.length < HEADER_SIZE) throw new Error("snapshot too short for header");
  for (let i = 0; i < 4; i++) {
    if (bytes[i] !== MAGIC[i]) throw new Error("bad magic: not an RBMN snapshot");
  }
  if (bytes[4] !== 1) throw new Error(`unsupported version: ${bytes[4]}`);

  const dateDays = view.getUint32(8, true);
  const count = view.getUint32(12, true);
  const expected = HEADER_SIZE + RECORD_SIZE * count;
  if (bytes.length !== expected) {
    throw new Error(`expected ${expected} bytes, got ${bytes.length}`);
  }

  const machines: RawMachine[] = [];
  let off = HEADER_SIZE;
  for (let i = 0; i < count; i++) {
    machines.push({
      lat: view.getFloat32(off, true),
      lon: view.getFloat32(off + 4, true),
      tgtLat: view.getFloat32(off + 8, true),
      tgtLon: view.getFloat32(off + 12, true),
      severity: Math.min(bytes[off + 16], 3),
      source: Math.min(bytes[off + 17], 2),
      country: String.fromCharCode(bytes[off + 18], bytes[off + 19]),
      firstSeen: view.getUint32(off + 20, true),
    });
    off += RECORD_SIZE;
  }
  return { dateDays, machines };
}

function aggregate(
  snap: { dateDays: number; machines: RawMachine[] },
  maxArcs = DEFAULT_MAX_ARCS,
): RenderBatch {
  const counts: [number, number, number, number] = [0, 0, 0, 0];
  for (const m of snap.machines) counts[m.severity]++;

  // De-duplicate points by ~1 degree cell, keeping the highest severity.
  const cells = new Map<string, Point>();
  for (const m of snap.machines) {
    const key = `${Math.round(m.lat)},${Math.round(m.lon)}`;
    const existing = cells.get(key);
    if (existing) {
      existing.weight++;
      if (m.severity > existing.severity) {
        existing.severity = m.severity;
        existing.source = m.source;
      }
    } else {
      cells.set(key, {
        lat: m.lat,
        lng: m.lon,
        severity: m.severity,
        source: m.source,
        country: m.country,
        weight: 1,
      });
    }
  }

  const arcs: Arc[] = [...snap.machines]
    .sort((a, b) => b.severity - a.severity)
    .slice(0, maxArcs)
    .map((m) => ({
      startLat: m.lat,
      startLng: m.lon,
      endLat: m.tgtLat,
      endLng: m.tgtLon,
      severity: m.severity,
    }));

  return {
    date: daysToIso(snap.dateDays),
    points: [...cells.values()],
    arcs,
    counts,
    total: snap.machines.length,
  };
}

/** Decode + aggregate a binary snapshot in pure TS (WASM fallback). */
export function buildRenderBatchJS(buffer: ArrayBuffer, maxArcs = 0): RenderBatch {
  return aggregate(decode(buffer), maxArcs === 0 ? DEFAULT_MAX_ARCS : maxArcs);
}
