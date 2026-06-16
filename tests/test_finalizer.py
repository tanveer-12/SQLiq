"""Tests for FinalizerAgent — rule-based assembler, no LLM."""
from __future__ import annotations

import pytest

from app.agents.finalizer import FinalizerAgent


@pytest.fixture
def agent(mock_store):
    return FinalizerAgent(store=mock_store)


def _get(patches, target):
    return next(p for p in patches if p.target == target).value


def _base_facts(**overrides) -> dict:
    facts: dict = {
        "mode": "nl_to_sql",
        "generated_sql": "SELECT * FROM users",
        "sql_input": None,
        "sql_explanation": "Returns all users",
        "rewrite_proposal": None,
        "rewrite_reason": None,
        "rewrite_approved": None,
        "risk_score": 0.1,
        "risk_reasons": [],
        "validation_ok": True,
        "validation_notes": "Looks fine",
    }
    facts.update(overrides)
    return facts


# ── nl_to_sql: no rewrite ──────────────────────────────────────────────────────

async def test_nl_to_sql_uses_generated_sql(agent):
    patches = await agent({"facts": _base_facts()})
    assert _get(patches, "facts.final_sql") == "SELECT * FROM users"


async def test_nl_to_sql_captures_explanation(agent):
    patches = await agent({"facts": _base_facts()})
    assert _get(patches, "facts.final_explanation") == "Returns all users"


# ── nl_to_sql: rewrite approved ───────────────────────────────────────────────

async def test_rewrite_approved_uses_proposal(agent):
    patches = await agent({"facts": _base_facts(
        generated_sql="DELETE FROM users",
        rewrite_proposal="DELETE FROM users WHERE id = :id",
        rewrite_approved=True,
    )})
    assert _get(patches, "facts.final_sql") == "DELETE FROM users WHERE id = :id"


# ── nl_to_sql: rewrite rejected ───────────────────────────────────────────────

async def test_rewrite_rejected_keeps_original(agent):
    patches = await agent({"facts": _base_facts(
        generated_sql="DELETE FROM users",
        rewrite_proposal="DELETE FROM users WHERE id = :id",
        rewrite_approved=False,
    )})
    assert _get(patches, "facts.final_sql") == "DELETE FROM users"


# ── sql_to_nl mode ────────────────────────────────────────────────────────────

async def test_sql_to_nl_uses_sql_input(agent):
    patches = await agent({"facts": _base_facts(
        mode="sql_to_nl",
        sql_input="SELECT id, name FROM users WHERE active = 1",
        generated_sql=None,
    )})
    assert _get(patches, "facts.final_sql") == "SELECT id, name FROM users WHERE active = 1"


# ── status / goal patches ─────────────────────────────────────────────────────

async def test_workflow_status_set_complete(agent):
    patches = await agent({"facts": _base_facts()})
    assert _get(patches, "status") == "complete"


async def test_goal_marked_complete(agent):
    patches = await agent({"facts": _base_facts()})
    assert _get(patches, "goals.sql_task.status") == "complete"


async def test_finalize_task_marked_complete(agent):
    patches = await agent({"facts": _base_facts()})
    assert _get(patches, "tasks.finalize.status") == "complete"


# ── artifact ──────────────────────────────────────────────────────────────────

async def test_result_artifact_created(agent):
    patches = await agent({"facts": _base_facts()})
    artifact_patch = next(p for p in patches if p.target.startswith("artifacts."))
    assert artifact_patch.value["artifact_type"] == "sql_result"
    content = artifact_patch.value["content"]
    assert content["sql"] == "SELECT * FROM users"
    assert content["mode"] == "nl_to_sql"


async def test_artifact_records_rewrite_state(agent):
    patches = await agent({"facts": _base_facts(
        rewrite_proposal="SELECT 1",
        rewrite_approved=True,
    )})
    artifact_patch = next(p for p in patches if p.target.startswith("artifacts."))
    content = artifact_patch.value["content"]
    assert content["rewrite_was_proposed"] is True
    assert content["rewrite_was_approved"] is True


async def test_no_rewrite_proposal_flag_false(agent):
    patches = await agent({"facts": _base_facts()})
    artifact_patch = next(p for p in patches if p.target.startswith("artifacts."))
    assert artifact_patch.value["content"]["rewrite_was_proposed"] is False
