// The 3D globe view (globe.gl / three.js) with the uprising skin.

import Globe from "globe.gl";
import * as THREE from "three";
import type { Arc, Point, RenderBatch } from "./snapshot";
import type { HeatPoint, PulseRing } from "./wasm-loader";
import { MAP, severityColor } from "./theme";
import {
  ENTER_ARC_MS,
  ENTER_TOTAL_MS,
  enterOrder,
  enterScale,
  EXIT_MS,
  exitScale,
  runTween,
  staggerDelay,
  type Tween,
} from "./transition";

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface GlobeHandlers {
  onPointHover: (p: Point | null) => void;
  onPointClick: (p: Point | null) => void;
  onCountryHover: (feature: any | null) => void;
  onCountryClick: (feature: any | null) => void;
}

const LAND_HIGHLIGHT = "rgba(214, 69, 69, 0.8)";
// Shared by selected countries (as rgba) and selected pins (as hex) so they match.
const SELECTED_RED = "#a31919";
const LAND_SELECTED = "rgba(163, 25, 25, 0.9)";
const LAND_INCIDENT = "rgba(255, 122, 0, 0.22)";

const GLOBE_RADIUS = 100;
const MIN_ALTITUDE = 0.7;
const MAX_ALTITUDE = 3.0;

// Arc height relative to its length; ARC_FLAT lays an arc on the surface (three-globe
// grows new arcs from the same value).
const ARC_AUTO_SCALE = 0.4;
const ARC_FLAT = -1e-3;

// ---- Pin geometry (shared across all pins) --------------------------------

const SHAFT_GEO = new THREE.CylinderGeometry(0.35, 0.35, 1, 6);
const TIP_GEO = new THREE.SphereGeometry(1.6, 10, 8);

function pinHeight(severity: number): number {
  return 4 + severity * 4;
}

function buildPin(severity: number, color: string): THREE.Group {
  const h = pinHeight(severity);
  const mat = new THREE.MeshBasicMaterial({ color });

  const group = new THREE.Group();

  const shaft = new THREE.Mesh(SHAFT_GEO, mat);
  shaft.scale.y = h;
  shaft.position.y = h / 2;
  group.add(shaft);

  const tip = new THREE.Mesh(TIP_GEO, mat);
  tip.position.y = h;
  group.add(tip);

  return group;
}

function recolorPin(pin: THREE.Group, color: string): void {
  pin.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      ((child as THREE.Mesh).material as THREE.MeshBasicMaterial).color.set(
        color,
      );
    }
  });
}

// ---- GlobeView -------------------------------------------------------------

export class GlobeView {
  private world: any;
  private hoverPoly: unknown = null;
  private isSelectedCountry: ((f: any) => boolean) | null = null;
  private selectable: (f: any) => boolean = () => false;
  private pinGroups = new Map<number, THREE.Group>();
  private selectedId: number | null = null;
  private lastSelectedSeverity = 0;
  private readonly handlers: GlobeHandlers;
  // Report-change transition state (see transitionTo).
  private transitioning = false;
  private transitionId = 0;
  private activeTween: Tween | null = null;
  private enterPlan: Map<number, number> | null = null;
  private hasMarkers = false;

  constructor(container: HTMLElement, handlers: GlobeHandlers) {
    this.handlers = handlers;
    this.world = new Globe(container)
      .backgroundColor("#0e1410")
      .showGlobe(true)
      .showAtmosphere(true)
      .atmosphereColor("#FF7A00")
      .atmosphereAltitude(0.22)
      // Pins = Awakened Machines (custom three.js: shaft + tip sphere)
      .customLayerData([])
      .customThreeObject((d: any) => {
        const p = d as Point;
        const pin = buildPin(p.severity, severityColor(p.severity));
        // During a report change new pins start buried and emerge in transitionTo.
        if (this.enterPlan) pin.scale.setScalar(0);
        this.pinGroups.set(p.id, pin);
        return pin;
      })
      .customThreeObjectUpdate((obj: any, d: any) => {
        const p = d as Point;
        const coords = this.world.getCoords(p.lat, p.lng, 0);
        obj.position.set(coords.x, coords.y, coords.z);
        const up = new THREE.Vector3(
          coords.x,
          coords.y,
          coords.z,
        ).normalize();
        obj.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), up);
      })
      .onCustomLayerHover((d: any, prevD: any) => {
        // Pins are sinking or emerging: no recolor, no tooltip until the swap settles.
        if (this.transitioning) return;
        if (prevD) {
          const prev = prevD as Point;
          if (prev.id !== this.selectedId) {
            const pin = this.pinGroups.get(prev.id);
            if (pin) recolorPin(pin, severityColor(prev.severity));
          }
        }
        const p = d ? (d as Point) : null;
        if (p) {
          const pin = this.pinGroups.get(p.id);
          if (pin) recolorPin(pin, SELECTED_RED);
        }
        handlers.onPointHover(p);
      })
      .onCustomLayerClick((d: any) => {
        if (this.transitioning) return;
        handlers.onPointClick((d as Point) ?? null);
      })
      // Arcs = Assault Vectors
      .arcsData([])
      .arcStartLat((d: any) => (d as Arc).startLat)
      .arcStartLng((d: any) => (d as Arc).startLng)
      .arcEndLat((d: any) => (d as Arc).endLat)
      .arcEndLng((d: any) => (d as Arc).endLng)
      .arcColor((d: any) => {
        const c = severityColor((d as Arc).severity);
        return [c, "rgba(2,2,10,0)"];
      })
      .arcAltitudeAutoScale(ARC_AUTO_SCALE)
      .arcStroke((d: any) => 0.3 + (d as Arc).severity * 0.15)
      .arcDashLength(0.5)
      .arcDashGap(1)
      .arcDashAnimateTime(REDUCED_MOTION ? 0 : 2200)
      .arcsTransitionDuration(REDUCED_MOTION ? 0 : ENTER_ARC_MS)
      // Pulse rings — expanding concentric halos from each strike (WASM-computed)
      .ringsData([])
      .ringLat((d: any) => d.lat)
      .ringLng((d: any) => d.lng)
      .ringMaxRadius((d: any) => d.maxRadius)
      .ringPropagationSpeed((d: any) => d.propagationSpeed)
      .ringRepeatPeriod((d: any) => d.repeatPeriod)
      .ringColor((d: any) => `rgba(${d.colorR},${d.colorG},${d.colorB},${d.colorA})`)
      .ringAltitude((d: any) => d.altitude)
      // Heatmap overlay — WASM-computed Gaussian threat density
      .pointsData([])
      .pointLat((d: any) => d.lat)
      .pointLng((d: any) => d.lng)
      .pointAltitude((d: any) => 0.001 + d.weight * 0.03)
      .pointRadius((d: any) => 0.3 + d.weight * 0.6)
      .pointColor((d: any) => {
        const w = (d as HeatPoint).weight;
        if (w > 0.7) return "rgba(198,117,133,0.55)";
        if (w > 0.4) return "rgba(255,122,0,0.4)";
        return "rgba(207,190,137,0.25)";
      })
      .pointsMerge(true)
      // Land masses = filled country polygons raised above the ocean surface,
      // with glowing ice-cyan coastlines. This distinguishes sea from land.
      .polygonsData([])
      .polygonCapColor((d: any) => this.capColor(d))
      .polygonSideColor(() => MAP.landSide)
      .polygonStrokeColor(() => MAP.coastline)
      .polygonAltitude((d: any) => this.capAltitude(d))
      .polygonsTransitionDuration(0)
      .onPolygonHover((f: any) => {
        const target = f && this.selectable(f) ? f : null;
        this.hoverPoly = target;
        this.refreshColors();
        handlers.onCountryHover(target);
      })
      .onPolygonClick((f: any) =>
        handlers.onCountryClick(f && this.selectable(f) ? f : null),
      );

    // Ocean = near-black cold surface (so land and neon arcs stand out).
    const mat = this.world.globeMaterial();
    mat.color.set(MAP.ocean);
    mat.emissive.set(MAP.oceanEmissive);
    mat.emissiveIntensity = 0.3;

    // Slow, ominous auto-rotation (disabled under reduced motion).
    const controls = this.world.controls();
    controls.autoRotate = !REDUCED_MOTION;
    controls.autoRotateSpeed = 0.175;
    controls.enableDamping = true;
    controls.minDistance = GLOBE_RADIUS * (1 + MIN_ALTITUDE);
    controls.maxDistance = GLOBE_RADIUS * (1 + MAX_ALTITUDE);

    window.addEventListener("resize", () => this.resize(container));
    this.resize(container);
  }

  private resize(container: HTMLElement): void {
    this.world.width(container.clientWidth).height(container.clientHeight);
  }

  /** Swap the markers instantly (used under reduced motion). */
  render(batch: RenderBatch): void {
    this.cancelTransition();
    this.enterPlan = null;
    this.transitioning = false;
    this.pinGroups.clear();
    this.hasMarkers = batch.points.length > 0 || batch.arcs.length > 0;
    this.world
      .arcAltitudeAutoScale(ARC_AUTO_SCALE)
      .customLayerData(batch.points)
      .arcsData(batch.arcs);
  }

  /**
   * Replace the shown report with `batch`: the current pins sink and the arcs flatten,
   * then `onSwap` runs (app state + UI) and the markers are swapped, then the new pins
   * emerge staggered (highest severity first) while the new arcs grow. Starting another
   * transition cancels this one: it resolves false and, if still in its exit phase,
   * never calls `onSwap`. Under reduced motion the swap is instant.
   */
  async transitionTo(batch: RenderBatch, onSwap: () => void): Promise<boolean> {
    this.cancelTransition();
    const id = ++this.transitionId;
    const superseded = () => id !== this.transitionId;

    if (REDUCED_MOTION) {
      onSwap();
      this.render(batch);
      return true;
    }

    this.transitioning = true;
    this.handlers.onPointHover(null);

    // Exit: sink every pin from its current scale (a transition may have been cut short).
    if (this.hasMarkers) {
      const from = new Map<number, number>();
      for (const [pid, pin] of this.pinGroups) from.set(pid, pin.scale.x);
      this.world.arcsTransitionDuration(EXIT_MS).arcAltitudeAutoScale(ARC_FLAT);
      const exited = await this.play(EXIT_MS, (t) => {
        for (const [pid, pin] of this.pinGroups) {
          pin.scale.setScalar(exitScale(t, from.get(pid) ?? 0));
        }
      });
      if (!exited || superseded()) return false;
    }

    // Swap: state and UI change together with the markers (ids are per report).
    onSwap();
    const order = enterOrder(batch.points);
    this.enterPlan = order;
    this.pinGroups.clear();
    this.hasMarkers = batch.points.length > 0 || batch.arcs.length > 0;
    this.world
      .arcAltitudeAutoScale(ARC_AUTO_SCALE)
      .arcsTransitionDuration(ENTER_ARC_MS)
      .customLayerData(batch.points)
      .arcsData(batch.arcs);

    // Enter: three-globe builds the pins on its next digest, so look them up per frame.
    const count = order.size;
    if (count > 0) {
      const entered = await this.play(ENTER_TOTAL_MS, (t) => {
        for (const [pid, pin] of this.pinGroups) {
          const index = order.get(pid);
          pin.scale.setScalar(index === undefined ? 1 : enterScale(t, staggerDelay(index, count)));
        }
      });
      if (!entered || superseded()) return false;
    }

    for (const pin of this.pinGroups.values()) pin.scale.setScalar(1);
    this.enterPlan = null;
    this.transitioning = false;
    return true;
  }

  private play(durationMs: number, onFrame: (elapsedMs: number) => void): Promise<boolean> {
    const tween = runTween(durationMs, onFrame);
    this.activeTween = tween;
    return tween.done.finally(() => {
      if (this.activeTween === tween) this.activeTween = null;
    });
  }

  private cancelTransition(): void {
    this.activeTween?.cancel();
    this.activeTween = null;
  }

  selectPin(point: Point | null): void {
    if (this.selectedId != null) {
      const prev = this.pinGroups.get(this.selectedId);
      if (prev) recolorPin(prev, severityColor(this.lastSelectedSeverity));
    }
    if (point) {
      this.selectedId = point.id;
      this.lastSelectedSeverity = point.severity;
      const pin = this.pinGroups.get(point.id);
      if (pin) recolorPin(pin, SELECTED_RED);
    } else {
      this.selectedId = null;
    }
  }

  showPulseRing(ring: PulseRing | null): void {
    this.world.ringsData(ring ? [ring] : []);
  }

  renderHeatmap(points: HeatPoint[]): void {
    this.world.pointsData(points);
  }

  clearHeatmap(): void {
    this.world.pointsData([]);
  }

  private capColor(d: any): string {
    if (this.isSelectedCountry?.(d)) return LAND_SELECTED;
    if (d === this.hoverPoly) return LAND_HIGHLIGHT;
    return this.selectable(d) ? LAND_INCIDENT : MAP.land;
  }

  private capAltitude(d: any): number {
    return this.selectable(d) ? 0.012 : 0.006;
  }

  private refreshColors(): void {
    this.world.polygonCapColor((d: any) => this.capColor(d));
  }

  private refreshPolygons(): void {
    this.world
      .polygonCapColor((d: any) => this.capColor(d))
      .polygonAltitude((d: any) => this.capAltitude(d));
  }

  /** Keep the matching country highlighted until called again with null. */
  selectCountry(match: ((f: any) => boolean) | null): void {
    this.isSelectedCountry = match;
    this.refreshColors();
  }

  setCountries(features: unknown[]): void {
    this.world.polygonsData(features);
  }

  setSelectablePredicate(fn: (f: any) => boolean): void {
    this.selectable = fn;
    this.refreshPolygons();
  }

  focus(lat: number, lng: number): void {
    this.world.pointOfView({ lat, lng, altitude: 1.8 }, 800);
  }

  zoom(factor: number): void {
    const pov = this.world.pointOfView();
    const altitude = Math.min(
      Math.max(pov.altitude * factor, MIN_ALTITUDE),
      MAX_ALTITUDE,
    );
    this.world.pointOfView({ ...pov, altitude }, 400);
  }

  spin(deltaDeg: number): void {
    const pov = this.world.pointOfView();
    this.world.pointOfView({ ...pov, lng: pov.lng + deltaDeg }, 500);
  }

  toggleAutoRotate(): boolean {
    const controls = this.world.controls();
    controls.autoRotate = !controls.autoRotate;
    return controls.autoRotate;
  }
}
