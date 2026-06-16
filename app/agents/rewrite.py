from __future__ import annotations

from pathlib import Path

from openai import AsyncOpenAI

from agentstatelib import StatePatch, StateStore

from app.agents.base import _MODEL, _MAX_RETRIES, call_model_with_events

_PROMPT = (Path(__file__).parent.parent / "prompts" / "rewrite.txt").read_text()


class RewriteAgent:
    """Proposes a safer SQL rewrite. Only runs when risk_score > 0.7."""

    def __init__(self, store: StateStore, client: AsyncOpenAI) -> None:
        self._store = store
        self._client = client

    async def __call__(self, context: dict) -> list[StatePatch]:
        workflow_id: str = context.get("workflow_id", "")
        facts = context.get("facts", {})
        generated_sql = facts.get("generated_sql") or ""
        risk_reasons = facts.get("risk_reasons") or []

        user_message = (
            f"Risky SQL:\n{generated_sql}\n\n"
            f"Risk reasons:\n" + "\n".join(f"- {r}" for r in risk_reasons)
        )

        data = await call_model_with_events(
            store=self._store,
            workflow_id=workflow_id,
            agent_id="rewrite_agent",
            client=self._client,
            model=_MODEL,
            system_prompt=_PROMPT,
            user_message=user_message,
            max_retries=_MAX_RETRIES,
        )

        return [
            StatePatch(
                agent_id="rewrite_agent",
                target="facts.rewrite_proposal",
                value=data.get("rewrite_sql", ""),
                reason="Safer SQL rewrite proposed",
            ),
            StatePatch(
                agent_id="rewrite_agent",
                target="facts.rewrite_reason",
                value=data.get("rewrite_reason", ""),
                reason="Rewrite reason recorded",
            ),
        ]