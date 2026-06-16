"""Assemble the FastAPI application."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agentstatelib.api import create_app as create_library_app

from app.api.routes import router as sqliq_router


def create_app() -> FastAPI:
    db_path = os.getenv("SQLIQ_DB_PATH", "sqliq.db")

    # The library's app provides:
    #   GET/POST  /v1/workflows/...      (state CRUD)
    #   GET       /v1/workflows/{id}/events  (SSE stream)
    #   GET/POST  /v1/workflows/{id}/approvals/...
    #   GET       /v1/workflows/{id}/turns
    #   GET       /dashboard             (library's built-in trace dashboard)
    app = create_library_app(db_path=db_path)

    # Add SQLiq-specific routes (/api/run, /api/result/{id}, /api/approve/{id})
    app.include_router(sqliq_router)

    # Serve our custom frontend at /ui/ to avoid conflicting with /dashboard
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    if os.path.isdir(frontend_dir):
        app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app