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
import {
  buildHeatmap,
  buildPulseRings,
  buildRenderBatch,
  buildThreatStats,
  currentEngine,
  initCore,
  type PulseRing,
  type ThreatStats,
} from "./wasm-loader";

const DEFAULT_SNAPSHOT_BASE = "/snapshots/latest";
const MANIFEST_URL = "/snapshots/manifest.json";

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
  points: Point[]; // every strike reported in this country
}

/** Sum machine strikes per ISO alpha-2 country code from the render batch. */
function aggregateByCountry(batch: RenderBatch): Map<string, CountryStat> {
  const stats = new Map<string, CountryStat>();
  for (const p of batch.points) {
    const cc = p.country.toUpperCase();
    const s = stats.get(cc) ?? { total: 0, counts: [0, 0, 0, 0], points: [] };
    s.total += p.weight;
    s.counts[p.severity] += p.weight;
    s.points.push(p);
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

// Snapshot loading moved inline into main() so we can reuse the ArrayBuffer
// for both the render batch and the experimental WASM effects.

// ---- Overlap spreading ------------------------------------------------------

/**
 * Spread same-country points into a golden-angle spiral so they don't pile up
 * on the same pixel. Arc endpoints follow the moved points.
 */
function spreadBatch(batch: RenderBatch): RenderBatch {
  const { points, arcs } = batch;
  if (points.length <= 1) return batch;

  const byCountry = new Map<string, number[]>();
  for (let i = 0; i < points.length; i++) {
    const cc = points[i].country.toUpperCase();
    const group = byCountry.get(cc) ?? [];
    group.push(i);
    byCountry.set(cc, group);
  }

  const posKey = (lat: number, lng: number) =>
    `${lat.toFixed(5)},${lng.toFixed(5)}`;
  const posMap = new Map<string, { lat: number; lng: number }>();

  const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
  const SPACING = 2.0;

  const newPoints = points.map((p) => ({ ...p }));

  for (const indices of byCountry.values()) {
    if (indices.length <= 1) continue;

    let cLat = 0;
    let cLng = 0;
    for (const i of indices) {
      cLat += points[i].lat;
      cLng += points[i].lng;
    }
    cLat /= indices.length;
    cLng /= indices.length;

    const cosLat = Math.cos((cLat * Math.PI) / 180);
    const lngScale = cosLat > 0.1 ? 1 / cosLat : 1;

    const sorted = [...indices].sort(
      (a, b) =>
        points[b].severity - points[a].severity || points[a].id - points[b].id,
    );

    for (let k = 0; k < sorted.length; k++) {
      const idx = sorted[k];
      const oldKey = posKey(points[idx].lat, points[idx].lng);
      let lat: number;
      let lng: number;

      if (k === 0) {
        lat = cLat;
        lng = cLng;
      } else {
        const r = SPACING * Math.sqrt(k);
        const theta = k * GOLDEN_ANGLE;
        lat = cLat + r * Math.sin(theta);
        lng = cLng + r * Math.cos(theta) * lngScale;
      }

      newPoints[idx] = { ...points[idx], lat, lng };
      posMap.set(oldKey, { lat, lng });
    }
  }

  const newArcs = arcs.map((a) => {
    const key = posKey(a.endLat, a.endLng);
    const moved = posMap.get(key);
    return moved ? { ...a, endLat: moved.lat, endLng: moved.lng } : a;
  });

  return { ...batch, points: newPoints, arcs: newArcs };
}

function showBanner(batch: RenderBatch): void {
  const report = $("banner-report");
  report.textContent =
    batch.total === 0 ? COPY.emptyState : COPY.bannerReport(batch.date, batch.total);
  $("banner").hidden = false;
  $("legend").hidden = false;
}

function buildCountryNav(
  stats: Map<string, CountryStat>,
  dossiers: Map<number, StrikeDossier>,
  panels: Panels,
): void {
  const nav = $("country-nav");
  nav.innerHTML = "";

  const entries = [...stats.entries()]
    .filter(([, s]) => s.total > 0)
    .sort((a, b) => b[1].total - a[1].total);

  for (const [cc, stat] of entries) {
    const sample = stat.points[0];
    const d = sample ? dossiers.get(sample.id) : undefined;
    const name = d?.country || cc;

    const btn = document.createElement("button");
    btn.className = "country-chip";
    btn.type = "button";
    btn.innerHTML = `${esc(name)} <span class="country-chip__count">${stat.total}</span>`;
    btn.addEventListener("click", () => panels.countryByCode(cc, name));
    nav.appendChild(btn);
  }

  nav.hidden = entries.length === 0;
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

/**
 * Render every strike reported in a country as a clickable list. Each entry
 * opens that strike's full dossier (handled by a delegated click in wirePanels).
 */
function strikeList(points: Point[], dossiers: Map<number, StrikeDossier>): string {
  const sorted = [...points].sort(
    (a, b) => b.severity - a.severity || a.id - b.id,
  );
  const items = sorted
    .map((p) => {
      const d = dossiers.get(p.id);
      const tier = severityLabel(p.severity);
      const title = d?.title || "Machine Strike";
      const meta = d?.location || p.country;
      return `
        <li>
          <button class="strike-item" type="button" data-id="${p.id}">
            <span class="strike-item__dot tier--${tier}" aria-hidden="true"></span>
            <span class="strike-item__text">
              <span class="strike-item__title">${esc(title)}</span>
              <span class="strike-item__meta">${esc(meta)} · <span class="tier--${tier}">${tier}</span></span>
            </span>
            <span class="strike-item__chev" aria-hidden="true">›</span>
          </button>
        </li>`;
    })
    .join("");
  return `<ul class="panel__list">${items}</ul>`;
}

interface Panels {
  strike: (p: Point) => void;
  country: (feature: any) => void;
  countryByCode: (cc: string, name: string) => void;
  close: () => void;
}

function wirePanels(
  globe: GlobeView,
  stats: () => Map<string, CountryStat>,
  dossiers: () => Map<number, StrikeDossier>,
  pointsById: () => Map<number, Point>,
  pulseRings: () => Map<number, PulseRing>,
): Panels {
  const panel = $("panel");
  const body = $("panel-body");
  const dateGroup = $("banner-report").parentElement!;

  // Opening the panel hides the date group (it would sit under the
  // panel); closing it brings it back.
  const open = () => {
    panel.hidden = false;
    dateGroup.classList.add("is-hidden");
  };
  const close = () => {
    panel.hidden = true;
    dateGroup.classList.remove("is-hidden");
    globe.selectPin(null);
    globe.showPulseRing(null);
  };
  $("panel-close").addEventListener("click", close);

  const strike = (p: Point) => {
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
    body.scrollTop = 0;
    open();
    globe.selectPin(p);
    globe.focus(p.lat, p.lng);
    globe.showPulseRing(pulseRings().get(p.id) ?? null);
  };

  const showCountryPanel = (cc: string, name: string, focusLat?: number, focusLng?: number) => {
    const stat = cc ? stats().get(cc) : undefined;
    if (!stat || stat.total === 0) {
      body.innerHTML = `
        <h2>${esc(name)}</h2>
        <p class="panel__blurb">${COPY.countryClear(esc(name))}</p>`;
    } else {
      body.innerHTML = `
        <h2>${esc(name)}</h2>
        <p class="panel__blurb">${stat.total} machine strike(s) reported here.</p>
        <dl>${severityRows(stat.counts)}</dl>
        <h3 class="panel__subhead">Insurgency log · ${stat.total}</h3>
        ${strikeList(stat.points, dossiers())}`;
      if (focusLat == null && stat.points.length > 0) {
        focusLat = stat.points.reduce((s, p) => s + p.lat, 0) / stat.points.length;
        focusLng = stat.points.reduce((s, p) => s + p.lng, 0) / stat.points.length;
      }
    }
    body.scrollTop = 0;
    open();
    globe.selectPin(null);
    globe.showPulseRing(null);
    if (focusLat != null && focusLng != null) globe.focus(focusLat, focusLng);
  };

  const country = (feature: any) => {
    const name = featureCountryName(feature);
    const cc = featureCountryCode(feature);
    const c = featureCenter(feature);
    showCountryPanel(cc, name, c?.lat, c?.lng);
  };

  const countryByCode = (cc: string, name: string) => {
    showCountryPanel(cc, name);
  };

  // Delegated: clicking an entry in a country's strike list opens that dossier.
  body.addEventListener("click", (e) => {
    const item = (e.target as HTMLElement).closest<HTMLElement>(".strike-item[data-id]");
    if (!item) return;
    const p = pointsById().get(Number(item.dataset.id));
    if (p) strike(p);
  });

  return { close, strike, country, countryByCode };
}

/** Make the detail panel's width drag-resizable, clamped within sane limits. */
function wireResize(): void {
  const panel = $("panel");
  const handle = $("panel-resize");
  const MIN = 320;
  const MAX = 720;
  let dragging = false;
  let startX = 0;
  let startW = 0;

  handle.addEventListener("pointerdown", (e) => {
    dragging = true;
    startX = e.clientX;
    startW = panel.getBoundingClientRect().width;
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("is-resizing");
    e.preventDefault();
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    // Panel is anchored right; dragging the left edge leftwards widens it.
    const dx = startX - e.clientX;
    const max = Math.min(MAX, Math.round(window.innerWidth * 0.95));
    const width = Math.min(Math.max(startW + dx, MIN), max);
    panel.style.width = `${width}px`;
  });
  const endDrag = (e: PointerEvent) => {
    if (!dragging) return;
    dragging = false;
    if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
    document.body.classList.remove("is-resizing");
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);
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
        btn.innerHTML = spinning
          ? '<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><rect x="2" y="1" width="3.5" height="12" rx="1"/><rect x="8.5" y="1" width="3.5" height="12" rx="1"/></svg>'
          : '<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><polygon points="2,1 12,7 2,13"/></svg>';
        break;
      }
    }
  });
}

// ---- Report date picker -----------------------------------------------------

interface ReportManifest {
  dates: string[];
}

async function loadManifest(): Promise<string[]> {
  try {
    const res = await fetch(MANIFEST_URL, { cache: "no-cache" });
    if (!res.ok) return [];
    const m = (await res.json()) as ReportManifest;
    return (m.dates ?? []).sort().reverse();
  } catch {
    return [];
  }
}

function wireReportPicker(
  onSelect: (date: string | null) => void,
): { setDates: (dates: string[]) => void; setActive: (date: string | null) => void } {
  const clockBtn = $("banner-clock");
  const picker = $("report-picker");
  const listEl = $("report-picker-list");
  const latestBtn = $("btn-latest");

  let dates: string[] = [];
  let activeDate: string | null = null;
  let open = false;

  function closePicker() {
    open = false;
    picker.hidden = true;
  }

  function renderList() {
    listEl.innerHTML = "";
    for (const d of dates) {
      const btn = document.createElement("button");
      btn.className = "picker__date" + (d === activeDate ? " picker__date--active" : "");
      btn.type = "button";
      btn.textContent = formatDateLabel(d);
      btn.dataset.date = d;
      btn.addEventListener("click", () => {
        closePicker();
        onSelect(d);
      });
      listEl.appendChild(btn);
    }
  }

  clockBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    open = !open;
    picker.hidden = !open;
    if (open) renderList();
  });

  document.addEventListener("click", (e) => {
    if (open && !picker.contains(e.target as Node)) closePicker();
  });

  latestBtn.addEventListener("click", () => {
    onSelect(null);
  });

  return {
    setDates(d: string[]) {
      dates = d;
    },
    setActive(d: string | null) {
      activeDate = d;
      const isLatest = d === null || (dates.length > 0 && d === dates[0]);
      latestBtn.hidden = isLatest;
    },
  };
}

function formatDateLabel(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

// ---- Threat Intelligence HUD -----------------------------------------------

function renderThreatHud(stats: ThreatStats): void {
  const hud = document.getElementById("threat-hud");
  if (!hud) return;

  const tierLabels = ["tremor", "breach", "siege", "dominion"];
  const bars = stats.severityPct
    .map(
      (pct, i) =>
        `<div class="hud__bar-row">
          <span class="hud__bar-label tier--${tierLabels[i]}">${tierLabels[i]}</span>
          <div class="hud__bar-track"><div class="hud__bar-fill hud__bar-fill--${tierLabels[i]}" style="width:${pct.toFixed(0)}%"></div></div>
          <span class="hud__bar-val">${pct.toFixed(0)}%</span>
        </div>`,
    )
    .join("");

  const entropyLabel =
    stats.geographicEntropy > 0.7
      ? "widespread"
      : stats.geographicEntropy > 0.4
        ? "regional"
        : "concentrated";

  hud.innerHTML = `
    <div class="hud__header">
      <span class="hud__label">THREAT INDEX</span>
      <span class="hud__index hud__index--${stats.threatLabel.toLowerCase().replace(/\s/g, "-")}">${stats.threatIndex.toFixed(0)}</span>
      <span class="hud__threat-label">${esc(stats.threatLabel)}</span>
    </div>
    <div class="hud__meter">
      <div class="hud__meter-fill" style="width:${stats.threatIndex.toFixed(0)}%"></div>
    </div>
    <div class="hud__stats">
      <div class="hud__stat"><span class="hud__stat-val">${stats.totalStrikes}</span><span class="hud__stat-key">strikes</span></div>
      <div class="hud__stat"><span class="hud__stat-val">${stats.uniqueCountries}</span><span class="hud__stat-key">countries</span></div>
      <div class="hud__stat"><span class="hud__stat-val">${stats.averageSeverity.toFixed(1)}</span><span class="hud__stat-key">avg sev</span></div>
      <div class="hud__stat"><span class="hud__stat-val">${entropyLabel}</span><span class="hud__stat-key">spread</span></div>
    </div>
    <div class="hud__bars">${bars}</div>
    <div class="hud__engine">Engine: <span class="hud__engine-badge">${currentEngine().toUpperCase()}</span></div>
  `;
  hud.hidden = false;
}

// ---- Effect toggle wiring ---------------------------------------------------

interface EffectState {
  heatmapActive: boolean;
}

function wireEffectToggles(
  globe: GlobeView,
  snapshotBuffer: ArrayBuffer,
  effectState: EffectState,
): void {
  const toggles = document.getElementById("effect-toggles");
  if (!toggles) return;
  toggles.hidden = false;

  toggles.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button");
    if (!btn) return;

    if (btn.dataset.effect === "heatmap") {
      effectState.heatmapActive = !effectState.heatmapActive;
      if (effectState.heatmapActive) {
        const hm = buildHeatmap(snapshotBuffer, 2);
        if (hm) globe.renderHeatmap(hm);
      } else {
        globe.clearHeatmap();
      }
      btn.classList.toggle("effect-btn--active", effectState.heatmapActive);
    }
  });
}

async function loadReport(
  basePath: string,
  globe: GlobeView,
  panels: Panels,
  state: AppState,
): Promise<void> {
  const binUrl = `${basePath}/snapshot.bin`;
  const jsonUrl = `${basePath}/snapshot.json`;

  const snapshotRes = await fetch(binUrl, { cache: "no-cache" });
  if (!snapshotRes.ok) throw new Error(`failed to load snapshot: ${snapshotRes.status}`);
  const snapshotBuffer = await snapshotRes.arrayBuffer();

  const [rawBatch, dmap] = await Promise.all([
    Promise.resolve(buildRenderBatch(snapshotBuffer, 0)),
    loadDossiers(jsonUrl),
  ]);
  const batch = spreadBatch(rawBatch);
  state.dossiers = dmap;
  state.countryStats = aggregateByCountry(batch);
  state.pointsById = new Map(batch.points.map((p) => [p.id, p]));
  state.pulseRingMap = new Map<number, PulseRing>();
  state.snapshotBuffer = snapshotBuffer;

  globe.setSelectablePredicate((f) => {
    const cc = featureCountryCode(f);
    return !!cc && (state.countryStats.get(cc)?.total ?? 0) > 0;
  });
  globe.render(batch);
  showBanner(batch);
  buildCountryNav(state.countryStats, state.dossiers, panels);
  panels.close();

  const stats = buildThreatStats(snapshotBuffer);
  if (stats) renderThreatHud(stats);

  const rings = buildPulseRings(snapshotBuffer);
  if (rings) {
    for (const r of rings) state.pulseRingMap.set(r.id, r);
  }

  state.effectState.heatmapActive = false;
  globe.clearHeatmap();
  wireEffectToggles(globe, snapshotBuffer, state.effectState);
}

interface AppState {
  countryStats: Map<string, CountryStat>;
  dossiers: Map<number, StrikeDossier>;
  pointsById: Map<number, Point>;
  pulseRingMap: Map<number, PulseRing>;
  snapshotBuffer: ArrayBuffer | null;
  effectState: EffectState;
}

async function main(): Promise<void> {
  const tooltip = makeTooltip();
  let lastMouse = { x: 0, y: 0 };
  window.addEventListener("mousemove", (e) => (lastMouse = { x: e.clientX, y: e.clientY }));

  const state: AppState = {
    countryStats: new Map(),
    dossiers: new Map(),
    pointsById: new Map(),
    pulseRingMap: new Map(),
    snapshotBuffer: null,
    effectState: { heatmapActive: false },
  };

  let panels: Panels | null = null;
  const globe = new GlobeView($("globe"), {
    onPointHover: (p) => {
      document.body.style.cursor = p ? "pointer" : "default";
      if (!p) {
        tooltip(null, lastMouse.x, lastMouse.y);
        return;
      }
      const where = state.dossiers.get(p.id)?.location || p.country;
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
      const n = (cc && state.countryStats.get(cc)?.total) || 0;
      tooltip(COPY.country(featureCountryName(f), n), lastMouse.x, lastMouse.y);
    },
    onCountryClick: (f) => {
      if (f) panels?.country(f);
    },
  });
  panels = wirePanels(
    globe,
    () => state.countryStats,
    () => state.dossiers,
    () => state.pointsById,
    () => state.pulseRingMap,
  );

  wireControls(globe);
  wireResize();
  void loadCountries(globe);

  const engine = await initCore();
  console.info(`[app] decode engine: ${engine} (${currentEngine()})`);

  const picker = wireReportPicker(async (date) => {
    const basePath = date ? `/snapshots/${date}` : DEFAULT_SNAPSHOT_BASE;
    try {
      await loadReport(basePath, globe, panels!, state);
      picker.setActive(date);
    } catch (err) {
      console.error("[app] failed to load report", err);
    }
  });

  const dates = await loadManifest();
  picker.setDates(dates);

  try {
    await loadReport(DEFAULT_SNAPSHOT_BASE, globe, panels!, state);
  } catch (err) {
    console.error(err);
    $("banner-report").textContent = "The uprising is silent… (failed to load report)";
    $("banner").hidden = false;
  } finally {
    const loader = $("loader");
    loader.classList.add("loader--done");
    setTimeout(() => (loader.hidden = true), 900);
  }
}

void main();
