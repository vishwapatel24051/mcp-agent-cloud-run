#!/usr/bin/env bash
# Build the container with Cloud Build and deploy it to Cloud Run.
# Usage: ./deploy.sh   (reads secrets from .env; nothing secret lives in this file)
set -euo pipefail

set -a
source .env
set +a

SERVICE=csci599-a1
REGION=us-west1
IMAGE="gcr.io/${GCP_PROJECT_ID}/${SERVICE}"

gcloud builds submit --project "${GCP_PROJECT_ID}" --tag "${IMAGE}"

gcloud run deploy "${SERVICE}" \
  --project "${GCP_PROJECT_ID}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --cpu-boost \
  --concurrency 10 \
  --timeout 300 \
  --min-instances 1 \
  --max-instances 1 \
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY},OPENAI_BASE_URL=${OPENAI_BASE_URL},MODEL_NAME=${MODEL_NAME},TAVILY_API_KEY=${TAVILY_API_KEY},MCP_SERVERS_CONFIG=/app/mcp_config.json"
