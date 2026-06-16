from __future__ import annotations

from pathlib import Path

from openai import AsyncOpenAI

from agentstatelib import StatePatch, StateStore

from app.agents.base import _MODEL, _MAX_RETRIES, call_model_with_events

_PROMPT = (Path(__file__).parent.parent / "prompts" / "risk_validator.txt").read_text()

# Pre-flight regex check runs before the LLM call to catch obvious cases fast.
import re
_DANGER_PATTERNS = [
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), 0.95, "DROP TABLE detected"),
    (re.compile(r"\bTRUNCATE\b", re.IGNORECASE), 0.90, "TRUNCATE detected"),
    (re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", re.IGNORECASE | re.DOTALL), 0.85, "DELETE without WHERE"),
    (re.compile(r"\bUPDATE\b.+\bSET\b(?!.*\bWHERE\b)", re.IGNORECASE | re.DOTALL), 0.80, "UPDATE without WHERE"),
]


class RiskValidatorAgent:
    def __init__(self, store: StateStore, client: AsyncOpenAI) -> None:
        self._store = store
        self._client = client

    async def __call__(self, context: dict) -> list[StatePatch]:
        workflow_id: str = context.get("workflow_id", "")
        facts = context.get("facts", {})
        mode = facts.get("mode", "nl_to_sql")

        sql = facts.get("generated_sql") if mode == "nl_to_sql" else facts.get("sql_input")
        sql = sql or ""

        # Pre-flight: if a danger pattern fires, skip the LLM call.
        pre_score = 0.0
        pre_reasons: list[str] = []
        for pattern, score, reason in _DANGER_PATTERNS:
            if pattern.search(sql):
                pre_score = max(pre_score, score)
                pre_reasons.append(reason)

        if pre_score >= 0.8:
            data = {
                "risk_score": pre_score,
                "risk_reasons": pre_reasons,
                "validation_ok": True,
                "validation_notes": "Pre-flight check flagged high risk; skipped LLM validation.",
            }
        else:
            user_message = f"SQL query to assess:\n{sql}"
            data = await call_model_with_events(
                store=self._store,
                workflow_id=workflow_id,
                agent_id="risk_validator",
                client=self._client,
                model=_MODEL,
                system_prompt=_PROMPT,
                user_message=user_message,
                max_retries=_MAX_RETRIES,
            )
            # Merge pre-flight reasons if any.
            if pre_reasons:
                data["risk_score"] = max(data.get("risk_score", 0.0), pre_score)
                data["risk_reasons"] = list(set(pre_reasons + data.get("risk_reasons", [])))

        return [
            StatePatch(
                agent_id="risk_validator",
                target="facts.risk_score",
                value=float(data.get("risk_score", 0.0)),
                reason="Risk score assessed",
            ),
            StatePatch(
                agent_id="risk_validator",
                target="facts.risk_reasons",
                value=data.get("risk_reasons", []),
                reason="Risk reasons recorded",
            ),
            StatePatch(
                agent_id="risk_validator",
                target="facts.validation_ok",
                value=bool(data.get("validation_ok", True)),
                reason="Validation result",
            ),
            StatePatch(
                agent_id="risk_validator",
                target="facts.validation_notes",
                value=data.get("validation_notes", ""),
                reason="Validation notes",
            ),
        ]