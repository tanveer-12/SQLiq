"""Tests for the top-level workflow orchestration.

All graph execution is mocked — these tests verify the control flow
decisions (when to pause for approval, when to run the finalizer) rather
than LLM outputs.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.state import create_workflow_state
from app.workflow import get_pending_approval, resolve_approval, run_workflow


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_state(risk_score: float = 0.0, rewrite_proposal: str | None = None, mode: str = "nl_to_sql"):
    """Create a real SharedState and pre-populate the relevant facts."""
    state = create_workflow_state(
        mode=mode,
        nl_input="test query" if mode == "nl_to_sql" else None,
        sql_input="SELECT 1" if mode == "sql_to_nl" else None,
    )
    state.facts["risk_score"] = risk_score
    state.facts["rewrite_proposal"] = rewrite_proposal
    state.facts["generated_sql"] = "DELETE FROM users"
    state.facts["risk_reasons"] = ["High-risk SQL"] if risk_score > 0.7 else []
    state.facts["rewrite_reason"] = "safer" if rewrite_proposal else ""
    return state


def _final_state():
    state = create_workflow_state(mode="nl_to_sql", nl_input="test")
    state.facts["final_sql"] = "SELECT 1"
    state.facts["final_explanation"] = "Returns 1"
    return state


# ── safe path ─────────────────────────────────────────────────────────────────

async def test_safe_workflow_returns_no_approval_id(mock_store):
    safe = _make_state(risk_score=0.1)
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=safe)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="show users", store=mock_store
        )

    assert approval_id is None
    mock_g2.run.assert_called_once()


async def test_safe_workflow_runs_finalizer(mock_store):
    safe = _make_state(risk_score=0.5)   # just under gate
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=safe)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        await run_workflow(mode="nl_to_sql", nl_input="test", store=mock_store)

    mock_g2.run.assert_called_once()


# ── high-risk path ────────────────────────────────────────────────────────────

async def test_high_risk_nl_to_sql_pauses_for_approval(mock_store):
    risky = _make_state(risk_score=0.95, rewrite_proposal="SELECT 1 -- safer")
    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=risky)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph") as mock_g2_factory:
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="drop all users", store=mock_store
        )

    assert approval_id is not None
    mock_g2_factory.assert_not_called()   # finalizer graph not built during pause
    mock_store.append.assert_called()     # HumanApprovalRequested event emitted


async def test_high_risk_without_rewrite_proposal_does_not_pause(mock_store):
    risky_no_rewrite = _make_state(risk_score=0.95, rewrite_proposal=None)
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=risky_no_rewrite)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="test", store=mock_store
        )

    assert approval_id is None


async def test_sql_to_nl_never_pauses_even_at_high_risk(mock_store):
    risky = _make_state(risk_score=0.99, rewrite_proposal="SELECT 1", mode="sql_to_nl")
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=risky)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        state, approval_id = await run_workflow(
            mode="sql_to_nl", sql_input="DROP TABLE users", store=mock_store
        )

    assert approval_id is None
    mock_g2.run.assert_called_once()


# ── resolve_approval ──────────────────────────────────────────────────────────

async def _setup_pending(mock_store, decision_to_test: str):
    """Run a high-risk workflow to populate _pending, then resolve it."""
    import app.workflow as wf_module

    risky = _make_state(risk_score=0.95, rewrite_proposal="SELECT 1 -- safer")
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=risky)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="risky", store=mock_store
        )

    workflow_id = state.workflow_id

    # Now resolve
    mock_g2b = MagicMock()
    mock_g2b.run = AsyncMock(return_value=final)
    with patch("app.workflow.build_finalizer_graph", return_value=mock_g2b), \
         patch("app.workflow.apply_patch", side_effect=lambda s, _p: s):
        result = await resolve_approval(workflow_id=workflow_id, decision=decision_to_test)

    return result, workflow_id


async def test_resolve_approved_runs_finalizer(mock_store):
    result, _ = await _setup_pending(mock_store, "approved")
    assert result is not None


async def test_resolve_rejected_runs_finalizer(mock_store):
    result, _ = await _setup_pending(mock_store, "rejected")
    assert result is not None


async def test_resolve_modified_runs_finalizer(mock_store):
    import app.workflow as wf_module

    risky = _make_state(risk_score=0.95, rewrite_proposal="SELECT 1 -- safer")
    final = _final_state()

    mock_g1 = MagicMock()
    mock_g1.run = AsyncMock(return_value=risky)
    mock_g2 = MagicMock()
    mock_g2.run = AsyncMock(return_value=final)

    with patch("app.workflow.build_analysis_graph", return_value=mock_g1), \
         patch("app.workflow.build_finalizer_graph", return_value=mock_g2):
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="risky", store=mock_store
        )

    mock_g2b = MagicMock()
    mock_g2b.run = AsyncMock(return_value=final)
    with patch("app.workflow.build_finalizer_graph", return_value=mock_g2b), \
         patch("app.workflow.apply_patch", side_effect=lambda s, _p: s):
        result = await resolve_approval(
            workflow_id=state.workflow_id,
            decision="modified",
            modified_sql="SELECT id FROM users WHERE id = :id",
        )

    assert result is not None


async def test_resolve_unknown_workflow_raises(mock_store):
    with pytest.raises(KeyError):
        await resolve_approval(workflow_id="does_not_exist", decision="approved")


# ── get_pending_approval ──────────────────────────────────────────────────────

def test_get_pending_approval_unknown_returns_none():
    assert get_pending_approval("wf_unknown") is None


def test_get_pending_approval_returns_entry():
    from unittest.mock import patch as _patch
    state = create_workflow_state(mode="nl_to_sql", nl_input="drop table")
    state.facts["generated_sql"] = "DROP TABLE users"
    state.facts["rewrite_proposal"] = "SELECT 1"
    state.facts["rewrite_reason"] = "safer"
    state.facts["risk_score"] = 0.95
    state.facts["risk_reasons"] = ["DROP TABLE detected"]

    fake_pending = {state.workflow_id: {
        "approval_id": "appr_abc",
        "state": state,
        "store": MagicMock(),
    }}
    with _patch.dict("app.workflow._pending", fake_pending):
        result = get_pending_approval(state.workflow_id)

    assert result is not None
    assert result["approval_id"] == "appr_abc"
    assert result["original_sql"] == "DROP TABLE users"
    assert result["risk_score"] == 0.95
