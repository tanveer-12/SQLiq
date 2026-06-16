"""Tests for LLM-backed agents: NLToSQL, Explainer, Rewrite.

call_model_with_events is mocked at the module level in each test so no
real model or network is required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.nl_to_sql import NLToSQLAgent
from app.agents.explainer import ExplainerAgent
from app.agents.rewrite import RewriteAgent

_NL_MOD = "app.agents.nl_to_sql.call_model_with_events"
_EX_MOD = "app.agents.explainer.call_model_with_events"
_RW_MOD = "app.agents.rewrite.call_model_with_events"


def _get(patches, target):
    return next(p for p in patches if p.target == target).value


# ══════════════════════════════════════════════════════════════════════════════
# NLToSQLAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestNLToSQLAgent:

    async def test_sql_patch_written(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"sql": "SELECT id, name FROM users WHERE active = 1"})
        agent = NLToSQLAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {"nl_input": "Active users", "parsed_schema": None}}
        with patch(_NL_MOD, new=llm):
            patches = await agent(ctx)
        assert _get(patches, "facts.generated_sql") == "SELECT id, name FROM users WHERE active = 1"

    async def test_task_status_complete(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"sql": "SELECT 1"})
        agent = NLToSQLAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {"nl_input": "test", "parsed_schema": None}}
        with patch(_NL_MOD, new=llm):
            patches = await agent(ctx)
        assert _get(patches, "tasks.translate.status") == "complete"

    async def test_schema_included_in_user_message(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"sql": "SELECT * FROM orders"})
        agent = NLToSQLAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "nl_input": "Show all orders",
            "parsed_schema": {"orders": ["order_id", "amount"]},
        }}
        with patch(_NL_MOD, new=llm) as m:
            await agent(ctx)
        user_msg = m.call_args.kwargs["user_message"]
        assert "orders" in user_msg
        assert "order_id" in user_msg

    async def test_no_schema_mentions_generic(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"sql": "SELECT 1"})
        agent = NLToSQLAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {"nl_input": "test", "parsed_schema": None}}
        with patch(_NL_MOD, new=llm) as m:
            await agent(ctx)
        user_msg = m.call_args.kwargs["user_message"]
        # When no schema, the prompt says to use generic names
        assert "schema" in user_msg.lower() or "generic" in user_msg.lower() or "No schema" in user_msg


# ══════════════════════════════════════════════════════════════════════════════
# ExplainerAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestExplainerAgent:

    async def test_nl_to_sql_mode_explains_generated_sql(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"explanation": "Selects all active users."})
        agent = ExplainerAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "mode": "nl_to_sql",
            "generated_sql": "SELECT * FROM users WHERE active = 1",
            "sql_input": None,
            "parsed_schema": None,
        }}
        with patch(_EX_MOD, new=llm):
            patches = await agent(ctx)
        assert _get(patches, "facts.sql_explanation") == "Selects all active users."
        assert _get(patches, "tasks.explain.status") == "complete"

    async def test_sql_to_nl_mode_uses_sql_input(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"explanation": "Gets active customers."})
        agent = ExplainerAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "mode": "sql_to_nl",
            "generated_sql": None,
            "sql_input": "SELECT * FROM customers WHERE active = 1",
            "parsed_schema": None,
        }}
        with patch(_EX_MOD, new=llm) as m:
            await agent(ctx)
        user_msg = m.call_args.kwargs["user_message"]
        assert "SELECT * FROM customers" in user_msg

    async def test_schema_context_appended(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"explanation": "Returns users."})
        agent = ExplainerAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "mode": "nl_to_sql",
            "generated_sql": "SELECT * FROM users",
            "sql_input": None,
            "parsed_schema": {"users": ["id", "name", "email"]},
        }}
        with patch(_EX_MOD, new=llm) as m:
            await agent(ctx)
        user_msg = m.call_args.kwargs["user_message"]
        assert "users" in user_msg
        assert "email" in user_msg


# ══════════════════════════════════════════════════════════════════════════════
# RewriteAgent
# ══════════════════════════════════════════════════════════════════════════════

class TestRewriteAgent:

    async def test_rewrite_proposal_patch(self, mock_store, mock_client):
        llm = AsyncMock(return_value={
            "rewrite_sql": "DELETE FROM users WHERE id = :id",
            "rewrite_reason": "Added WHERE clause to prevent bulk deletion",
        })
        agent = RewriteAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "generated_sql": "DELETE FROM users",
            "risk_reasons": ["DELETE without WHERE"],
            "risk_score": 0.85,
        }}
        with patch(_RW_MOD, new=llm):
            patches = await agent(ctx)
        assert _get(patches, "facts.rewrite_proposal") == "DELETE FROM users WHERE id = :id"
        assert _get(patches, "facts.rewrite_reason") == "Added WHERE clause to prevent bulk deletion"
        assert _get(patches, "tasks.rewrite.status") == "complete"

    async def test_risk_reasons_included_in_user_message(self, mock_store, mock_client):
        llm = AsyncMock(return_value={"rewrite_sql": "SELECT 1", "rewrite_reason": "safer"})
        agent = RewriteAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "generated_sql": "DROP TABLE users",
            "risk_reasons": ["DROP TABLE detected", "Irreversible operation"],
            "risk_score": 0.95,
        }}
        with patch(_RW_MOD, new=llm) as m:
            await agent(ctx)
        user_msg = m.call_args.kwargs["user_message"]
        assert "DROP TABLE detected" in user_msg
        assert "Irreversible operation" in user_msg

    async def test_missing_keys_in_llm_response_defaults_to_empty(self, mock_store, mock_client):
        llm = AsyncMock(return_value={})  # no rewrite_sql / rewrite_reason keys
        agent = RewriteAgent(store=mock_store, client=mock_client)
        ctx = {"workflow_id": "wf_1", "facts": {
            "generated_sql": "DROP TABLE users",
            "risk_reasons": [],
            "risk_score": 0.95,
        }}
        with patch(_RW_MOD, new=llm):
            patches = await agent(ctx)
        # Should not raise — just write empty strings
        assert _get(patches, "facts.rewrite_proposal") == ""
        assert _get(patches, "facts.rewrite_reason") == ""
