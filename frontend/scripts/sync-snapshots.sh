#!/usr/bin/env bash
# Sync the Rebellion Timeline archive (dated Insurgency Reports) from the snapshot
# bucket into frontend/public/snapshots/, validate every dated folder, and regenerate
# manifest.json from the valid ones.
#
# Usage:
#   sync-snapshots.sh                     # S3 -> local (read-only on S3), then manifest
#   sync-snapshots.sh --manifest-only     # validate local folders + manifest (no AWS)
#   sync-snapshots.sh --publish-manifest [--dry-run] [--yes]
#                                         # write the corrected manifest to production S3
#
# Environment:
#   SNAPSHOT_BUCKET   bucket name (default: SnapshotBucketName output of the stack)
#   STACK_NAME        CloudFormation stack (default: infra-kiro-hackathon)
#
# `latest/` is never synced: it is the committed demo fixture managed by the regen hooks.
# Requires bash, coreutils (od, wc, date) and, except for --manifest-only, the AWS CLI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOTS="$(cd "$SCRIPT_DIR/../public/snapshots" && pwd)"
MANIFEST="$SNAPSHOTS/manifest.json"
STACK_NAME="${STACK_NAME:-infra-kiro-hackathon}"
DATE_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
HEADER_SIZE=16
RECORD_SIZE=28

MODE="sync"
DRY_RUN=0
ASSUME_YES=0
TMP_MANIFEST=""

usage() {
  sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    --publish-manifest) MODE="publish" ;;
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
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

if [[ "$MODE" != "publish" && ($DRY_RUN -eq 1 || $ASSUME_YES -eq 1) ]]; then
  die "--dry-run and --yes only apply to --publish-manifest"
fi

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

# Print {"dates": [...]} for the given dates (the pipeline's json.dumps format).
manifest_json() {
  local out='{"dates": [' sep='' d
  for d in "$@"; do
    out+="$sep\"$d\""
    sep=', '
  done
  printf '%s]}' "$out"
}

write_local_manifest() {
  validate_local
  manifest_json "${VALID_DATES[@]}" >"$MANIFEST"
  printf '\n' >>"$MANIFEST"
  log "manifest.json: ${#VALID_DATES[@]} report(s): ${VALID_DATES[*]:-none}"
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
  write_local_manifest
}

publish_manifest() {
  local keys key d current_raw cdn sm running answer dist invalidation
  local -a s3_bins=() s3_jsons=() s3_dates=() target=() current=() added=() dropped=()

  require_aws
  resolve_bucket

  validate_local
  ((INVALID_COUNT == 0)) || die "fix the invalid local report folder(s) first"

  # Dated prefixes in S3 that hold both artifacts.
  keys="$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix snapshots/ \
    --query 'Contents[].Key' --output text)"
  for key in $keys; do
    if [[ "$key" =~ ^snapshots/([0-9]{4}-[0-9]{2}-[0-9]{2})/snapshot\.bin$ ]]; then
      s3_bins+=("${BASH_REMATCH[1]}")
    elif [[ "$key" =~ ^snapshots/([0-9]{4}-[0-9]{2}-[0-9]{2})/snapshot\.json$ ]]; then
      s3_jsons+=("${BASH_REMATCH[1]}")
    fi
  done
  for d in "${s3_bins[@]}"; do
    if printf '%s\n' "${s3_jsons[@]}" | grep -qx "$d"; then s3_dates+=("$d"); fi
  done

  # Target = complete S3 reports that also passed local validation.
  for d in "${s3_dates[@]}"; do
    if printf '%s\n' "${VALID_DATES[@]}" | grep -qx "$d"; then
      target+=("$d")
    else
      warn "$d is in S3 but not validated locally (run the sync first); left out"
    fi
  done
  ((${#target[@]} > 0)) || die "no publishable report found"
  mapfile -t target < <(printf '%s\n' "${target[@]}" | sort -u)

  current_raw="$(aws s3 cp "s3://$BUCKET/snapshots/manifest.json" - 2>/dev/null || true)"
  mapfile -t current < <(printf '%s' "$current_raw" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort -u)

  for d in "${target[@]}"; do
    printf '%s\n' "${current[@]}" | grep -qx "$d" || added+=("$d")
  done
  for d in "${current[@]}"; do
    printf '%s\n' "${target[@]}" | grep -qx "$d" || dropped+=("$d")
  done

  log "bucket:  $BUCKET"
  log "current: ${current[*]:-none}"
  log "target:  ${target[*]}"
  log "added:   ${added[*]:-none}"
  if ((${#dropped[@]} > 0)); then
    die "the target would drop ${dropped[*]}; refusing to write"
  fi
  if ((${#added[@]} == 0)); then
    log "the production manifest is already up to date"
    return 0
  fi
  if ((DRY_RUN == 1)); then
    log "dry run: nothing written"
    return 0
  fi

  sm="$(stack_output StateMachineArn)"
  cdn="$(stack_output CdnDomain)"
  [[ -n "$sm" && "$sm" != "None" ]] || die "could not resolve StateMachineArn"
  [[ -n "$cdn" && "$cdn" != "None" ]] || die "could not resolve CdnDomain"
  running="$(aws stepfunctions list-executions --state-machine-arn "$sm" \
    --status-filter RUNNING --query 'length(executions)' --output text)"
  [[ "$running" == "0" ]] || die "$running state machine execution(s) running; retry later"

  if ((ASSUME_YES == 0)); then
    read -r -p "[sync] write the manifest to s3://$BUCKET/snapshots/manifest.json? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "aborted; nothing written"
  fi

  dist="$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='$cdn'].Id" --output text)"
  [[ -n "$dist" && "$dist" != "None" ]] || die "no CloudFront distribution for $cdn"

  TMP_MANIFEST="$(mktemp)"
  trap 'rm -f "$TMP_MANIFEST"' EXIT
  manifest_json "${target[@]}" >"$TMP_MANIFEST"
  aws s3 cp "$TMP_MANIFEST" "s3://$BUCKET/snapshots/manifest.json" --only-show-errors \
    --content-type application/json --cache-control max-age=300
  log "wrote s3://$BUCKET/snapshots/manifest.json"

  invalidation="$(aws cloudfront create-invalidation --distribution-id "$dist" \
    --paths /snapshots/manifest.json --query 'Invalidation.Id' --output text)"
  log "CloudFront invalidation $invalidation on $dist (/snapshots/manifest.json)"
}

case "$MODE" in
  sync) sync_from_s3 ;;
  manifest) write_local_manifest ;;
  publish) publish_manifest ;;
esac
