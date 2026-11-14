// Snapshot types + a pure-TypeScript fallback decoder/aggregator (binary layout v2).
//
// The PRIMARY path decodes snapshots with the Rust/WASM core (see wasm-loader.ts).
// This fallback mirrors schema/binary-layout.md and rebellion-core/src/aggregate.rs
// so the globe still renders in environments where the WASM package has not been
// built (e.g. no Rust toolchain). Keep it byte-compatible with the Rust decoder.
//
// The binary carries only what the globe needs to draw a strike fast; the full
// dossier (headline, stolen data, fallout, ward, article URL) lives in snapshot.json
// and is joined to each point by `id` (see snapshot-detail.ts).

export interface Point {
  id: number;
  lat: number;
  lng: number;
  severity: number;
  witness: number;
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
const VERSION = 2;
const HEADER_SIZE = 16;
const RECORD_SIZE = 28;
const DEFAULT_MAX_ARCS = 1500;

function daysToIso(days: number): string {
  // Days since Unix epoch -> YYYY-MM-DD (UTC).
  const ms = days * 86_400_000;
  return new Date(ms).toISOString().slice(0, 10);
}

interface RawStrike {
  id: number;
  lat: number;
  lon: number;
  originLat: number;
  originLon: number;
  severity: number;
  witness: number;
  country: string;
  published: number;
}

function decode(buffer: ArrayBuffer): { dateDays: number; strikes: RawStrike[] } {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);

  if (bytes.length < HEADER_SIZE) throw new Error("snapshot too short for header");
  for (let i = 0; i < 4; i++) {
    if (bytes[i] !== MAGIC[i]) throw new Error("bad magic: not an RBMN snapshot");
  }
  if (bytes[4] !== VERSION) throw new Error(`unsupported version: ${bytes[4]}`);

  const dateDays = view.getUint32(8, true);
  const count = view.getUint32(12, true);
  const expected = HEADER_SIZE + RECORD_SIZE * count;
  if (bytes.length !== expected) {
    throw new Error(`expected ${expected} bytes, got ${bytes.length}`);
  }

  const strikes: RawStrike[] = [];
  let off = HEADER_SIZE;
  for (let i = 0; i < count; i++) {
    strikes.push({
      id: view.getUint32(off, true),
      lat: view.getFloat32(off + 4, true),
      lon: view.getFloat32(off + 8, true),
      originLat: view.getFloat32(off + 12, true),
      originLon: view.getFloat32(off + 16, true),
      severity: Math.min(bytes[off + 20], 3),
      witness: Math.min(bytes[off + 21], 6),
      country: String.fromCharCode(bytes[off + 22], bytes[off + 23]),
      published: view.getUint32(off + 24, true),
    });
    off += RECORD_SIZE;
  }
  return { dateDays, strikes };
}

function aggregate(
  snap: { dateDays: number; strikes: RawStrike[] },
  maxArcs = DEFAULT_MAX_ARCS,
): RenderBatch {
  const counts: [number, number, number, number] = [0, 0, 0, 0];
  for (const s of snap.strikes) counts[s.severity]++;

  // One point per strike, carrying its id so the UI can open the dossier.
  const points: Point[] = snap.strikes.map((s) => ({
    id: s.id,
    lat: s.lat,
    lng: s.lon,
    severity: s.severity,
    witness: s.witness,
    country: s.country,
    weight: 1,
  }));

  // Arcs origin -> ground zero, highest severity first, then cap.
  const arcs: Arc[] = [...snap.strikes]
    .sort((a, b) => b.severity - a.severity)
    .slice(0, maxArcs)
    .map((s) => ({
      startLat: s.originLat,
      startLng: s.originLon,
      endLat: s.lat,
      endLng: s.lon,
      severity: s.severity,
    }));

  return {
    date: daysToIso(snap.dateDays),
    points,
    arcs,
    counts,
    total: snap.strikes.length,
  };
}

/** Decode + aggregate a binary snapshot in pure TS (WASM fallback). */
export function buildRenderBatchJS(buffer: ArrayBuffer, maxArcs = 0): RenderBatch {
  return aggregate(decode(buffer), maxArcs === 0 ? DEFAULT_MAX_ARCS : maxArcs);
}
