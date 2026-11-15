# Generated WASM output

This directory receives the compiled Rust core. First check that the Rust toolchain is
available:

```bash
command -v cargo rustc wasm-pack && rustup target list --installed | grep wasm32-unknown-unknown
# If anything is missing:
#   rustup target add wasm32-unknown-unknown
#   cargo install wasm-pack
```

Then build it:

```bash
npm run wasm
# => wasm-pack build ../rebellion-core --target web --out-dir ../frontend/src/wasm
```

That generates `rebellion_core.js` + `rebellion_core_bg.wasm`, which
`src/wasm-loader.ts` picks up through `import.meta.glob`. Vite resolves the glob at
build time, so `npm run wasm` must run **before** `npm run build`: the package is then
bundled as a lazy chunk and the `.wasm` is emitted into `dist/assets/`. If the package
is absent (`npm run wasm` did not run), the app automatically falls back to the
pure-TypeScript decoder in `src/snapshot.ts`, so the globe still renders.

The generated files are ignored by the `.gitignore` that wasm-pack writes here; this
README is the only committed file.
