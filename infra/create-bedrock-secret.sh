#!/usr/bin/env bash
# Create (or update) the Secrets Manager secret that holds the Bedrock bearer
# token used by the Preflight and Extract Lambdas. Prints the secret ARN on
# success so it can be passed as the BedrockTokenSecretArn SAM parameter.
#
# Usage:
#   bash infra/create-bedrock-secret.sh
#   bash infra/create-bedrock-secret.sh --region us-west-2

set -euo pipefail

SECRET_NAME="rebellion/bedrock-bearer-token"
DESCRIPTION="Bearer token for Amazon Bedrock model access (Rebellion of the Machines)"
REGION_FLAG=()

# Optional --region override.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) REGION_FLAG=(--region "$2"); shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Prompt for the token (masked input: shows * per character).
TOKEN=""
printf "Enter the Bedrock bearer token: "
while IFS= read -rsn1 ch; do
  if [[ -z "$ch" ]]; then
    break
  elif [[ "$ch" == $'\x7f' || "$ch" == $'\b' ]]; then
    if [[ -n "$TOKEN" ]]; then
      TOKEN="${TOKEN%?}"
      printf '\b \b'
    fi
  else
    TOKEN+="$ch"
    printf '*'
  fi
done
echo

if [[ -z "$TOKEN" ]]; then
  echo "Error: token cannot be empty." >&2
  exit 1
fi

# Try to create; if the secret already exists, update its value instead.
if ARN=$(aws secretsmanager create-secret \
    "${REGION_FLAG[@]}" \
    --name "$SECRET_NAME" \
    --description "$DESCRIPTION" \
    --secret-string "$TOKEN" \
    --query ARN --output text 2>/dev/null); then
  echo "Secret created."
else
  ARN=$(aws secretsmanager put-secret-value \
    "${REGION_FLAG[@]}" \
    --secret-id "$SECRET_NAME" \
    --secret-string "$TOKEN" \
    --query ARN --output text)
  echo "Secret updated (already existed)."
fi

echo ""
echo "============================================"
echo "Secret ARN (use as BedrockTokenSecretArn):"
echo "  $ARN"
echo "============================================"
