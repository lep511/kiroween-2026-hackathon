// The 3D globe view (globe.gl / three.js) with the uprising skin.

import Globe from "globe.gl";
import type { Arc, Point, RenderBatch } from "./snapshot";
import { severityColor } from "./theme";

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface GlobeHandlers {
  onPointHover: (p: Point | null) => void;
  onPointClick: (p: Point | null) => void;
}

export class GlobeView {
  // globe.gl is loosely typed; keep the instance as a chainable any.
  private world: any;

  constructor(container: HTMLElement, handlers: GlobeHandlers) {
    this.world = new Globe(container)
      .backgroundColor("#02020a")
      .showGlobe(true)
      .showAtmosphere(true)
      .atmosphereColor("#ff1744")
      .atmosphereAltitude(0.18)
      // Points = Awakened Machines
      .pointsData([])
      .pointLat((d: any) => (d as Point).lat)
      .pointLng((d: any) => (d as Point).lng)
      .pointColor((d: any) => severityColor((d as Point).severity))
      .pointAltitude((d: any) => 0.01 + (d as Point).severity * 0.015)
      .pointRadius((d: any) => 0.18 + Math.min((d as Point).weight, 8) * 0.04)
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
      .arcDashAnimateTime(REDUCED_MOTION ? 0 : 2200);

    // Near-black "possessed" globe surface.
    const mat = this.world.globeMaterial();
    mat.color.set("#0a0a16");
    mat.emissive.set("#140018");
    mat.emissiveIntensity = 0.35;

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

  focus(lat: number, lng: number): void {
    this.world.pointOfView({ lat, lng, altitude: 1.8 }, 800);
  }
}
