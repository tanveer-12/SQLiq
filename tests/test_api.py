"""Tests for SQLiq-specific API routes (/api/run, /api/result, /api/approve).

Uses a minimal FastAPI app with only the SQLiq router so we avoid
setting up the full agentstatelib library stack.  The background task
and store are mocked to prevent any real LLM or DB calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.routes import router
from app.state import create_workflow_state


@pytest.fixture(scope="module")
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_workflow_states():
    """Isolate _workflow_states between tests."""
    import app.api.routes as routes_module
    original = routes_module._workflow_states.copy()
    routes_module._workflow_states.clear()
    yield
    routes_module._workflow_states.clear()
    routes_module._workflow_states.update(original)


# ── POST /api/run ─────────────────────────────────────────────────────────────

def test_run_nl_to_sql_returns_workflow_id(client):
    with patch("app.api.routes.get_store", return_value=MagicMock()), \
         patch("app.api.routes._background_run_with_id", new=AsyncMock()):
        resp = client.post("/api/run", json={"mode": "nl_to_sql", "nl_input": "Show all users"})
    assert resp.status_code == 200
    data = resp.json()
    assert "workflow_id" in data
    assert data["workflow_id"].startswith("wf_")
    assert data["status"] == "running"


def test_run_sql_to_nl_returns_workflow_id(client):
    with patch("app.api.routes.get_store", return_value=MagicMock()), \
         patch("app.api.routes._background_run_with_id", new=AsyncMock()):
        resp = client.post("/api/run", json={"mode": "sql_to_nl", "sql_input": "SELECT * FROM users"})
    assert resp.status_code == 200
    assert resp.json()["workflow_id"].startswith("wf_")


def test_run_nl_to_sql_without_nl_input_is_422(client):
    resp = client.post("/api/run", json={"mode": "nl_to_sql"})
    assert resp.status_code == 422


def test_run_sql_to_nl_without_sql_input_is_422(client):
    resp = client.post("/api/run", json={"mode": "sql_to_nl"})
    assert resp.status_code == 422


def test_run_invalid_mode_is_422(client):
    resp = client.post("/api/run", json={"mode": "invalid", "nl_input": "test"})
    assert resp.status_code == 422


# ── GET /api/result/{workflow_id} ─────────────────────────────────────────────

def test_result_unknown_id_is_404(client):
    resp = client.get("/api/result/wf_doesnotexist")
    assert resp.status_code == 404


def test_result_returns_initial_state(client):
    import app.api.routes as routes_module

    state = create_workflow_state(mode="nl_to_sql", nl_input="test")
    routes_module._workflow_states[state.workflow_id] = {"state": state, "approval_id": None}

    resp = client.get(f"/api/result/{state.workflow_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_id"] == state.workflow_id
    assert data["mode"] == "nl_to_sql"


def test_result_shows_awaiting_approval_when_pending(client):
    import app.api.routes as routes_module

    state = create_workflow_state(mode="nl_to_sql", nl_input="risky")
    state.facts["generated_sql"] = "DROP TABLE users"
    state.facts["rewrite_proposal"] = "SELECT 1"
    state.facts["risk_score"] = 0.95

    routes_module._workflow_states[state.workflow_id] = {
        "state": state,
        "approval_id": "appr_xyz",
    }

    # Mock get_pending_approval so we don't need _pending populated
    with patch("app.api.routes.get_pending_approval", return_value={"approval_id": "appr_xyz"}):
        resp = client.get(f"/api/result/{state.workflow_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_approval"


# ── POST /api/approve/{workflow_id} ──────────────────────────────────────────

def test_approve_unknown_id_is_404(client):
    resp = client.post("/api/approve/wf_unknown", json={"decision": "approved"})
    assert resp.status_code == 404


def test_approve_without_approval_id_is_404(client):
    import app.api.routes as routes_module

    state = create_workflow_state(mode="nl_to_sql", nl_input="test")
    routes_module._workflow_states[state.workflow_id] = {"state": state, "approval_id": None}

    resp = client.post(f"/api/approve/{state.workflow_id}", json={"decision": "approved"})
    assert resp.status_code == 404


def test_approve_resolves_pending_approval(client):
    import app.api.routes as routes_module

    state = create_workflow_state(mode="nl_to_sql", nl_input="risky drop")
    state.facts["generated_sql"] = "DROP TABLE users"
    state.facts["rewrite_proposal"] = "SELECT 1"
    state.facts["risk_score"] = 0.95
    routes_module._workflow_states[state.workflow_id] = {
        "state": state,
        "approval_id": "appr_abc",
    }

    resolved_state = create_workflow_state(mode="nl_to_sql", nl_input="risky drop")
    resolved_state.facts["final_sql"] = "SELECT 1"

    with patch("app.api.routes.resolve_approval", new=AsyncMock(return_value=resolved_state)):
        resp = client.post(f"/api/approve/{state.workflow_id}", json={"decision": "approved"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["decision"] == "approved"


def test_approve_with_modified_decision_and_sql(client):
    import app.api.routes as routes_module

    state = create_workflow_state(mode="nl_to_sql", nl_input="test")
    state.facts["rewrite_proposal"] = "SELECT 1"
    routes_module._workflow_states[state.workflow_id] = {
        "state": state,
        "approval_id": "appr_123",
    }

    resolved_state = create_workflow_state(mode="nl_to_sql", nl_input="test")
    resolved_state.facts["final_sql"] = "SELECT id FROM users WHERE id = 1"

    with patch("app.api.routes.resolve_approval", new=AsyncMock(return_value=resolved_state)) as m:
        resp = client.post(f"/api/approve/{state.workflow_id}", json={
            "decision": "modified",
            "modified_sql": "SELECT id FROM users WHERE id = 1",
        })

    assert resp.status_code == 200
    call_kwargs = m.call_args.kwargs
    assert call_kwargs["decision"] == "modified"
    assert call_kwargs["modified_sql"] == "SELECT id FROM users WHERE id = 1"
