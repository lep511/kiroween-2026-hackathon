#!/usr/bin/env bash
# Sync the Rebellion Timeline archive (dated Insurgency Reports) from the snapshot
# bucket into frontend/public/snapshots/, validate every dated folder, and regenerate
# manifest.json from the valid ones (with each report's status and strike total).
#
# Usage:
#   sync-snapshots.sh                     # S3 -> local (read-only on S3), then manifest
#   sync-snapshots.sh --manifest-only     # validate local folders + manifest (no AWS)
#
# The production manifest is built from the DynamoDB timeline by the pipeline. To repair
# it, run `python -m pipeline.timeline_admin rebuild-manifest` from the repo root.
#
# Environment:
#   SNAPSHOT_BUCKET   bucket name (default: SnapshotBucketName output of the stack)
#   STACK_NAME        CloudFormation stack (default: stack_name in infra/samconfig.toml,
#                     else infra-kiro-hackathon)
#
# `latest/` is never synced: it is the committed demo fixture managed by the regen hooks.
# Requires bash, coreutils (od, wc, date), node and, except for --manifest-only, the AWS CLI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOTS="$(cd "$SCRIPT_DIR/../public/snapshots" && pwd)"
MANIFEST="$SNAPSHOTS/manifest.json"
MANIFEST_TOOL="$SCRIPT_DIR/manifest.mjs"
SAMCONFIG="$SCRIPT_DIR/../../infra/samconfig.toml"
DATE_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
HEADER_SIZE=16
RECORD_SIZE=28

# The stack `sam deploy` targets (infra/samconfig.toml), unless STACK_NAME is set.
samconfig_stack() {
  [[ -f "$SAMCONFIG" ]] || return 0
  sed -n 's/^[[:space:]]*stack_name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$SAMCONFIG" |
    head -n 1
}
STACK_NAME="${STACK_NAME:-$(samconfig_stack)}"
STACK_NAME="${STACK_NAME:-infra-kiro-hackathon}"

MODE="sync"
TMP_SOURCE=""

usage() {
  sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

log() { printf '[sync] %s\n' "$*"; }
warn() { printf '[sync] WARNING: %s\n' "$*" >&2; }
die() {
  printf '[sync] ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest-only) MODE="manifest" ;;
    --publish-manifest)
      cat >&2 <<'EOF'
[sync] ERROR: --publish-manifest was removed. The production manifest is now built from
[sync] the DynamoDB timeline; to repair it, run from the repo root:
[sync]   .venv/bin/python -m pipeline.timeline_admin rebuild-manifest [--apply]
EOF
      exit 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done

command -v node >/dev/null || die "node is required to write the manifest"

# ---- Binary header checks (layout v2, little-endian) -------------------------------

# Print the unsigned little-endian u32 at byte offset $2 of file $1.
read_u32le() {
  local -a b
  read -r -a b <<<"$(od -An -tu1 -j"$2" -N4 "$1")"
  [[ ${#b[@]} -eq 4 ]] || return 1
  echo $((b[0] + (b[1] << 8) + (b[2] << 16) + (b[3] << 24)))
}

# Days since the Unix epoch -> YYYY-MM-DD (UTC). GNU date first, then BSD date.
days_to_iso() {
  local secs=$(($1 * 86400))
  date -u -d "@$secs" +%F 2>/dev/null || date -u -r "$secs" +%F
}

# Validate one dated folder. Prints the reason and returns 1 when it is invalid.
check_report() {
  local dir="$1" name bin json magic version size count days header_date
  name="$(basename "$dir")"
  bin="$dir/snapshot.bin"
  json="$dir/snapshot.json"

  if [[ -L "$dir" ]]; then
    echo "is a symlink, not a copied report"
    return 1
  fi
  [[ -d "$dir" ]] || { echo "is not a directory"; return 1; }
  [[ -f "$bin" ]] || { echo "missing snapshot.bin"; return 1; }
  [[ -f "$json" ]] || { echo "missing snapshot.json"; return 1; }

  size=$(wc -c <"$bin" | tr -d ' ')
  if ((size < HEADER_SIZE)); then
    echo "snapshot.bin is too short ($size bytes)"
    return 1
  fi
  magic="$(od -An -tu1 -N4 "$bin" | tr -s ' ' | sed 's/^ //;s/ $//')"
  [[ "$magic" == "82 66 77 78" ]] || { echo "bad magic (not RBMN)"; return 1; }
  version="$(od -An -tu1 -j4 -N1 "$bin" | tr -d ' ')"
  [[ "$version" == "2" ]] || { echo "unsupported layout version $version"; return 1; }
  days="$(read_u32le "$bin" 8)" || { echo "unreadable header date"; return 1; }
  count="$(read_u32le "$bin" 12)" || { echo "unreadable record count"; return 1; }
  if ((size != HEADER_SIZE + RECORD_SIZE * count)); then
    echo "size $size does not match $count records"
    return 1
  fi
  header_date="$(days_to_iso "$days")"
  if [[ "$header_date" != "$name" ]]; then
    echo "header date $header_date does not match the folder name"
    return 1
  fi
  if ! grep -Eq "\"date\": ?\"$name\"" "$json"; then
    echo "snapshot.json is not dated $name"
    return 1
  fi
}

# Validate every date-named entry. Sets VALID_DATES (ascending) and INVALID_COUNT.
VALID_DATES=()
INVALID_COUNT=0
validate_local() {
  local entry name reason
  VALID_DATES=()
  INVALID_COUNT=0
  shopt -s nullglob
  for entry in "$SNAPSHOTS"/*; do
    name="$(basename "$entry")"
    [[ "$name" =~ $DATE_RE ]] || continue
    if reason="$(check_report "$entry")"; then
      VALID_DATES+=("$name")
    else
      warn "$name $reason; left out of the manifest"
      INVALID_COUNT=$((INVALID_COUNT + 1))
    fi
  done
  shopt -u nullglob
  if ((${#VALID_DATES[@]} > 0)); then
    mapfile -t VALID_DATES < <(printf '%s\n' "${VALID_DATES[@]}" | sort)
  fi
}

# Write the manifest for the valid folders. Runs come from the manifest at $1; a folder it
# does not describe keeps its run from the manifest at $2 (optional).
write_local_manifest() {
  local source="$1" fallback="${2:-}" summary
  local -a extra=()
  [[ -n "$fallback" ]] && extra=(--fallback "$fallback")
  validate_local
  summary="$(node "$MANIFEST_TOOL" --out "$MANIFEST" --source "$source" "${extra[@]}" \
    "${VALID_DATES[@]}")"
  log "manifest.json: $summary: ${VALID_DATES[*]:-none}"
  if ((INVALID_COUNT > 0)); then
    die "$INVALID_COUNT invalid report folder(s); fix or remove them"
  fi
}

# ---- AWS helpers --------------------------------------------------------------------

require_aws() {
  command -v aws >/dev/null || die "the AWS CLI is required for this mode"
  aws sts get-caller-identity --query Account --output text >/dev/null ||
    die "no valid AWS credentials"
}

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

resolve_bucket() {
  if [[ -n "${SNAPSHOT_BUCKET:-}" ]]; then
    BUCKET="$SNAPSHOT_BUCKET"
  else
    BUCKET="$(stack_output SnapshotBucketName)"
  fi
  [[ -n "$BUCKET" && "$BUCKET" != "None" ]] || die "could not resolve the snapshot bucket"
}

# ---- Modes --------------------------------------------------------------------------

sync_from_s3() {
  require_aws
  resolve_bucket
  log "s3://$BUCKET/snapshots/ -> $SNAPSHOTS (dated reports only, read-only on S3)"
  aws s3 sync "s3://$BUCKET/snapshots/" "$SNAPSHOTS/" --only-show-errors \
    --exclude '*' \
    --include '20??-??-??/snapshot.json' \
    --include '20??-??-??/snapshot.bin'

  # The production manifest carries the runs (status, strike total) from the timeline.
  # Folders it does not list (e.g. after a stack rebuilt from scratch) keep their local runs.
  TMP_SOURCE="$(mktemp)"
  trap 'rm -f "$TMP_SOURCE"' EXIT
  if aws s3 cp "s3://$BUCKET/snapshots/manifest.json" "$TMP_SOURCE" --only-show-errors; then
    write_local_manifest "$TMP_SOURCE" "$MANIFEST"
  else
    warn "could not read the production manifest; keeping the local runs"
    write_local_manifest "$MANIFEST"
  fi
}

case "$MODE" in
  sync) sync_from_s3 ;;
  manifest) write_local_manifest "$MANIFEST" ;;
esac
