// App entry: load the latest Insurgency Report, decode it (WASM or TS fallback),
// render the globe, and wire the Halloween UI.

import { GlobeView } from "./globe";
import type { Point, RenderBatch } from "./snapshot";
import { COPY, severityLabel, sourceLabel, TIER_BLURBS } from "./theme";
import { buildRenderBatch, currentEngine, initCore } from "./wasm-loader";

const SNAPSHOT_URL =
  import.meta.env.VITE_SNAPSHOT_URL ?? "/snapshots/latest/snapshot.bin";

function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el;
}

async function loadSnapshot(): Promise<RenderBatch> {
  const res = await fetch(SNAPSHOT_URL, { cache: "no-cache" });
  if (!res.ok) throw new Error(`failed to load snapshot: ${res.status}`);
  const buffer = await res.arrayBuffer();
  return buildRenderBatch(buffer, 0);
}

function showBanner(batch: RenderBatch): void {
  const banner = $("banner");
  const report = $("banner-report");
  report.textContent =
    batch.total === 0 ? COPY.emptyState : COPY.bannerReport(batch.date, batch.total);
  banner.hidden = false;
  $("legend").hidden = false;
}

function wireTooltip(): (p: Point | null, x?: number, y?: number) => void {
  const tip = $("tooltip");
  return (p, x = 0, y = 0) => {
    if (!p) {
      tip.hidden = true;
      return;
    }
    tip.textContent = COPY.tooltip(p.country, severityLabel(p.severity));
    tip.style.left = `${x + 14}px`;
    tip.style.top = `${y + 14}px`;
    tip.hidden = false;
  };
}

function wirePanel(globe: GlobeView): (p: Point | null) => void {
  const panel = $("panel");
  const body = $("panel-body");
  $("panel-close").addEventListener("click", () => (panel.hidden = true));

  return (p) => {
    if (!p) return;
    const tier = severityLabel(p.severity);
    body.innerHTML = `
      <h2>Awakened Machine</h2>
      <p class="panel__blurb">${TIER_BLURBS[tier]}</p>
      <dl>
        <dt>Origin</dt><dd>${p.country}</dd>
        <dt>Threat tier</dt><dd class="tier tier--${tier}">${tier}</dd>
        <dt>Feed</dt><dd>${sourceLabel(p.source)}</dd>
        <dt>Cluster size</dt><dd>${p.weight} machine(s)</dd>
      </dl>`;
    panel.hidden = false;
    globe.focus(p.lat, p.lng);
  };
}

async function main(): Promise<void> {
  const setTooltip = wireTooltip();
  let lastMouse = { x: 0, y: 0 };
  window.addEventListener("mousemove", (e) => (lastMouse = { x: e.clientX, y: e.clientY }));

  let openPanel: (p: Point | null) => void = () => {};
  const globe = new GlobeView($("globe"), {
    onPointHover: (p) => {
      document.body.style.cursor = p ? "pointer" : "default";
      setTooltip(p, lastMouse.x, lastMouse.y);
    },
    onPointClick: (p) => openPanel(p),
  });
  openPanel = wirePanel(globe);

  const engine = await initCore();
  console.info(`[app] decode engine: ${engine} (${currentEngine()})`);

  try {
    const batch = await loadSnapshot();
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
