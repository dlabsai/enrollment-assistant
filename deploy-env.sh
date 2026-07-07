#!/bin/bash

set -e

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
: "${AZURE_WEBAPP_NAME:?Set AZURE_WEBAPP_NAME}"

RESOURCE_GROUP="$AZURE_RESOURCE_GROUP"
WEBAPP_NAME="$AZURE_WEBAPP_NAME"
WEBAPP_HOST="${WEBAPP_HOST:-https://${WEBAPP_NAME}.azurewebsites.net}"

echo "=== Setting Environment Variables for $WEBAPP_NAME ==="
echo ""
echo "WARNING: This script is only for initial deployment configuration."
echo "Running it after initial setup will destroy the current deployment configuration for $WEBAPP_NAME."
echo "It overwrites Azure Web App app settings, including secret/configuration values."
echo ""
echo "To continue, type exactly: INITIAL CONFIGURATION"

if ! read -r -p "Confirmation: " CONFIRMATION </dev/tty; then
    echo "Confirmation requires an interactive keyboard/terminal. Aborting." >&2
    exit 1
fi

if [ "$CONFIRMATION" != "INITIAL CONFIGURATION" ]; then
    echo "Confirmation did not match. Aborting without changing deployment configuration." >&2
    exit 1
fi

echo "Confirmation accepted. Applying initial deployment configuration..."

az webapp config appsettings set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --settings \
    ENVIRONMENT="production" \
    FRONTEND_HOST="$WEBAPP_HOST" \
    BACKEND_CORS_ORIGINS="$WEBAPP_HOST" \
    \
    POSTGRES_SERVER="${POSTGRES_SERVER:-}" \
    POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
    POSTGRES_USER="${POSTGRES_USER:-}" \
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}" \
    POSTGRES_DB="${POSTGRES_DB:-}" \
    PYTEST_POSTGRES_SERVER="${PYTEST_POSTGRES_SERVER:-${POSTGRES_SERVER:-}}" \
    PYTEST_POSTGRES_PORT="${PYTEST_POSTGRES_PORT:-${POSTGRES_PORT:-5432}}" \
    PYTEST_POSTGRES_USER="${PYTEST_POSTGRES_USER:-${POSTGRES_USER:-}}" \
    PYTEST_POSTGRES_PASSWORD="${PYTEST_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}" \
    PYTEST_POSTGRES_DB="${PYTEST_POSTGRES_DB:-}" \
    \
    AZURE_API_KEY_1="${AZURE_API_KEY_1:-}" \
    AZURE_API_BASE_1="${AZURE_API_BASE_1:-}" \
    AZURE_API_VERSION_1="${AZURE_API_VERSION_1:-latest}" \
    \
    AZURE_API_KEY_2="${AZURE_API_KEY_2:-}" \
    AZURE_API_BASE_2="${AZURE_API_BASE_2:-}" \
    AZURE_API_VERSION_2="${AZURE_API_VERSION_2:-latest}" \
    \
    AZURE_MODEL_RESOURCE_MAP="${AZURE_MODEL_RESOURCE_MAP:-}" \
    \
    MODELS="${MODELS:-azure/your-chat-deployment}" \
    \
    OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" \
    \
    CHATBOT_MODEL="${CHATBOT_MODEL:-azure/your-chat-deployment}" \
    CHATBOT_MODEL_TEMPERATURE="${CHATBOT_MODEL_TEMPERATURE:-0.7}" \
    GUARDRAIL_MODEL="${GUARDRAIL_MODEL:-azure/your-chat-deployment}" \
    GUARDRAIL_MODEL_TEMPERATURE="${GUARDRAIL_MODEL_TEMPERATURE:-0.1}" \
    EVALUATION_MODEL="${EVALUATION_MODEL:-azure/your-chat-deployment}" \
    EVALUATION_MODEL_TEMPERATURE="${EVALUATION_MODEL_TEMPERATURE:-0.0}" \
    SUMMARIZER_MODEL="${SUMMARIZER_MODEL:-azure/your-chat-deployment}" \
    \
    ENABLE_GUARDRAILS="${ENABLE_GUARDRAILS:-true}" \
    MAX_GUARDRAILS_RETRIES="${MAX_GUARDRAILS_RETRIES:-2}" \
    \
    LLM_REQUEST_TIMEOUT="${LLM_REQUEST_TIMEOUT:-300}" \
    \
    USER_REGISTRATION_TOKEN="${USER_REGISTRATION_TOKEN:-}" \
    ADMIN_REGISTRATION_TOKEN="${ADMIN_REGISTRATION_TOKEN:-}" \
    DEV_REGISTRATION_TOKEN="${DEV_REGISTRATION_TOKEN:-}" \
    TEAMS_SSO_ENABLED="${TEAMS_SSO_ENABLED:-false}" \
    TEAMS_SSO_TENANT_ID="${TEAMS_SSO_TENANT_ID:-}" \
    TEAMS_SSO_CLIENT_ID="${TEAMS_SSO_CLIENT_ID:-}" \
    TEAMS_SSO_RESOURCE="${TEAMS_SSO_RESOURCE:-}" \
    TEAMS_SSO_ALLOWED_AUDIENCES="${TEAMS_SSO_ALLOWED_AUDIENCES:-}" \
    JWT_SECRET_KEY="${JWT_SECRET_KEY:-}" \
    JWT_ALGORITHM="${JWT_ALGORITHM:-HS256}" \
    JWT_EXPIRE_MINUTES="${JWT_EXPIRE_MINUTES:-1440}" \
    REFRESH_TOKEN_EXPIRE_DAYS="${REFRESH_TOKEN_EXPIRE_DAYS:-30}" \
    REFRESH_TOKEN_COOKIE_NAME="${REFRESH_TOKEN_COOKIE_NAME:-va_refresh_token}" \
    REFRESH_TOKEN_COOKIE_SAMESITE="${REFRESH_TOKEN_COOKIE_SAMESITE:-none}" \
    \
    LANGFUSE_OTEL_ENABLED="${LANGFUSE_OTEL_ENABLED:-false}" \
    LANGFUSE_OTEL_ENDPOINT="${LANGFUSE_OTEL_ENDPOINT:-}" \
    LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}" \
    LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}" \
    LANGFUSE_INGESTION_VERSION="${LANGFUSE_INGESTION_VERSION:-4}" \
    LANGFUSE_ENVIRONMENT="${LANGFUSE_ENVIRONMENT:-}" \
    SCHEDULER="${SCHEDULER:-true}" \
    \
    SCM_DO_BUILD_DURING_DEPLOYMENT="1" \
    WEBSITE_HTTPLOGGING_RETENTION_DAYS="30" \
    --output none

echo "=== Environment variables set ==="
