from __future__ import annotations

import json
from pathlib import Path

from openai import AsyncOpenAI

from agentstatelib import StatePatch, StateStore

from app.agents.base import _MODEL, _MAX_RETRIES, call_model_with_events

_PROMPT = (Path(__file__).parent.parent / "prompts" / "explainer.txt").read_text()


class ExplainerAgent:
    """Explains SQL in plain English. Works in both NL→SQL and SQL→NL modes."""

    def __init__(self, store: StateStore, client: AsyncOpenAI) -> None:
        self._store = store
        self._client = client

    async def __call__(self, context: dict) -> list[StatePatch]:
        workflow_id: str = context.get("workflow_id", "")
        facts = context.get("facts", {})
        mode = facts.get("mode", "nl_to_sql")

        # In NL→SQL mode, explain the generated SQL.
        # In SQL→NL mode, explain the user's pasted SQL.
        sql = facts.get("generated_sql") if mode == "nl_to_sql" else facts.get("sql_input")
        parsed_schema = facts.get("parsed_schema")

        schema_section = (
            f"\n\nSchema context:\n{json.dumps(parsed_schema, indent=2)}"
            if parsed_schema
            else ""
        )
        user_message = f"SQL query:\n{sql}{schema_section}"

        data = await call_model_with_events(
            store=self._store,
            workflow_id=workflow_id,
            agent_id="explainer",
            client=self._client,
            model=_MODEL,
            system_prompt=_PROMPT,
            user_message=user_message,
            max_retries=_MAX_RETRIES,
        )

        return [
            StatePatch(
                agent_id="explainer",
                target="facts.sql_explanation",
                value=data["explanation"],
                reason="Plain-English explanation of SQL",
            ),
        ]