// The 3D globe view (globe.gl / three.js) with the uprising skin.

import Globe from "globe.gl";
import * as THREE from "three";
import type { Arc, Point, RenderBatch } from "./snapshot";
import { MAP, severityColor } from "./theme";

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface GlobeHandlers {
  onPointHover: (p: Point | null) => void;
  onPointClick: (p: Point | null) => void;
  onCountryHover: (feature: any | null) => void;
  onCountryClick: (feature: any | null) => void;
}

const HOVER_RED = "#a31919";
const LAND_HIGHLIGHT = "rgba(214, 69, 69, 0.8)";
const LAND_INCIDENT = "rgba(252, 185, 125, 0.22)";

const GLOBE_RADIUS = 100;
const MIN_ALTITUDE = 0.7;
const MAX_ALTITUDE = 3.0;

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
  private selectable: (f: any) => boolean = () => false;
  private pinGroups = new Map<number, THREE.Group>();

  constructor(container: HTMLElement, handlers: GlobeHandlers) {
    this.world = new Globe(container)
      .backgroundColor("#02020a")
      .showGlobe(true)
      .showAtmosphere(true)
      .atmosphereColor("#FCB97D")
      .atmosphereAltitude(0.18)
      // Pins = Awakened Machines (custom three.js: shaft + tip sphere)
      .customLayerData([])
      .customThreeObject((d: any) => {
        const p = d as Point;
        const pin = buildPin(p.severity, severityColor(p.severity));
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
        if (prevD) {
          const prev = prevD as Point;
          const pin = this.pinGroups.get(prev.id);
          if (pin) recolorPin(pin, severityColor(prev.severity));
        }
        const p = d ? (d as Point) : null;
        if (p) {
          const pin = this.pinGroups.get(p.id);
          if (pin) recolorPin(pin, HOVER_RED);
        }
        handlers.onPointHover(p);
      })
      .onCustomLayerClick((d: any) => {
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

  render(batch: RenderBatch): void {
    this.pinGroups.clear();
    this.world.customLayerData(batch.points).arcsData(batch.arcs);
  }

  private capColor(d: any): string {
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
