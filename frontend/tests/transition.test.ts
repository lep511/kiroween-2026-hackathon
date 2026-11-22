import { describe, expect, it } from "vitest";
import {
  easeInCubic,
  easeOutBack,
  ENTER_PIN_MS,
  enterOrder,
  enterScale,
  EXIT_MS,
  exitScale,
  type FrameClock,
  MAX_STAGGER_MS,
  runTween,
  staggerDelay,
} from "../src/transition";

/** Deterministic frame clock: frames run only when the test advances time. */
function fakeClock() {
  let t = 0;
  let nextId = 1;
  const queue = new Map<number, (time: number) => void>();
  const clock: FrameClock & { advance(ms: number): void; pending(): number } = {
    now: () => t,
    request: (cb) => {
      const id = nextId++;
      queue.set(id, cb);
      return id;
    },
    cancel: (id) => {
      queue.delete(id);
    },
    advance(ms) {
      t += ms;
      const due = [...queue.values()];
      queue.clear();
      for (const cb of due) cb(t);
    },
    pending: () => queue.size,
  };
  return clock;
}

const samples = (n: number, max: number) =>
  Array.from({ length: n + 1 }, (_, i) => (i / n) * max);

describe("easing", () => {
  it("starts at exactly 0 and ends at exactly 1", () => {
    expect(easeInCubic(0)).toBe(0);
    expect(easeInCubic(1)).toBe(1);
    expect(easeOutBack(0)).toBe(0);
    expect(easeOutBack(1)).toBe(1);
  });

  it("clamps progress outside [0, 1]", () => {
    expect(easeInCubic(-1)).toBe(0);
    expect(easeInCubic(2)).toBe(1);
    expect(easeOutBack(-1)).toBe(0);
    expect(easeOutBack(2)).toBe(1);
  });

  it("overshoots by at most 10% on the way in", () => {
    const peak = Math.max(...samples(1000, 1).map(easeOutBack));
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(1.1);
  });
});

describe("exitScale", () => {
  it("shrinks monotonically from the starting scale to 0", () => {
    const values = samples(60, EXIT_MS).map((t) => exitScale(t));
    expect(values[0]).toBe(1);
    expect(values[values.length - 1]).toBe(0);
    for (let i = 1; i < values.length; i++) expect(values[i]).toBeLessThanOrEqual(values[i - 1]);
  });

  it("starts from a partial scale when a transition was interrupted", () => {
    expect(exitScale(0, 0.4)).toBeCloseTo(0.4);
    expect(exitScale(EXIT_MS, 0.4)).toBe(0);
  });

  it("stays at 0 after the exit", () => {
    expect(exitScale(EXIT_MS * 3)).toBe(0);
  });
});

describe("staggerDelay", () => {
  it("is 0 when there is at most one pin", () => {
    expect(staggerDelay(0, 0)).toBe(0);
    expect(staggerDelay(0, 1)).toBe(0);
  });

  it("spreads pins evenly within the stagger budget", () => {
    const n = 44;
    const delays = Array.from({ length: n }, (_, i) => staggerDelay(i, n));
    expect(delays[0]).toBe(0);
    expect(delays[n - 1]).toBe(MAX_STAGGER_MS);
    for (const d of delays) {
      expect(d).toBeGreaterThanOrEqual(0);
      expect(d).toBeLessThanOrEqual(MAX_STAGGER_MS);
    }
  });

  it("clamps out-of-range indexes", () => {
    expect(staggerDelay(-3, 5)).toBe(0);
    expect(staggerDelay(99, 5)).toBe(MAX_STAGGER_MS);
  });
});

describe("enterScale", () => {
  it("is 0 until the pin's delay has passed", () => {
    expect(enterScale(0, 100)).toBe(0);
    expect(enterScale(100, 100)).toBe(0);
  });

  it("ends at exactly 1 and stays there", () => {
    expect(enterScale(100 + ENTER_PIN_MS, 100)).toBe(1);
    expect(enterScale(10_000, 100)).toBe(1);
  });

  it("never grows past a 10% overshoot", () => {
    for (const t of samples(500, ENTER_PIN_MS)) {
      expect(enterScale(t, 0)).toBeGreaterThanOrEqual(0);
      expect(enterScale(t, 0)).toBeLessThanOrEqual(1.1);
    }
  });
});

describe("enterOrder", () => {
  it("puts the highest severity first, then the lowest id", () => {
    const order = enterOrder([
      { id: 1, severity: 0 },
      { id: 2, severity: 3 },
      { id: 3, severity: 2 },
      { id: 4, severity: 3 },
    ]);
    expect([...order.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id)).toEqual([
      2, 4, 3, 1,
    ]);
  });

  it("is empty for an empty report", () => {
    expect(enterOrder([]).size).toBe(0);
  });
});

describe("runTween", () => {
  it("runs frames until the duration and resolves true", async () => {
    const clock = fakeClock();
    const frames: number[] = [];
    const tween = runTween(300, (t) => frames.push(t), clock);
    clock.advance(100);
    clock.advance(100);
    clock.advance(150);
    clock.advance(100);
    await expect(tween.done).resolves.toBe(true);
    expect(frames).toEqual([0, 100, 200, 300]);
    expect(clock.pending()).toBe(0);
  });

  it("stops on cancel and resolves false", async () => {
    const clock = fakeClock();
    const frames: number[] = [];
    const tween = runTween(300, (t) => frames.push(t), clock);
    clock.advance(100);
    tween.cancel();
    clock.advance(500);
    await expect(tween.done).resolves.toBe(false);
    expect(frames).toEqual([0, 100]);
    expect(clock.pending()).toBe(0);
  });

  it("ignores cancel after completion", async () => {
    const clock = fakeClock();
    const tween = runTween(50, () => {}, clock);
    clock.advance(60);
    tween.cancel();
    await expect(tween.done).resolves.toBe(true);
  });

  it("finishes at once for a zero duration", async () => {
    const clock = fakeClock();
    const frames: number[] = [];
    const tween = runTween(0, (t) => frames.push(t), clock);
    await expect(tween.done).resolves.toBe(true);
    expect(frames).toEqual([0]);
    expect(clock.pending()).toBe(0);
  });
});
