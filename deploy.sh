#!/usr/bin/env bash
# Puts the server on Google Cloud Run. Run it from this folder in Cloud Shell: ./deploy.sh
# The first run asks for your league details. Later runs ship new code and keep those settings.
set -euo pipefail

SERVICE=espn-fantasy-mcp
REGION=us-central1

project=$(gcloud config get-value project 2>/dev/null)
[[ -n $project ]] || { echo "Pick your project first: gcloud config set project YOUR_PROJECT_ID"; exit 1; }
echo "Google Cloud project: $project"

settings=()
if ! gcloud --quiet run services describe "$SERVICE" --region "$REGION" >/dev/null 2>&1; then
  read -rp "ESPN league ID (the number after leagueId= in your league's web address): " league_id
  [[ $league_id =~ ^[0-9]+$ ]] || { echo "The league ID should be just digits."; exit 1; }
  read -rsp "espn_s2 cookie (stays hidden; press Enter to skip for a public league): " espn_s2; echo
  read -rsp "SWID cookie (stays hidden): " swid; echo
  env_file=$(mktemp)
  trap 'rm -f "$env_file"' EXIT
  cat > "$env_file" <<EOF
LEAGUE_ID: '$league_id'
ESPN_S2: '$espn_s2'
SWID: '$swid'
MCP_SECRET: '$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")'
EOF
  settings=(--env-vars-file "$env_file")
fi

gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated --max-instances 1 "${settings[@]}"

gcloud run services describe "$SERVICE" --region "$REGION" --format json | python3 -c '
import json, sys
service = json.load(sys.stdin)
env = {e["name"]: e.get("value") for e in service["spec"]["template"]["spec"]["containers"][0].get("env", [])}
print("\nYour connector URL. Keep it private: anyone with it can read your league.")
print(service["status"]["url"] + "/" + env["MCP_SECRET"] + "/mcp")'
