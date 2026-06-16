"""
Top-level orchestration for SQLiq.

run_workflow()     → runs Phase 1 (analysis agents).
                     If risk is high and a rewrite was proposed, returns a
                     pending approval_id and stores the paused state.
                     Otherwise runs Phase 2 (finalizer) immediately.

resolve_approval() → called by API or CLI when user decides.
                     Applies decision to state, runs Phase 2.

Both functions accept an optional event_queue so the terminal dashboard
and the SSE stream can both receive live events.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from agentstatelib import (
    HumanApprovalRequested,
    HumanApprovalResolved,
    PatchApplied,
    SharedState,
    SQLiteStore,
    StatePatch,
    StateStore,
    apply_patch,
)

from app.graphs import build_analysis_graph, build_finalizer_graph
from app.state import MODE, create_workflow_state

# In-memory store for workflows awaiting approval.
# Maps workflow_id → {"approval_id": str, "state": SharedState, "store": StateStore}
_pending: dict[str, dict] = {}


def get_store(db_path: str = "sqliq.db") -> StateStore:
    import os
    return SQLiteStore(os.getenv("SQLIQ_DB_PATH", db_path))


async def run_workflow(
    mode: MODE,
    nl_input: str | None = None,
    sql_input: str | None = None,
    schema_text: str | None = None,
    store: StateStore | None = None,
    event_queue: asyncio.Queue | None = None,
    initial_state: SharedState | None = None,
) -> tuple[SharedState, str | None]:
    """
    Run the SQL intelligence workflow.

    Returns (state, approval_id).
    If approval_id is not None, the workflow is paused awaiting human review.
    Call resolve_approval() with the returned approval_id to complete it.
    """
    if store is None:
        store = get_store()

    state = initial_state if initial_state is not None else create_workflow_state(mode, nl_input, sql_input, schema_text)

    # Determine Phase-1 start node(s).
    if schema_text:
        start: str | list[str] = "schema_parser"
    elif mode == "nl_to_sql":
        start = "nl_to_sql"
    else:
        start = "explainer"

    graph1 = build_analysis_graph(store)
    state = await graph1.run(state, start=start, event_queue=event_queue)

    risk_score: float = state.facts.get("risk_score") or 0.0
    rewrite_proposal: str | None = state.facts.get("rewrite_proposal")

    if mode == "nl_to_sql" and risk_score > 0.7 and rewrite_proposal:
        # Pause for human approval — emit the library's event so it appears
        # in the trace and in the library's /dashboard view.
        approval_id = str(uuid.uuid4())
        await store.append(
            HumanApprovalRequested(
                workflow_id=state.workflow_id,
                agent_id="system",
                approval_id=approval_id,
                description=(
                    f"Risky SQL detected (score {risk_score:.2f}). "
                    f"Reasons: {', '.join(state.facts.get('risk_reasons', []))}. "
                    f"Rewrite proposed."
                ),
                pending_patch={
                    "rewrite_proposal": rewrite_proposal,
                    "rewrite_reason": state.facts.get("rewrite_reason", ""),
                },
            )
        )
        if event_queue is not None:
            event_queue.put_nowait(None)  # signal dashboard to stop Phase-1 display

        _pending[state.workflow_id] = {
            "approval_id": approval_id,
            "state": state,
            "store": store,
        }
        return state, approval_id

    # Safe path — run finalizer immediately.
    graph2 = build_finalizer_graph(store)
    state = await graph2.run(state, start="finalizer", event_queue=event_queue)

    if event_queue is not None:
        event_queue.put_nowait(None)  # signal dashboard to stop

    return state, None


async def resolve_approval(
    workflow_id: str,
    decision: Literal["approved", "rejected", "modified"],
    modified_sql: str | None = None,
    event_queue: asyncio.Queue | None = None,
) -> SharedState:
    """
    Apply the human's decision and run Phase 2 (finalizer).
    Raises KeyError if workflow_id has no pending approval.
    """
    entry = _pending.pop(workflow_id)
    approval_id: str = entry["approval_id"]
    state: SharedState = entry["state"]
    store: StateStore = entry["store"]

    await store.append(
        HumanApprovalResolved(
            workflow_id=workflow_id,
            agent_id="system",
            approval_id=approval_id,
            decision=decision,
        )
    )

    if decision == "approved":
        state = apply_patch(
            state,
            StatePatch(
                agent_id="human",
                target="facts.rewrite_approved",
                value=True,
                reason="User approved rewrite",
            ),
        )
    elif decision == "rejected":
        state = apply_patch(
            state,
            StatePatch(
                agent_id="human",
                target="facts.rewrite_approved",
                value=False,
                reason="User rejected rewrite",
            ),
        )
    elif decision == "modified":
        state = apply_patch(
            state,
            StatePatch(
                agent_id="human",
                target="facts.rewrite_approved",
                value=True,
                reason="User accepted modified rewrite",
            ),
        )
        if modified_sql:
            state = apply_patch(
                state,
                StatePatch(
                    agent_id="human",
                    target="facts.rewrite_proposal",
                    value=modified_sql,
                    reason="User's modified SQL accepted",
                ),
            )

    graph2 = build_finalizer_graph(store)
    state = await graph2.run(state, start="finalizer", event_queue=event_queue)

    if event_queue is not None:
        event_queue.put_nowait(None)

    return state


def get_pending_approval(workflow_id: str) -> dict | None:
    """Return the pending approval entry for a workflow, or None."""
    entry = _pending.get(workflow_id)
    if not entry:
        return None
    state: SharedState = entry["state"]
    return {
        "approval_id": entry["approval_id"],
        "workflow_id": workflow_id,
        "original_sql": state.facts.get("generated_sql"),
        "rewrite_proposal": state.facts.get("rewrite_proposal"),
        "rewrite_reason": state.facts.get("rewrite_reason"),
        "risk_score": state.facts.get("risk_score"),
        "risk_reasons": state.facts.get("risk_reasons", []),
    }