"""Shared fixtures for SQLiq tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_store():
    """Minimal StateStore mock — only needs append()."""
    store = MagicMock()
    store.append = AsyncMock()
    return store


@pytest.fixture
def mock_client():
    """AsyncOpenAI client mock with a configurable default response.

    Override the response inside individual tests by patching
    call_model_with_events directly — the client fixture is only
    needed when constructing agents that store the client reference.
    """
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = '{"sql": "SELECT 1"}'
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


@pytest.fixture
def make_context():
    """Factory: build a minimal agent context dict with sensible defaults."""
    def _make(workflow_id: str = "wf_test", mode: str = "nl_to_sql", **facts_overrides):
        facts: dict = {
            "mode": mode,
            "nl_input": None,
            "sql_input": None,
            "schema_text": None,
            "parsed_schema": None,
            "generated_sql": None,
            "sql_explanation": None,
            "validation_ok": None,
            "validation_notes": None,
            "risk_score": None,
            "risk_reasons": [],
            "rewrite_proposal": None,
            "rewrite_reason": None,
            "rewrite_approved": None,
            "final_sql": None,
            "final_explanation": None,
        }
        facts.update(facts_overrides)
        return {"workflow_id": workflow_id, "facts": facts}
    return _make
