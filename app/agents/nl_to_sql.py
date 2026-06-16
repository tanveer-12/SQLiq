from __future__ import annotations

import json
from pathlib import Path

from openai import AsyncOpenAI

from agentstatelib import StatePatch, StateStore

from app.agents.base import _MODEL, _MAX_RETRIES, call_model_with_events

_PROMPT = (Path(__file__).parent.parent / "prompts" / "nl_to_sql.txt").read_text()


class NLToSQLAgent:
    def __init__(self, store: StateStore, client: AsyncOpenAI) -> None:
        self._store = store
        self._client = client

    async def __call__(self, context: dict) -> list[StatePatch]:
        workflow_id: str = context.get("workflow_id", "")
        facts = context.get("facts", {})
        nl_input: str = facts.get("nl_input") or ""
        parsed_schema = facts.get("parsed_schema")

        schema_section = (
            f"\n\nDatabase schema:\n{json.dumps(parsed_schema, indent=2)}"
            if parsed_schema
            else "\n\nNo schema provided — use plausible generic names."
        )

        user_message = f"Question: {nl_input}{schema_section}"

        data = await call_model_with_events(
            store=self._store,
            workflow_id=workflow_id,
            agent_id="nl_to_sql",
            client=self._client,
            model=_MODEL,
            system_prompt=_PROMPT,
            user_message=user_message,
            max_retries=_MAX_RETRIES,
        )

        return [
            StatePatch(
                agent_id="nl_to_sql",
                target="facts.generated_sql",
                value=data["sql"],
                reason="Generated SQL from natural language input",
            ),
        ]