// Report-change animation: easing and per-pin scale math, plus a cancelable tween
// runner. Pure apart from the default frame clock, so it is unit-tested in Node
// (tests/transition.test.ts). GlobeView.transitionTo drives the globe with it.

/** Current pins sink and current arcs flatten. */
export const EXIT_MS = 450;
/** One new pin emerging from the surface. */
export const ENTER_PIN_MS = 450;
/** Delay of the last pin to emerge (the first one starts at once). */
export const MAX_STAGGER_MS = 300;
/** New arcs growing out of the ground. */
export const ENTER_ARC_MS = 900;
/** Length of the whole pin enter phase. */
export const ENTER_TOTAL_MS = ENTER_PIN_MS + MAX_STAGGER_MS;

const clamp01 = (t: number) => Math.min(1, Math.max(0, t));

export function easeInCubic(t: number): number {
  const x = clamp01(t);
  return x * x * x;
}

// "Back" easing: overshoots by just under 10% (peak ≈ 1.0998) before settling at 1.
// The textbook constant 1.70158 peaks a hair above 1.1.
const BACK_C1 = 1.7;
const BACK_C3 = BACK_C1 + 1;

export function easeOutBack(t: number): number {
  const x = clamp01(t);
  if (x === 0) return 0;
  if (x === 1) return 1;
  return 1 + BACK_C3 * (x - 1) ** 3 + BACK_C1 * (x - 1) ** 2;
}

/** Scale of a sinking pin, from `from` (its scale when the exit began) down to 0. */
export function exitScale(elapsed: number, from = 1): number {
  return Math.max(0, from * (1 - easeInCubic(elapsed / EXIT_MS)));
}

/** Start delay of the pin at `index` (enter order) among `count` pins. */
export function staggerDelay(index: number, count: number): number {
  if (count <= 1) return 0;
  const i = Math.min(Math.max(index, 0), count - 1);
  return (i / (count - 1)) * MAX_STAGGER_MS;
}

/** Scale of an emerging pin: 0 until `delay`, then up to exactly 1. */
export function enterScale(elapsed: number, delay: number): number {
  if (elapsed <= delay) return 0;
  return easeOutBack((elapsed - delay) / ENTER_PIN_MS);
}

/** Enter position of every strike id: highest severity first, then lowest id. */
export function enterOrder(
  points: readonly { id: number; severity: number }[],
): Map<number, number> {
  const sorted = [...points].sort((a, b) => b.severity - a.severity || a.id - b.id);
  return new Map(sorted.map((p, i) => [p.id, i]));
}

// ---- Tween runner -----------------------------------------------------------

export interface FrameClock {
  now(): number;
  request(cb: (time: number) => void): number;
  cancel(id: number): void;
}

export interface Tween {
  /** Resolves true once the last frame ran, false if canceled first. */
  done: Promise<boolean>;
  cancel(): void;
}

const browserClock: FrameClock = {
  now: () => performance.now(),
  request: (cb) => requestAnimationFrame(cb),
  cancel: (id) => cancelAnimationFrame(id),
};

/**
 * Call `onFrame(elapsedMs)` on every animation frame for `durationMs`. The first frame
 * runs synchronously with 0 and the last one with exactly `durationMs`.
 */
export function runTween(
  durationMs: number,
  onFrame: (elapsedMs: number) => void,
  clock: FrameClock = browserClock,
): Tween {
  let handle: number | null = null;
  let settled = false;
  let resolve!: (completed: boolean) => void;
  const done = new Promise<boolean>((r) => (resolve = r));
  const start = clock.now();

  const settle = (completed: boolean) => {
    if (settled) return;
    settled = true;
    if (handle !== null) clock.cancel(handle);
    handle = null;
    resolve(completed);
  };

  const frame = () => {
    handle = null;
    if (settled) return;
    const elapsed = Math.min(Math.max(clock.now() - start, 0), Math.max(durationMs, 0));
    onFrame(elapsed);
    if (elapsed >= durationMs) settle(true);
    else handle = clock.request(frame);
  };

  frame();
  return { done, cancel: () => settle(false) };
}
