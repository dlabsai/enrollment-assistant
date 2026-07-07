# Deployment Setup

This document describes the production-style setup where FastAPI serves the active React frontend alongside the API.

## Architecture Overview

```text
Azure Web App / local production-style run
├── /api/*     -> FastAPI API routes
├── /widget/*  -> optional public-widget shell when backend/static-widget exists
└── /*         -> active internal React frontend from backend/static
```

## Active Frontend

### Internal app (`frontend/packages/app-internal`)

- **Served at**: `/`
- **Technology**: React + Vite
- **Build command**: `pnpm run build-internal-<env>`
- **Output directory**: `frontend/dist-internal-<env>/`
- **Packaged to**: `backend/static/` in local production-style runs or `deploy-package/static/` for Azure deployment

`deploy-files.sh` builds the staged internal app with `VITE_API_URL=/api` by default so the static bundle calls the API on the same browser origin.

## Optional Widget Shell

`backend/app/static_app.py` can serve `backend/static-widget/` at `/widget` if that directory exists. The normal Azure packaging path does not build or copy a widget shell; the active public widget development app remains in `frontend/packages/app-public` and is run with the frontend workspace scripts.

## FastAPI Static App

`backend/app/static_app.py` wraps the main FastAPI app and adds:

1. GZip compression for responses larger than 500 bytes.
2. Static mounting for root frontend asset directories.
3. Optional static mounting for `/widget/assets` and `/widget/icons` when `backend/static-widget/` exists.
4. SPA fallback to `index.html` for non-API, non-file routes.

Route priority:

1. `/api/*` — API routes handled by `app.main`.
2. `/widget/*` — optional public-widget shell.
3. `/*` — active internal React frontend.

## Local Production-Style Run

```bash
./run-prod-local.sh

# Skip build if frontend/dist-internal-local already exists
./run-prod-local.sh --skip-build
```

Endpoints when running locally:

- Frontend: http://localhost:8000/
- API: http://localhost:8000/api
- Optional widget shell: http://localhost:8000/widget, only if `backend/static-widget/` exists

## Azure Deployment

```bash
AZURE_RESOURCE_GROUP=<resource-group> AZURE_WEBAPP_NAME=<web-app> ./deploy-files.sh
```

The deployment script:

1. Builds the active internal frontend from `frontend/`.
2. Copies the FastAPI backend, Alembic configuration, demo RAG JSON files, and runtime scripts into `deploy-package/`.
3. Copies `frontend/dist-internal-stage` to `deploy-package/static`.
4. Generates a `requirements.txt` from `uv`.
5. Generates an Azure `startup.sh` that runs migrations, starts the optional standalone scheduler, and serves `app.static_app:app` with gunicorn.
6. Creates and deploys `deploy.zip`.

Set `AZURE_POSTGRES_SERVER_NAME` when the script should enable the Azure PostgreSQL `vector` extension before deployment. Keep real credentials in local environment variables or Azure app settings, not in repository files.

## Deployment Package Shape

```text
deploy-package/
├── app/                    # FastAPI backend
├── static/                 # Active internal frontend served at /
│   ├── index.html
│   └── assets/
├── alembic.ini
├── requirements.txt
└── startup.sh
```

## Troubleshooting

### 404 for frontend assets

Verify the frontend build exists and was copied to `static/`:

```bash
ls frontend/dist-internal-stage
ls deploy-package/static
```

### API calls fail after deployment

The deployed frontend should use the relative API base `/api`. Check the build log from `deploy-files.sh` for the `Using frontend API URL:` line.

### Static files do not update

`static_app.py` collects root static files at startup. Restart the server after replacing files, or use `uvicorn --reload` during local development.
