"""Tests for SchemaParserAgent — rule-based, no LLM."""
from __future__ import annotations

import pytest

from app.agents.schema_parser import SchemaParserAgent


@pytest.fixture
def agent(mock_store):
    return SchemaParserAgent(store=mock_store)


def _ctx(schema_text: str) -> dict:
    return {"workflow_id": "wf_test", "facts": {"schema_text": schema_text}}


def _parsed(patches) -> dict | None:
    return next(p for p in patches if p.target == "facts.parsed_schema").value


def _task_status(patches) -> str:
    return next(p for p in patches if p.target == "tasks.parse_schema.status").value


# ── basic cases ────────────────────────────────────────────────────────────────

async def test_empty_string_returns_none(agent):
    patches = await agent(_ctx(""))
    assert _parsed(patches) is None


async def test_none_schema_text_returns_none(agent):
    patches = await agent({"workflow_id": "wf_test", "facts": {}})
    assert _parsed(patches) is None


async def test_task_always_marked_complete(agent):
    patches = await agent(_ctx(""))
    assert _task_status(patches) == "complete"


# ── single table ───────────────────────────────────────────────────────────────

DDL_SIMPLE = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100),
    email TEXT NOT NULL
);
"""


async def test_single_table_columns(agent):
    patches = await agent(_ctx(DDL_SIMPLE))
    result = _parsed(patches)
    assert result is not None
    assert "users" in result
    assert set(result["users"]) == {"id", "name", "email"}


# ── multiple tables ────────────────────────────────────────────────────────────

DDL_MULTI = """
CREATE TABLE orders (
    order_id INTEGER,
    user_id  INTEGER,
    amount   DECIMAL(10, 2)
);
CREATE TABLE products (
    product_id INTEGER,
    title      TEXT,
    price      DECIMAL
);
"""


async def test_multiple_tables(agent):
    patches = await agent(_ctx(DDL_MULTI))
    result = _parsed(patches)
    assert set(result.keys()) == {"orders", "products"}
    assert "order_id" in result["orders"]
    assert "title" in result["products"]


# ── IF NOT EXISTS ──────────────────────────────────────────────────────────────

DDL_IF_NOT_EXISTS = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT,
    user_id    INTEGER,
    created_at TIMESTAMP
);
"""


async def test_if_not_exists_clause(agent):
    patches = await agent(_ctx(DDL_IF_NOT_EXISTS))
    result = _parsed(patches)
    assert "sessions" in result
    assert set(result["sessions"]) == {"session_id", "user_id", "created_at"}


# ── constraint keywords not parsed as column names ─────────────────────────────

DDL_WITH_PK = """
CREATE TABLE accounts (
    account_id INTEGER,
    balance    DECIMAL,
    PRIMARY KEY (account_id),
    UNIQUE (balance)
);
"""


async def test_constraint_keywords_excluded(agent):
    patches = await agent(_ctx(DDL_WITH_PK))
    result = _parsed(patches)
    cols = result["accounts"]
    assert "PRIMARY" not in cols
    assert "UNIQUE" not in cols
    assert "account_id" in cols
    assert "balance" in cols
