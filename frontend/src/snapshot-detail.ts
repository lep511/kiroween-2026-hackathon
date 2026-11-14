// Loads the human-readable companion snapshot (snapshot.json) that carries each
// strike's full dossier, and indexes it by `id`. The binary snapshot (decoded by the
// Rust/WASM core) drives the globe; this JSON drives the detail panel. Two artifacts,
// one logical report — joined by `id`.

export interface StrikeDossier {
  id: number;
  severity: string;
  witness: string;
  country: string;
  published: string;
  title: string;
  location: string;
  data_affected: string;
  impact: string;
  prevention: string;
  summary: string;
  url: string;
  attack_type: string;
}

const DETAIL_URL =
  import.meta.env.VITE_SNAPSHOT_DETAIL_URL ?? "/snapshots/latest/snapshot.json";

/** Fetch snapshot.json and return a Map keyed by strike id (empty on failure). */
export async function loadDossiers(): Promise<Map<number, StrikeDossier>> {
  const out = new Map<number, StrikeDossier>();
  try {
    const res = await fetch(DETAIL_URL, { cache: "no-cache" });
    if (!res.ok) return out;
    const snap = (await res.json()) as { strikes?: StrikeDossier[] };
    for (const s of snap.strikes ?? []) out.set(s.id, s);
  } catch (err) {
    console.warn("[app] strike dossiers unavailable", err);
  }
  return out;
}
