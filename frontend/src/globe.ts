// The 3D globe view (globe.gl / three.js) with the uprising skin.

import Globe from "globe.gl";
import type { Arc, Point, RenderBatch } from "./snapshot";
import { MAP, severityColor } from "./theme";

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface GlobeHandlers {
  onPointHover: (p: Point | null) => void;
  onPointClick: (p: Point | null) => void;
  onCountryHover: (feature: any | null) => void;
  onCountryClick: (feature: any | null) => void;
}

const LAND_HIGHLIGHT = "rgba(252, 185, 125, 0.55)"; // hovered incident country
const LAND_INCIDENT = "rgba(252, 185, 125, 0.22)"; // countries with incidents (selectable)

export class GlobeView {
  // globe.gl is loosely typed; keep the instance as a chainable any.
  private world: any;
  private hoverPoly: unknown = null;
  // Predicate: is this country feature selectable (has detected incidents)?
  private selectable: (f: any) => boolean = () => false;

  constructor(container: HTMLElement, handlers: GlobeHandlers) {
    this.world = new Globe(container)
      .backgroundColor("#02020a")
      .showGlobe(true)
      .showAtmosphere(true)
      .atmosphereColor("#FCB97D")
      .atmosphereAltitude(0.18)
      // Points = Awakened Machines
      .pointsData([])
      .pointLat((d: any) => (d as Point).lat)
      .pointLng((d: any) => (d as Point).lng)
      .pointColor((d: any) => severityColor((d as Point).severity))
      .pointAltitude((d: any) => 0.01 + (d as Point).severity * 0.015)
      .pointRadius((d: any) => 0.22 + (d as Point).severity * 0.07)
      .pointResolution(6)
      .onPointHover((p: any) => handlers.onPointHover((p as Point) ?? null))
      .onPointClick((p: any) => handlers.onPointClick((p as Point) ?? null))
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
      .arcAltitudeAutoScale(0.4)
      .arcStroke((d: any) => 0.3 + (d as Arc).severity * 0.15)
      .arcDashLength(0.5)
      .arcDashGap(1)
      .arcDashAnimateTime(REDUCED_MOTION ? 0 : 2200)
      // Land masses = filled country polygons raised above the ocean surface,
      // with glowing ice-cyan coastlines. This distinguishes sea from land.
      .polygonsData([])
      .polygonCapColor((d: any) => this.capColor(d))
      .polygonSideColor(() => MAP.landSide)
      .polygonStrokeColor(() => MAP.coastline)
      .polygonAltitude((d: any) => this.capAltitude(d))
      .polygonsTransitionDuration(0) // no geometry tweening -> cheap
      .onPolygonHover((f: any) => {
        // Only countries with detected incidents are selectable.
        const target = f && this.selectable(f) ? f : null;
        this.hoverPoly = target;
        // Hover only recolors (cheap); altitude stays static to avoid re-tessellation.
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
    controls.autoRotateSpeed = 0.35;
    controls.enableDamping = true;

    window.addEventListener("resize", () => this.resize(container));
    this.resize(container);
  }

  private resize(container: HTMLElement): void {
    this.world.width(container.clientWidth).height(container.clientHeight);
  }

  render(batch: RenderBatch): void {
    this.world.pointsData(batch.points).arcsData(batch.arcs);
  }

  private capColor(d: any): string {
    if (d === this.hoverPoly) return LAND_HIGHLIGHT;
    return this.selectable(d) ? LAND_INCIDENT : MAP.land;
  }

  private capAltitude(d: any): number {
    // Static, subtle lift: incident countries sit just above the rest. Altitude
    // never changes on hover, so the polygon geometry is built only once.
    return this.selectable(d) ? 0.012 : 0.006;
  }

  /** Re-apply only the cap color accessor (cheap: no geometry rebuild). */
  private refreshColors(): void {
    this.world.polygonCapColor((d: any) => this.capColor(d));
  }

  /** Re-apply color + altitude accessors (used once when selectability changes). */
  private refreshPolygons(): void {
    this.world
      .polygonCapColor((d: any) => this.capColor(d))
      .polygonAltitude((d: any) => this.capAltitude(d));
  }

  /** Draw faint continent outlines from a GeoJSON FeatureCollection. */
  setCountries(features: unknown[]): void {
    this.world.polygonsData(features);
  }

  /**
   * Set which country features are selectable (those with detected incidents).
   * Non-selectable countries are drawn for context but cannot be hovered/clicked.
   */
  setSelectablePredicate(fn: (f: any) => boolean): void {
    this.selectable = fn;
    this.refreshPolygons();
  }

  focus(lat: number, lng: number): void {
    this.world.pointOfView({ lat, lng, altitude: 1.8 }, 800);
  }

  /** Zoom by a multiplicative factor (<1 zooms in, >1 zooms out). */
  zoom(factor: number): void {
    const pov = this.world.pointOfView();
    const altitude = Math.min(Math.max(pov.altitude * factor, 0.4), 5);
    this.world.pointOfView({ ...pov, altitude }, 400);
  }

  /** Rotate the view horizontally by ``deltaDeg`` degrees of longitude. */
  spin(deltaDeg: number): void {
    const pov = this.world.pointOfView();
    this.world.pointOfView({ ...pov, lng: pov.lng + deltaDeg }, 500);
  }

  /** Toggle continuous auto-rotation. Returns the new state. */
  toggleAutoRotate(): boolean {
    const controls = this.world.controls();
    controls.autoRotate = !controls.autoRotate;
    return controls.autoRotate;
  }
}
