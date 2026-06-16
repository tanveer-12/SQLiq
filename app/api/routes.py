"""SQLiq-specific FastAPI routes. Mounted at /api."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, model_validator

logger = logging.getLogger(__name__)

from agentstatelib import SQLiteStore
from app.workflow import get_pending_approval, get_store, resolve_approval, run_workflow

router = APIRouter(prefix="/api")


class RunRequest(BaseModel):
    mode: Literal["nl_to_sql", "sql_to_nl"]
    nl_input: str | None = None
    sql_input: str | None = None
    schema_text: str | None = None

    @model_validator(mode="after")
    def _check_inputs(self):
        if self.mode == "nl_to_sql" and not self.nl_input:
            raise ValueError("nl_input required for nl_to_sql mode")
        if self.mode == "sql_to_nl" and not self.sql_input:
            raise ValueError("sql_input required for sql_to_nl mode")
        return self


class RunResponse(BaseModel):
    workflow_id: str
    status: str = "running"


class ApproveRequest(BaseModel):
    decision: Literal["approved", "rejected", "modified"]
    modified_sql: str | None = None


# Store active (state, approval_id) tuples keyed by workflow_id.
# The background task writes here; the approve endpoint reads from here.
_workflow_states: dict[str, dict] = {}


async def _background_run(req: RunRequest, store: SQLiteStore) -> None:
    state, approval_id = await run_workflow(
        mode=req.mode,
        nl_input=req.nl_input,
        sql_input=req.sql_input,
        schema_text=req.schema_text,
        store=store,
    )
    _workflow_states[state.workflow_id] = {
        "state": state,
        "approval_id": approval_id,
    }


@router.post("/run", response_model=RunResponse)
async def run(req: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    store = get_store()
    # Pre-create state to get the workflow_id before the background task runs.
    from app.state import create_workflow_state

    state = create_workflow_state(
        mode=req.mode,
        nl_input=req.nl_input,
        sql_input=req.sql_input,
        schema_text=req.schema_text,
    )
    workflow_id = state.workflow_id
    _workflow_states[workflow_id] = {"state": state, "approval_id": None}

    background_tasks.add_task(_background_run_with_id, req, store, workflow_id)
    return RunResponse(workflow_id=workflow_id)


async def _background_run_with_id(req: RunRequest, store, workflow_id: str) -> None:
    try:
        initial = _workflow_states[workflow_id]["state"]
        state, approval_id = await run_workflow(
            mode=req.mode,
            nl_input=req.nl_input,
            sql_input=req.sql_input,
            schema_text=req.schema_text,
            store=store,
            initial_state=initial,
        )
        _workflow_states[workflow_id] = {
            "state": state,
            "approval_id": approval_id,
        }
    except Exception:
        logger.error("Workflow %s failed:\n%s", workflow_id, traceback.format_exc())
        entry = _workflow_states.get(workflow_id, {})
        state = entry.get("state")
        if state is not None:
            from agentstatelib import StatePatch, apply_patch

            state = apply_patch(
                state,
                StatePatch(
                    agent_id="system",
                    target="status",
                    value="failed",
                    reason="Unhandled exception in workflow",
                ),
            )
            _workflow_states[workflow_id] = {"state": state, "approval_id": None}


@router.get("/result/{workflow_id}")
async def get_result(workflow_id: str) -> dict:
    entry = _workflow_states.get(workflow_id)
    if not entry:
        # After a server restart _workflow_states is empty but events are
        # persisted in SQLite. Reconstruct state on demand.
        from agentstatelib.memory.replay import replay

        store = get_store()
        events = await store.get_workflow(workflow_id)
        if not events:
            raise HTTPException(status_code=404, detail="Workflow not found")
        state = replay(events)
        entry = {"state": state, "approval_id": None}
        _workflow_states[workflow_id] = entry

    state = entry["state"]
    approval_id = entry.get("approval_id")
    facts = state.facts

    pending = None
    if approval_id:
        pending = get_pending_approval(workflow_id)

    return {
        "workflow_id": workflow_id,
        "status": state.status if not approval_id else "awaiting_approval",
        "mode": facts.get("mode"),
        "final_sql": facts.get("final_sql"),
        "final_explanation": facts.get("final_explanation"),
        "generated_sql": facts.get("generated_sql"),
        "sql_explanation": facts.get("sql_explanation"),
        "risk_score": facts.get("risk_score"),
        "risk_reasons": facts.get("risk_reasons", []),
        "validation_ok": facts.get("validation_ok"),
        "validation_notes": facts.get("validation_notes"),
        "pending_approval": pending,
    }


@router.post("/approve/{workflow_id}")
async def approve(workflow_id: str, body: ApproveRequest) -> dict:
    entry = _workflow_states.get(workflow_id)
    if not entry or not entry.get("approval_id"):
        raise HTTPException(
            status_code=404, detail="No pending approval for this workflow"
        )

    state = await resolve_approval(
        workflow_id=workflow_id,
        decision=body.decision,
        modified_sql=body.modified_sql,
    )
    _workflow_states[workflow_id] = {"state": state, "approval_id": None}
    return {"status": "resolved", "decision": body.decision}
