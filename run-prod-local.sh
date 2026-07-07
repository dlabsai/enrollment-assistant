#!/bin/bash

set -e

# Local script to test the production setup (frontend served by FastAPI)
# This mimics the Azure deployment locally for testing before deploying

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
STATIC_DIR="$BACKEND_DIR/static"
STATIC_WIDGET_DIR="$BACKEND_DIR/static-widget"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Parse arguments
SKIP_BUILD=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-build]"
            exit 1
            ;;
    esac
done

if [ "$SKIP_BUILD" = false ]; then
    echo "=== Building Frontend (frontend) ==="
    if [ -d "$FRONTEND_DIR" ]; then
        cd "$FRONTEND_DIR"
        pnpm install --frozen-lockfile
        pnpm run build-internal-local
    else
        echo "Warning: Frontend not found at $FRONTEND_DIR"
        echo "Only API will be available"
    fi
fi

echo "=== Setting up static directories ==="
# Clean previous static dirs
rm -rf "$STATIC_DIR" "$STATIC_WIDGET_DIR"

# Copy frontend to static (served at /)
if [ -d "$FRONTEND_DIR/dist-internal-local" ]; then
    cp -r "$FRONTEND_DIR/dist-internal-local" "$STATIC_DIR"
    echo "Frontend copied to $STATIC_DIR"
else
    echo "Warning: Frontend build not found at $FRONTEND_DIR/dist-internal-local"
fi

echo "=== Starting FastAPI with static file serving ==="
echo ""
echo "Endpoints:"
echo "  - Frontend:        http://localhost:8000/"
echo "  - API:             http://localhost:8000/api"
echo ""

cd "$BACKEND_DIR"
uv run uvicorn app.static_app:app --reload --host 0.0.0.0 --port 8000
