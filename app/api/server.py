"""Assemble the FastAPI application."""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from agentstatelib.api import create_app as create_library_app
from agentstatelib.api.dashboard import DASHBOARD_HTML

from app.api.routes import router as sqliq_router


class _InjectDashboardKey(BaseHTTPMiddleware):
    """Pre-seed the dashboard's localStorage key so no modal appears on first open."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/dashboard" and request.method == "GET":
            key = (os.getenv("AGENTSTATE_API_KEYS", "dev-key-123")
                   .split(",")[0].strip() or "dev-key-123")
            seed_script = (
                f'<script>try{{localStorage.setItem("agentstate_key","{key}")}}catch(e){{}}</script>'
            )
            patched = DASHBOARD_HTML.replace("</head>", seed_script + "</head>", 1)
            return HTMLResponse(patched)
        return await call_next(request)


def create_app() -> FastAPI:
    db_path = os.getenv("SQLIQ_DB_PATH", "sqliq.db")

    # The library's app provides:
    #   GET/POST  /v1/workflows/...      (state CRUD)
    #   GET       /v1/workflows/{id}/events  (SSE stream)
    #   GET/POST  /v1/workflows/{id}/approvals/...
    #   GET       /v1/workflows/{id}/turns
    #   GET       /dashboard             (library's built-in trace dashboard)
    app = create_library_app(db_path=db_path)
    app.add_middleware(_InjectDashboardKey)

    # Add SQLiq-specific routes (/api/run, /api/result/{id}, /api/approve/{id})
    app.include_router(sqliq_router)

    # Serve our custom frontend at /ui/ to avoid conflicting with /dashboard
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    if os.path.isdir(frontend_dir):
        app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app