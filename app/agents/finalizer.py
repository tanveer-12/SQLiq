"""
Rule-based result assembler. No LLM call.
Reads all facts written by previous agents and produces the final artifact.
"""
from __future__ import annotations

from agentstatelib import Artifact, StatePatch, StateStore

RESULT_ARTIFACT_ID = "result"


class FinalizerAgent:
    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def __call__(self, context: dict) -> list[StatePatch]:
        facts = context.get("facts", {})
        mode = facts.get("mode", "nl_to_sql")
        rewrite_approved = facts.get("rewrite_approved")

        # Determine final_sql based on mode and approval.
        if mode == "nl_to_sql":
            if rewrite_approved is True:
                final_sql = facts.get("rewrite_proposal") or facts.get("generated_sql")
            else:
                final_sql = facts.get("generated_sql")
        else:
            # SQL→NL: the user's original input is the SQL; no generation.
            final_sql = facts.get("sql_input")

        final_explanation = facts.get("sql_explanation") or ""

        result_content = {
            "mode": mode,
            "sql": final_sql,
            "explanation": final_explanation,
            "risk_score": facts.get("risk_score"),
            "risk_reasons": facts.get("risk_reasons", []),
            "validation_ok": facts.get("validation_ok"),
            "validation_notes": facts.get("validation_notes"),
            "rewrite_was_proposed": facts.get("rewrite_proposal") is not None,
            "rewrite_was_approved": rewrite_approved,
            "rewrite_reason": facts.get("rewrite_reason"),
        }

        artifact = Artifact(
            id=RESULT_ARTIFACT_ID,
            produced_by="finalizer",
            artifact_type="sql_result",
            content=result_content,
        )

        return [
            StatePatch(
                agent_id="finalizer",
                target="facts.final_sql",
                value=final_sql,
                reason="Final SQL assembled",
            ),
            StatePatch(
                agent_id="finalizer",
                target="facts.final_explanation",
                value=final_explanation,
                reason="Final explanation assembled",
            ),
            StatePatch(
                agent_id="finalizer",
                target=f"artifacts.{RESULT_ARTIFACT_ID}",
                value=artifact.model_dump(),
                reason="Result artifact created",
            ),
            StatePatch(
                agent_id="finalizer",
                target="status",
                value="complete",
                reason="Workflow complete",
            ),
        ]