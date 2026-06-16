"""SharedState factory for SQLiq workflows."""
from __future__ import annotations

import uuid
from typing import Literal

from agentstatelib import Artifact, SharedState


MODE = Literal["nl_to_sql", "sql_to_nl"]


def create_workflow_state(
    mode: MODE,
    nl_input: str | None = None,
    sql_input: str | None = None,
    schema_text: str | None = None,
) -> SharedState:
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
    description = (
        f"NL→SQL: {(nl_input or '')[:60]}"
        if mode == "nl_to_sql"
        else f"SQL→NL: {(sql_input or '')[:60]}"
    )

    facts: dict = {
        # ── read-only inputs ───────────────────────────────────────────────
        "mode": mode,
        "nl_input": nl_input,
        "sql_input": sql_input,
        "schema_text": schema_text,
        # ── written by agents ─────────────────────────────────────────────
        "parsed_schema": None,
        "generated_sql": None,
        "sql_explanation": None,
        "validation_ok": None,
        "validation_notes": None,
        "risk_score": None,
        "risk_reasons": [],
        "rewrite_proposal": None,
        "rewrite_reason": None,
        # ── written by approval resolution ────────────────────────────────
        "rewrite_approved": None,
        # ── written by finalizer ──────────────────────────────────────────
        "final_sql": None,
        "final_explanation": None,
    }

    return SharedState(
        workflow_id=workflow_id,
        workflow_type="sql_intelligence",
        goal=description,
        facts=facts,
        status="running",
    )


RESULT_ARTIFACT_ID = "result"