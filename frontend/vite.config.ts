import { defineConfig } from "vite";

// The WASM package (built by wasm-pack into src/wasm) ships a .wasm asset that
// Vite must treat as an asset/allow to be fetched. `fs.allow` lets dev serve it.
export default defineConfig({
  server: { fs: { allow: [".."] } },
  build: { target: "es2022" },
  // Default base is "/"; override with VITE_BASE when hosting under a sub-path.
  base: process.env.VITE_BASE ?? "/",
});
