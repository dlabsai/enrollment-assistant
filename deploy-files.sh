#!/bin/bash

set -e

# https://learn.microsoft.com/en-us/azure/app-service/
# https://learn.microsoft.com/en-us/azure/app-service/tutorial-python-postgresql-app-django?tabs=copilot&pivots=azure-developer-cli

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
: "${AZURE_WEBAPP_NAME:?Set AZURE_WEBAPP_NAME}"

RESOURCE_GROUP="$AZURE_RESOURCE_GROUP"
WEBAPP_NAME="$AZURE_WEBAPP_NAME"
POSTGRES_SERVER="${AZURE_POSTGRES_SERVER_NAME:-}"

if [ -z "$RESOURCE_GROUP" ] || [ -z "$WEBAPP_NAME" ]; then
    echo "Error: Set AZURE_RESOURCE_GROUP and AZURE_WEBAPP_NAME environment variables"
    echo "Example: AZURE_RESOURCE_GROUP=mygroup AZURE_WEBAPP_NAME=myapp ./deploy-files.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$SCRIPT_DIR/deploy-package"

if [ -n "${WEBAPP_HOST:-}" ]; then
    DEPLOY_HOST="${WEBAPP_HOST%/}"
else
    DEFAULT_HOSTNAME="$(az webapp show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$WEBAPP_NAME" \
        --query defaultHostName \
        --output tsv)"

    if [ -z "$DEFAULT_HOSTNAME" ]; then
        echo "Error: Could not determine web app hostname for $WEBAPP_NAME"
        exit 1
    fi

    DEPLOY_HOST="https://$DEFAULT_HOSTNAME"
fi

FRONTEND_API_URL="${VITE_API_URL:-/api}"

# Enable PostgreSQL vector extension if server is specified
if [ -n "$POSTGRES_SERVER" ]; then
    echo "=== Enabling PostgreSQL Vector Extension ==="
    az postgres flexible-server parameter set \
        --resource-group "$RESOURCE_GROUP" \
        --server-name "$POSTGRES_SERVER" \
        --name azure.extensions \
        --value vector \
        --output none || echo "Warning: Could not enable vector extension (may already be enabled)"
fi

echo "=== Cleaning Previous Builds ==="
rm -rf "$DEPLOY_DIR"
rm -f "$SCRIPT_DIR/deploy.zip"

echo "=== Building Frontend (frontend) ==="
FRONTEND_DIR="$SCRIPT_DIR/frontend"
if [ -d "$FRONTEND_DIR" ]; then
    cd "$FRONTEND_DIR"
    pnpm install --frozen-lockfile
    echo "Using frontend API URL: $FRONTEND_API_URL"
    VITE_API_URL="$FRONTEND_API_URL" pnpm run build-internal-stage
else
    echo "Error: Frontend not found at $FRONTEND_DIR"
    exit 1
fi

echo "=== Creating Deployment Package ==="
mkdir -p "$DEPLOY_DIR"

# Copy backend files while excluding bulky/generated source artifacts.
# The small Demo University source JSON files are copied explicitly below.
rsync -a \
    --exclude='*.pdf' \
    --exclude='app/rag/data/***' \
    "$SCRIPT_DIR/backend/app" "$DEPLOY_DIR/"
rm -rf "$DEPLOY_DIR/app/rag/data"

mkdir -p "$DEPLOY_DIR/app/rag/data"
for source_json in \
    catalog_courses.json \
    catalog_pages.json \
    catalog_programs.json \
    training_materials.json \
    website_pages.json \
    website_programs.json; do
    source_path="$SCRIPT_DIR/backend/app/rag/data/$source_json"
    if [ ! -f "$source_path" ]; then
        echo "Error: Missing demo RAG source JSON at $source_path"
        exit 1
    fi
    cp "$source_path" "$DEPLOY_DIR/app/rag/data/$source_json"
done

cp "$SCRIPT_DIR/backend/alembic.ini" "$DEPLOY_DIR/"
cp "$SCRIPT_DIR/backend/README.md" "$DEPLOY_DIR/"
cp "$SCRIPT_DIR/backend/run-build-rag-data.sh" "$DEPLOY_DIR/"
chmod +x "$DEPLOY_DIR/run-build-rag-data.sh"

# Generate requirements.txt from uv (more reliable on Azure than uv.lock).
cd "$SCRIPT_DIR/backend"
uv export --no-dev --no-hashes | grep -v "^-e " > "$DEPLOY_DIR/requirements.txt"

# Copy frontend build to static folder (served at /)
cp -r "$FRONTEND_DIR/dist-internal-stage" "$DEPLOY_DIR/static"

# Create startup script for Azure
# Note: With SCM_DO_BUILD_DURING_DEPLOYMENT, app runs from /tmp/<uid>, not /home/site/wwwroot
cat > "$DEPLOY_DIR/startup.sh" << 'EOF'
#!/bin/bash
set -e

# Run migrations from wherever the app is
python -m alembic upgrade head

shutdown() {
    if [ -n "${SCHEDULER_PID:-}" ]; then
        kill "$SCHEDULER_PID" 2>/dev/null || true
    fi
    if [ -n "${WEB_PID:-}" ]; then
        kill "$WEB_PID" 2>/dev/null || true
    fi
}
trap shutdown EXIT INT TERM

# When SCHEDULER is truthy, run exactly one standalone scheduler process. Web
# workers are always started with SCHEDULER=false below so APScheduler does not
# start once per gunicorn worker. Accept the same common bool strings Pydantic
# accepts for Settings.SCHEDULER.
SCHEDULER_VALUE="$(printf '%s' "${SCHEDULER:-false}" | tr '[:upper:]' '[:lower:]')"
case "$SCHEDULER_VALUE" in
    true|t|yes|y|on|1)
        python -m app.scheduler_runner &
        SCHEDULER_PID=$!
        ;;
    false|f|no|n|off|0|"")
        echo "Scheduler disabled by SCHEDULER=${SCHEDULER:-false}"
        ;;
    *)
        echo "Invalid SCHEDULER value: ${SCHEDULER}" >&2
        exit 1
        ;;
esac

# Start the app with gunicorn + uvicorn workers (use static_app which serves frontend).
SCHEDULER=false gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 4 -k uvicorn.workers.UvicornWorker app.static_app:app &
WEB_PID=$!

set +e
if [ -n "${SCHEDULER_PID:-}" ]; then
    # Keep both child processes supervised: if either exits, stop the other and
    # let Azure restart the app.
    wait -n "$SCHEDULER_PID" "$WEB_PID"
    EXIT_STATUS=$?
else
    wait "$WEB_PID"
    EXIT_STATUS=$?
fi
set -e

shutdown
wait "$WEB_PID" ${SCHEDULER_PID:-} 2>/dev/null || true
exit "$EXIT_STATUS"
EOF
chmod +x "$DEPLOY_DIR/startup.sh"

echo "=== Creating ZIP Package ==="
cd "$DEPLOY_DIR"
zip -r ../deploy.zip . -x "*.pyc" -x "__pycache__/*" -x ".git/*"

echo "=== Deploying to Azure Web App ==="

# Enable build automation during deployment
az webapp config appsettings set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --settings SCM_DO_BUILD_DURING_DEPLOYMENT=1 \
    --output none

# Deploy with clean=true to remove old files
az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --src-path "$SCRIPT_DIR/deploy.zip" \
    --type zip \
    # --clean true

echo "=== Setting Startup Command ==="
az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --startup-file "startup.sh"

echo "=== Deployment Complete ==="

# Cleanup
rm -rf "$DEPLOY_DIR"
rm -f "$SCRIPT_DIR/deploy.zip"
