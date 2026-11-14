#!/bin/sh
# Stage the Lambda code for `sam build` in infra/.build/lambda/ (gitignored).
#
# The folder holds the `pipeline` package without its tests or bytecode (the runtime
# data files pipeline/fixtures/curated_incidents.json and pipeline/countries.csv are
# kept) and pipeline/requirements.txt at its root, so the SAM python3.12 builder installs
# the runtime dependencies. Every function in infra/template.yaml uses
# CodeUri: .build/lambda. Run this script before `sam build`.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
build_root="$script_dir/.build"
out="$build_root/lambda"

# Only ever remove the generated folder under infra/.build/.
rm -rf -- "$out"
mkdir -p -- "$out/pipeline"

(
    cd -- "$repo_root/pipeline"
    find . -path ./tests -prune -o -name __pycache__ -prune -o -type f ! -name '*.pyc' -print
) | while IFS= read -r rel; do
    mkdir -p -- "$out/pipeline/$(dirname -- "$rel")"
    cp -- "$repo_root/pipeline/$rel" "$out/pipeline/$rel"
done

cp -- "$repo_root/pipeline/requirements.txt" "$out/requirements.txt"

echo "Lambda code staged in $out"
