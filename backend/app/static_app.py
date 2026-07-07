"""Wrapper module that adds static file serving to the FastAPI app.

Used in production deployment to serve the deployed frontend alongside the API.

This module:
- Serves the main frontend at /
- Optionally serves the widget static shell at /widget when present
- Serves the API at /api
- Serves static assets (JS, CSS, fonts, images) with proper caching headers
- Handles SPA routing by serving index.html for non-API, non-file routes
- Adds GZip compression for text-based responses
"""

import mimetypes
from pathlib import Path

from fastapi import Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.main import app

# Serve frontend static files from ../static and, when present, the optional
# widget shell from ../static-widget relative to this file.
STATIC_DIR = Path(__file__).parent.parent / "static"  # main frontend at /
STATIC_WIDGET_DIR = Path(__file__).parent.parent / "static-widget"  # optional widget at /widget

# Add GZip compression for responses > 500 bytes
# Compresses text/html, application/json, text/css, application/javascript, etc.
app.add_middleware(GZipMiddleware, minimum_size=500)


def _get_content_type(file_path: Path) -> str:
    """Get the MIME type for a file, with sensible defaults."""
    content_type, _ = mimetypes.guess_type(str(file_path))
    if content_type is None:
        # Default to binary for unknown types
        content_type = "application/octet-stream"
    return content_type


def _create_file_response(file_path: Path, cache_max_age: int = 0) -> FileResponse:
    """Create a FileResponse with proper headers."""
    headers: dict[str, str] = {}
    if cache_max_age > 0:
        headers["Cache-Control"] = f"public, max-age={cache_max_age}"
    return FileResponse(file_path, media_type=_get_content_type(file_path), headers=headers or None)


# Collect all root-level static files (favicon, images, etc.)
ROOT_STATIC_FILES: set[str] = set()
if STATIC_DIR.exists():
    # Mount directories for internal frontend static assets (served at /)
    assets_dir = STATIC_DIR / "assets"
    icons_dir = STATIC_DIR / "icons"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    if icons_dir.exists():
        app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")

    for item in STATIC_DIR.iterdir():
        if item.is_file():
            ROOT_STATIC_FILES.add(item.name)

# Collect all root-level static files for widget frontend
WIDGET_STATIC_FILES: set[str] = set()

# Mount widget frontend at /widget
if STATIC_WIDGET_DIR.exists():
    widget_assets_dir = STATIC_WIDGET_DIR / "assets"
    widget_icons_dir = STATIC_WIDGET_DIR / "icons"

    if widget_assets_dir.exists():
        app.mount("/widget/assets", StaticFiles(directory=widget_assets_dir), name="widget-assets")

    if widget_icons_dir.exists():
        app.mount("/widget/icons", StaticFiles(directory=widget_icons_dir), name="widget-icons")

    for item in STATIC_WIDGET_DIR.iterdir():
        if item.is_file():
            WIDGET_STATIC_FILES.add(item.name)


@app.get("/widget/{filename:path}")
async def serve_widget_static_or_spa(filename: str) -> Response:
    """Serve widget frontend static files or fall back to index.html.

    This handles all /widget/* routes for the public widget page.
    """
    if not STATIC_WIDGET_DIR.exists():
        return Response(
            content="Widget frontend not found", status_code=404, media_type="text/plain"
        )

    # Check if this is a root-level static file
    if filename in WIDGET_STATIC_FILES:
        file_path = STATIC_WIDGET_DIR / filename
        if file_path.exists():
            cache_time = 86400 if filename.endswith((".ico", ".png", ".jpg", ".svg")) else 3600
            return _create_file_response(file_path, cache_max_age=cache_time)

    # Check if it's a file request (has extension) that we don't have
    if filename and "." in filename.rsplit("/", maxsplit=1)[-1]:
        return Response(content="Not Found", status_code=404, media_type="text/plain")

    # For all other paths, serve index.html
    index_path = STATIC_WIDGET_DIR / "index.html"
    if index_path.exists():
        return _create_file_response(index_path, cache_max_age=0)

    return Response(
        content="Widget application not found", status_code=404, media_type="text/plain"
    )


@app.get("/widget")
async def serve_widget_index() -> Response:
    """Serve widget frontend index.html at /widget (without trailing slash)."""
    if not STATIC_WIDGET_DIR.exists():
        return Response(
            content="Widget frontend not found", status_code=404, media_type="text/plain"
        )

    index_path = STATIC_WIDGET_DIR / "index.html"
    if index_path.exists():
        return _create_file_response(index_path, cache_max_age=0)

    return Response(
        content="Widget application not found", status_code=404, media_type="text/plain"
    )


@app.get("/{filename:path}")
async def serve_static_or_spa(filename: str) -> Response:
    """Serve internal frontend static files or fall back to SPA index.html.

    Priority:
    1. If path starts with API prefix, skip (already handled by API router)
    2. If path matches a root-level static file, serve it
    3. Otherwise, serve index.html for SPA client-side routing
    """
    if not STATIC_DIR.exists():
        return Response(content="Frontend not found", status_code=404, media_type="text/plain")

    # API routes are already handled by the router mounted earlier
    api_prefix = settings.API_STR.lstrip("/")
    if filename.startswith(api_prefix):
        return Response(
            content='{"detail": "Not Found"}', status_code=404, media_type="application/json"
        )

    # Check if this is a root-level static file
    if filename in ROOT_STATIC_FILES:
        file_path = STATIC_DIR / filename
        if file_path.exists():
            cache_time = 86400 if filename.endswith((".ico", ".png", ".jpg", ".svg")) else 3600
            return _create_file_response(file_path, cache_max_age=cache_time)

    # Check if it's a file request (has extension) that we don't have
    if filename and "." in filename.rsplit("/", maxsplit=1)[-1]:
        return Response(content="Not Found", status_code=404, media_type="text/plain")

    # For all other paths, serve index.html (SPA routing)
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return _create_file_response(index_path, cache_max_age=0)

    return Response(content="Application not found", status_code=404, media_type="text/plain")
