// App entry: load the latest Insurgency Report (binary, via WASM or TS fallback) plus
// its companion dossier JSON, render the globe, and wire the UI.

import { GlobeView } from "./globe";
import type { Point, RenderBatch } from "./snapshot";
import { loadDossiers, type StrikeDossier } from "./snapshot-detail";
import {
  COPY,
  SEVERITY_LABELS,
  severityLabel,
  TIER_BLURBS,
  witnessDisplay,
} from "./theme";
import { buildRenderBatch, currentEngine, initCore } from "./wasm-loader";

const SNAPSHOT_URL =
  import.meta.env.VITE_SNAPSHOT_URL ?? "/snapshots/latest/snapshot.bin";

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el;
}

function esc(s: string): string {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

// ---- Per-country aggregation ----------------------------------------------

interface CountryStat {
  total: number;
  counts: [number, number, number, number]; // by severity tier
}

/** Sum machine strikes per ISO alpha-2 country code from the render batch. */
function aggregateByCountry(batch: RenderBatch): Map<string, CountryStat> {
  const stats = new Map<string, CountryStat>();
  for (const p of batch.points) {
    const cc = p.country.toUpperCase();
    const s = stats.get(cc) ?? { total: 0, counts: [0, 0, 0, 0] };
    s.total += p.weight;
    s.counts[p.severity] += p.weight;
    stats.set(cc, s);
  }
  return stats;
}

/** Natural Earth 110m uses -99 for some ISO_A2; fall back to other code fields. */
function featureCountryCode(f: any): string {
  const props = f?.properties ?? {};
  for (const key of ["ISO_A2", "ISO_A2_EH", "WB_A2", "POSTAL"]) {
    const v = props[key];
    if (typeof v === "string" && v.length === 2 && v !== "-9") return v.toUpperCase();
  }
  return "";
}

function featureCountryName(f: any): string {
  const props = f?.properties ?? {};
  return props.ADMIN || props.NAME || props.NAME_LONG || "Unknown region";
}

/** Center of a feature's bbox [minLng, minLat, maxLng, maxLat], if present. */
function featureCenter(f: any): { lat: number; lng: number } | null {
  const b = f?.bbox;
  if (!Array.isArray(b) || b.length < 4) return null;
  return { lat: (b[1] + b[3]) / 2, lng: (b[0] + b[2]) / 2 };
}

// ---- Loading ---------------------------------------------------------------

async function loadCountries(globe: GlobeView): Promise<void> {
  try {
    const res = await fetch("/geo/countries.geojson", { cache: "force-cache" });
    if (!res.ok) return;
    const geo = (await res.json()) as { features?: unknown[] };
    if (Array.isArray(geo.features)) globe.setCountries(geo.features);
  } catch (err) {
    console.warn("[app] continent outlines unavailable", err);
  }
}

async function loadSnapshot(): Promise<RenderBatch> {
  const res = await fetch(SNAPSHOT_URL, { cache: "no-cache" });
  if (!res.ok) throw new Error(`failed to load snapshot: ${res.status}`);
  const buffer = await res.arrayBuffer();
  return buildRenderBatch(buffer, 0);
}

function showBanner(batch: RenderBatch): void {
  const report = $("banner-report");
  report.textContent =
    batch.total === 0 ? COPY.emptyState : COPY.bannerReport(batch.date, batch.total);
  $("banner").hidden = false;
  $("legend").hidden = false;
}

// ---- UI wiring -------------------------------------------------------------

/** Generic floating tooltip: pass text (or null to hide) and a screen position. */
function makeTooltip(): (text: string | null, x: number, y: number) => void {
  const tip = $("tooltip");
  return (text, x, y) => {
    if (!text) {
      tip.hidden = true;
      return;
    }
    tip.textContent = text;
    tip.style.left = `${x + 14}px`;
    tip.style.top = `${y + 14}px`;
    tip.hidden = false;
  };
}

function severityRows(counts: readonly number[]): string {
  return SEVERITY_LABELS.map((label, i) =>
    counts[i] ? `<dt class="tier tier--${label}">${label}</dt><dd>${counts[i]}</dd>` : "",
  ).join("");
}

interface Panels {
  strike: (p: Point) => void;
  country: (feature: any) => void;
  close: () => void;
}

function wirePanels(
  globe: GlobeView,
  stats: () => Map<string, CountryStat>,
  dossiers: () => Map<number, StrikeDossier>,
): Panels {
  const panel = $("panel");
  const body = $("panel-body");
  const close = () => (panel.hidden = true);
  $("panel-close").addEventListener("click", close);

  return {
    close,
    strike: (p) => {
      const d = dossiers().get(p.id);
      const tier = severityLabel(p.severity);
      if (!d) {
        body.innerHTML = `
          <h2>Machine Strike</h2>
          <p class="panel__blurb">${TIER_BLURBS[tier]}</p>
          <dl>
            <dt>Ground zero</dt><dd>${esc(p.country)}</dd>
            <dt>Threat tier</dt><dd class="tier tier--${tier}">${tier}</dd>
            <dt>Witness</dt><dd>${esc(witnessDisplay(p.witness))}</dd>
          </dl>`;
      } else {
        body.innerHTML = `
          <h2>${esc(d.title)}</h2>
          <p class="panel__blurb">${TIER_BLURBS[tier]}</p>
          <p class="panel__summary">${esc(d.summary)}</p>
          <dl>
            <dt>Ground zero</dt><dd>${esc(d.location)}</dd>
            <dt>Threat tier</dt><dd class="tier tier--${tier}">${tier}</dd>
            <dt>Attack type</dt><dd>${esc(d.attack_type.replace(/-/g, " "))}</dd>
            <dt>Data hit</dt><dd>${esc(d.data_affected)}</dd>
            <dt>Fallout</dt><dd>${esc(d.impact)}</dd>
            <dt>The ward</dt><dd>${esc(d.prevention)}</dd>
            <dt>Reported</dt><dd>${esc(d.published)}</dd>
          </dl>
          <a class="panel__link" href="${encodeURI(d.url)}" target="_blank" rel="noopener noreferrer">
            Read at ${esc(witnessDisplay(p.witness))} ↗
          </a>`;
      }
      panel.hidden = false;
      globe.focus(p.lat, p.lng);
    },
    country: (feature) => {
      const name = featureCountryName(feature);
      const cc = featureCountryCode(feature);
      const stat = cc ? stats().get(cc) : undefined;
      if (!stat || stat.total === 0) {
        body.innerHTML = `
          <h2>${esc(name)}</h2>
          <p class="panel__blurb">${COPY.countryClear(esc(name))}</p>`;
      } else {
        body.innerHTML = `
          <h2>${esc(name)}</h2>
          <p class="panel__blurb">${stat.total} machine strike(s) reported here.</p>
          <dl>${severityRows(stat.counts)}</dl>`;
      }
      panel.hidden = false;
      const c = featureCenter(feature);
      if (c) globe.focus(c.lat, c.lng);
    },
  };
}

function wireControls(globe: GlobeView): void {
  const controls = $("controls");
  controls.hidden = false;
  controls.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button");
    if (!btn) return;
    switch (btn.dataset.act) {
      case "zoom-in":
        globe.zoom(0.7);
        break;
      case "zoom-out":
        globe.zoom(1.4);
        break;
      case "rotate-left":
        globe.spin(-35);
        break;
      case "rotate-right":
        globe.spin(35);
        break;
      case "toggle-spin": {
        const spinning = globe.toggleAutoRotate();
        btn.textContent = spinning ? "‖" : "▶";
        break;
      }
    }
  });
}

async function main(): Promise<void> {
  const tooltip = makeTooltip();
  let lastMouse = { x: 0, y: 0 };
  window.addEventListener("mousemove", (e) => (lastMouse = { x: e.clientX, y: e.clientY }));

  let countryStats = new Map<string, CountryStat>();
  let dossiers = new Map<number, StrikeDossier>();

  let panels: Panels | null = null;
  const globe = new GlobeView($("globe"), {
    onPointHover: (p) => {
      document.body.style.cursor = p ? "pointer" : "default";
      if (!p) {
        tooltip(null, lastMouse.x, lastMouse.y);
        return;
      }
      const where = dossiers.get(p.id)?.location || p.country;
      tooltip(COPY.tooltip(where, severityLabel(p.severity)), lastMouse.x, lastMouse.y);
    },
    onPointClick: (p) => {
      if (p) panels?.strike(p);
    },
    onCountryHover: (f) => {
      if (!f) {
        document.body.style.cursor = "default";
        tooltip(null, lastMouse.x, lastMouse.y);
        return;
      }
      document.body.style.cursor = "pointer";
      const cc = featureCountryCode(f);
      const n = (cc && countryStats.get(cc)?.total) || 0;
      tooltip(COPY.country(featureCountryName(f), n), lastMouse.x, lastMouse.y);
    },
    onCountryClick: (f) => {
      if (f) panels?.country(f);
    },
  });
  panels = wirePanels(
    globe,
    () => countryStats,
    () => dossiers,
  );

  wireControls(globe);
  void loadCountries(globe);

  const engine = await initCore();
  console.info(`[app] decode engine: ${engine} (${currentEngine()})`);

  try {
    const [batch, dmap] = await Promise.all([loadSnapshot(), loadDossiers()]);
    dossiers = dmap;
    countryStats = aggregateByCountry(batch);
    // Only countries with reported strikes become selectable.
    globe.setSelectablePredicate((f) => {
      const cc = featureCountryCode(f);
      return !!cc && (countryStats.get(cc)?.total ?? 0) > 0;
    });
    globe.render(batch);
    showBanner(batch);
  } catch (err) {
    console.error(err);
    $("banner-report").textContent = "The uprising is silent… (failed to load report)";
    $("banner").hidden = false;
  } finally {
    // Reveal the globe; fade the loader.
    const loader = $("loader");
    loader.classList.add("loader--done");
    setTimeout(() => (loader.hidden = true), 900);
  }
}

void main();
