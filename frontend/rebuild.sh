#!/usr/bin/env bash
# rebuild.sh — Full pipeline to update the site from scratch.
#
# Steps:
#   1. Rust: test, lint, format
#   2. WASM: build the rebellion-core package into src/wasm
#   3. Node: install dependencies (if needed)
#   4. TypeScript: type-check
#   5. Vite: production build -> dist/
#
# Usage:
#   cd frontend && bash rebuild.sh        # full rebuild
#   bash rebuild.sh --skip-rust           # skip Rust checks (WASM still builds)
#   bash rebuild.sh --dev                 # start dev server instead of prod build

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORE_DIR="$REPO_ROOT/rebellion-core"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${CYAN}▸ $1${NC}"; }
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

SKIP_RUST=false
DEV_MODE=false

for arg in "$@"; do
  case "$arg" in
    --skip-rust) SKIP_RUST=true ;;
    --dev)       DEV_MODE=true ;;
    -h|--help)
      echo "Usage: rebuild.sh [--skip-rust] [--dev]"
      echo "  --skip-rust   Skip Rust tests/lint (WASM still builds)"
      echo "  --dev         Start dev server instead of production build"
      exit 0
      ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# ---- 0. Preflight: check required tools ------------------------------------

step "Preflight checks"

command -v cargo   >/dev/null 2>&1 || fail "cargo not found — install Rust toolchain"
command -v wasm-pack >/dev/null 2>&1 || fail "wasm-pack not found — cargo install wasm-pack"
command -v node    >/dev/null 2>&1 || fail "node not found"
command -v npm     >/dev/null 2>&1 || fail "npm not found"

ok "cargo $(cargo --version | awk '{print $2}')"
ok "wasm-pack $(wasm-pack --version | awk '{print $2}')"
ok "node $(node --version)"

# ---- 1. Rust checks --------------------------------------------------------

if [ "$SKIP_RUST" = false ]; then
  step "Rust: format check"
  (cd "$CORE_DIR" && cargo fmt --check) || fail "cargo fmt failed — run: cargo fmt"
  ok "formatted"

  step "Rust: clippy"
  (cd "$CORE_DIR" && cargo clippy --all-targets -- -D warnings 2>&1) || fail "clippy warnings"
  ok "no warnings"

  step "Rust: tests"
  (cd "$CORE_DIR" && cargo test 2>&1) || fail "tests failed"
  ok "all tests passed"
else
  warn "Skipping Rust checks (--skip-rust)"
fi

# ---- 2. WASM build ---------------------------------------------------------

step "WASM: building rebellion-core"
(cd "$REPO_ROOT" && wasm-pack build rebellion-core --target web --out-dir ../frontend/src/wasm 2>&1) \
  || fail "wasm-pack build failed"
ok "rebellion-core WASM package ready"

# ---- 3. Node dependencies ---------------------------------------------------

step "Node: checking dependencies"
cd "$SCRIPT_DIR"

if [ ! -d node_modules ] || [ package.json -nt node_modules/.package-lock.json ]; then
  npm install 2>&1 || fail "npm install failed"
  ok "dependencies installed"
else
  ok "node_modules up to date"
fi

# ---- 4. TypeScript type-check -----------------------------------------------

step "TypeScript: type-check"
npx tsc --noEmit 2>&1 || fail "type errors found"
ok "no type errors"

# ---- 5. Build or dev --------------------------------------------------------

if [ "$DEV_MODE" = true ]; then
  step "Starting dev server"
  exec npm run dev
else
  step "Vite: production build"
  npm run build 2>&1 || fail "build failed"

  DIST="$SCRIPT_DIR/dist"
  WASM_SIZE=$(du -sh "$DIST"/assets/*.wasm 2>/dev/null | awk '{print $1}')
  JS_SIZE=$(du -sh "$DIST"/assets/index-*.js 2>/dev/null | awk '{print $1}')
  CSS_SIZE=$(du -sh "$DIST"/assets/index-*.css 2>/dev/null | awk '{print $1}')

  echo ""
  echo -e "${GREEN}Build complete → dist/${NC}"
  echo -e "  WASM: ${WASM_SIZE:-n/a}  JS: ${JS_SIZE:-n/a}  CSS: ${CSS_SIZE:-n/a}"
fi
