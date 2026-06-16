"""Tests for RiskValidatorAgent.

Pre-flight regex rules skip the LLM for obviously dangerous SQL.
Safe or ambiguous SQL goes through the LLM (mocked here).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.risk_validator import RiskValidatorAgent

_MODULE = "app.agents.risk_validator.call_model_with_events"


def _ctx(sql: str, mode: str = "nl_to_sql") -> dict:
    key = "generated_sql" if mode == "nl_to_sql" else "sql_input"
    return {"workflow_id": "wf_test", "facts": {"mode": mode, key: sql, "generated_sql": sql if mode == "nl_to_sql" else None, "sql_input": sql if mode == "sql_to_nl" else None}}


def _get(patches, target):
    return next(p for p in patches if p.target == target).value


# ── pre-flight: high-risk SQL skips LLM ───────────────────────────────────────

@pytest.mark.parametrize("sql,min_score,reason_fragment", [
    ("DROP TABLE users", 0.90, "DROP TABLE"),
    ("TRUNCATE orders", 0.85, "TRUNCATE"),
    ("DELETE FROM users", 0.80, "DELETE without WHERE"),
    ("UPDATE users SET active=0", 0.75, "UPDATE without WHERE"),
])
async def test_preflight_skips_llm(mock_store, mock_client, sql, min_score, reason_fragment):
    agent = RiskValidatorAgent(store=mock_store, client=mock_client)
    with patch(_MODULE) as mock_llm:
        patches = await agent({"workflow_id": "wf_test", "facts": {"mode": "nl_to_sql", "generated_sql": sql, "sql_input": None}})
    mock_llm.assert_not_called()
    assert _get(patches, "facts.risk_score") >= min_score
    reasons = _get(patches, "facts.risk_reasons")
    assert any(reason_fragment in r for r in reasons), f"Expected '{reason_fragment}' in {reasons}"


# ── DELETE with WHERE: not caught by pre-flight ───────────────────────────────

async def test_delete_with_where_calls_llm(mock_store, mock_client):
    llm_resp = {"risk_score": 0.3, "risk_reasons": [], "validation_ok": True, "validation_notes": "Scoped delete"}
    agent = RiskValidatorAgent(store=mock_store, client=mock_client)
    with patch(_MODULE, new=AsyncMock(return_value=llm_resp)):
        patches = await agent({"workflow_id": "wf_t", "facts": {"mode": "nl_to_sql", "generated_sql": "DELETE FROM users WHERE id = 5", "sql_input": None}})
    assert _get(patches, "facts.risk_score") == 0.3
    assert _get(patches, "facts.validation_ok") is True


# ── safe SELECT always calls LLM ──────────────────────────────────────────────

async def test_safe_select_calls_llm(mock_store, mock_client):
    llm_resp = {"risk_score": 0.05, "risk_reasons": [], "validation_ok": True, "validation_notes": "Read-only"}
    agent = RiskValidatorAgent(store=mock_store, client=mock_client)
    with patch(_MODULE, new=AsyncMock(return_value=llm_resp)) as m:
        patches = await agent({"workflow_id": "wf_t", "facts": {"mode": "nl_to_sql", "generated_sql": "SELECT * FROM users", "sql_input": None}})
    m.assert_called_once()
    assert _get(patches, "facts.risk_score") == 0.05


# ── sql_to_nl mode uses sql_input, not generated_sql ─────────────────────────

async def test_sql_to_nl_passes_sql_input_to_llm(mock_store, mock_client):
    llm_resp = {"risk_score": 0.1, "risk_reasons": [], "validation_ok": True, "validation_notes": ""}
    agent = RiskValidatorAgent(store=mock_store, client=mock_client)
    ctx = {"workflow_id": "wf_t", "facts": {"mode": "sql_to_nl", "sql_input": "SELECT name FROM customers", "generated_sql": None}}
    with patch(_MODULE, new=AsyncMock(return_value=llm_resp)) as m:
        await agent(ctx)
    user_msg = m.call_args.kwargs["user_message"]
    assert "SELECT name FROM customers" in user_msg


# ── patches emitted ───────────────────────────────────────────────────────────

async def test_all_expected_patches_emitted(mock_store, mock_client):
    llm_resp = {"risk_score": 0.2, "risk_reasons": ["minor"], "validation_ok": True, "validation_notes": "ok"}
    agent = RiskValidatorAgent(store=mock_store, client=mock_client)
    with patch(_MODULE, new=AsyncMock(return_value=llm_resp)):
        patches = await agent({"workflow_id": "wf_t", "facts": {"mode": "nl_to_sql", "generated_sql": "SELECT 1", "sql_input": None}})
    targets = {p.target for p in patches}
    assert "facts.risk_score" in targets
    assert "facts.risk_reasons" in targets
    assert "facts.validation_ok" in targets
    assert "facts.validation_notes" in targets
    assert "tasks.validate_risk.status" in targets
