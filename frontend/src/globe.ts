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

// Hover feedback is red, distinct from the warm severity palette, so the report under
// the pointer clearly stands out. The hovered *country* fill is a lighter, clearer red
// than the dark red used on the report selector (#a31919) so the two reads don't clash.
const HOVER_RED = "#a31919"; // dark red (points when hovered)
const LAND_HIGHLIGHT = "rgba(214, 69, 69, 0.8)"; // hovered incident country -> lighter red
const LAND_INCIDENT = "rgba(252, 185, 125, 0.22)"; // countries with incidents (selectable)

// Zoom bounds (globe.gl world units; the globe radius is 100). These clamp both the
// +/- buttons and mouse-wheel/trackpad zoom so the map can't be pushed too far out
// or dived in too close.
const GLOBE_RADIUS = 100;
const MIN_ALTITUDE = 0.7; // closest allowed (don't zoom in so much)
const MAX_ALTITUDE = 3.0; // farthest allowed (don't zoom out so much)

export class GlobeView {
  // globe.gl is loosely typed; keep the instance as a chainable any.
  private world: any;
  private hoverPoly: unknown = null;
  private hoverPoint: unknown = null;
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
      .pointColor((d: any) => this.pointColorFor(d))
      .pointAltitude((d: any) => 0.02 + (d as Point).severity * 0.02)
      // Bigger, smoother points: far easier to hover and click on the globe.
      .pointRadius((d: any) => 0.5 + (d as Point).severity * 0.14)
      .pointResolution(12)
      .onPointHover((p: any) => {
        // Recolor the hovered point dark red so it reads as "selected".
        this.hoverPoint = (p as Point) ?? null;
        this.refreshPointColors();
        handlers.onPointHover((p as Point) ?? null);
      })
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
    // Clamp wheel/trackpad zoom to the same altitude band as the +/- buttons.
    controls.minDistance = GLOBE_RADIUS * (1 + MIN_ALTITUDE);
    controls.maxDistance = GLOBE_RADIUS * (1 + MAX_ALTITUDE);

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

  /** A strike point's color: dark red while hovered, else its severity tier color. */
  private pointColorFor(d: any): string {
    if (d === this.hoverPoint) return HOVER_RED;
    return severityColor((d as Point).severity);
  }

  /** Re-apply only the point color accessor (cheap: used on hover). */
  private refreshPointColors(): void {
    this.world.pointColor((d: any) => this.pointColorFor(d));
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
    const altitude = Math.min(
      Math.max(pov.altitude * factor, MIN_ALTITUDE),
      MAX_ALTITUDE,
    );
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
