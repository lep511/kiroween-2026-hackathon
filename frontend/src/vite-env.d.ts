/// <reference types="vite/client" />

// The Rust/WASM package is generated at build time by `npm run wasm`. It may be
// absent (no Rust toolchain), so declare it loosely and load it dynamically.
declare module "*/rebellion_core.js";
