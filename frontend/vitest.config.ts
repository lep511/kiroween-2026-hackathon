import { defineConfig } from "vitest/config";

// Unit tests cover the pure history/transition logic and the integrity of the committed
// report archive (frontend/public/snapshots/). They run in Node: no DOM, no WebGL.
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
