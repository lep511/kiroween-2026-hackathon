# Generated WASM output

This directory receives the compiled Rust core. It is produced by:

```bash
npm run wasm
# => wasm-pack build ../rebellion-core --target web --out-dir ../frontend/src/wasm
```

That generates `rebellion_core.js` + `rebellion_core_bg.wasm`, which
`src/wasm-loader.ts` imports dynamically. If the package is absent (no Rust
toolchain), the app automatically falls back to the pure-TypeScript decoder in
`src/snapshot.ts`, so the globe still renders.

The generated files are gitignored; this README is the only committed file here.
