#!/usr/bin/env bash
# Copy the settings the hosted HUD needs from .env to the linked Vercel project,
# then redeploy production so they take effect.
# For macOS, Linux and Git Bash. In Windows PowerShell use vercel-env.ps1.
#
#   bash scripts/vercel-env.sh            upload and redeploy
#   bash scripts/vercel-env.sh --dry-run  show what would be uploaded, change nothing
#
# Uploads only the three LiveKit values and the HUD access code. The Gemini and
# Sarvam keys stay on your machine: only the voice agent uses them.
set -euo pipefail
cd "$(dirname "$0")/.."

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

[[ -f .env ]] || { echo "No .env file here. Copy .env.example to .env first." >&2; exit 1; }
vercel --version > /dev/null 2>&1 || {
  echo "The Vercel CLI does not run in this shell." >&2
  echo "On Windows (including WSL's bash), use: powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1" >&2
  exit 1
}

# Read one value from .env (strips quotes and Windows line endings).
env_value() {
  { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2- | tr -d '\r' \
    | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

if [[ -z "$(env_value FRIDAY_ACCESS_CODE)" ]]; then
  code="$(head -c 12 /dev/urandom | base64 | tr '+/' '-_')"
  if $DRY_RUN; then
    echo "Would generate an access code and save it to .env as FRIDAY_ACCESS_CODE."
  else
    printf '\n# Typed into the hosted HUD to unlock it.\nFRIDAY_ACCESS_CODE=%s\n' "$code" >> .env
    echo "Generated an access code and saved it to .env as FRIDAY_ACCESS_CODE."
  fi
fi

for name in LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET FRIDAY_ACCESS_CODE; do
  value="$(env_value "$name")"
  if [[ -z "$value" ]]; then
    $DRY_RUN && [[ "$name" == FRIDAY_ACCESS_CODE ]] && { echo "Would upload $name"; continue; }
    echo "$name is empty in .env; fill it in and run this again." >&2
    exit 1
  fi
  if $DRY_RUN; then
    echo "Would upload $name (${#value} characters)"
  else
    printf '%s' "$value" | vercel env add "$name" production --force --sensitive > /dev/null
    echo "Uploaded $name"
  fi
done

if $DRY_RUN; then
  echo "Would redeploy production."
  exit 0
fi

vercel deploy --prod --yes
echo
echo "Done. Open the production URL above; the access code is FRIDAY_ACCESS_CODE in .env."
