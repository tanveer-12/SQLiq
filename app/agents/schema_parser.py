"""
Rule-based DDL parser. No LLM call — fast and deterministic.
Extracts table names and column names from CREATE TABLE statements.
"""
from __future__ import annotations

import re

from agentstatelib import StatePatch, StateStore


class SchemaParserAgent:
    """Parse DDL text into a structured dict. Returns two StatePatch objects."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def __call__(self, context: dict) -> list[StatePatch]:
        workflow_id: str = context.get("workflow_id", "")
        schema_text: str = context.get("facts", {}).get("schema_text") or ""

        tables: dict[str, list[str]] = {}
        for match in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(([^;]+?)\)",
            schema_text,
            re.IGNORECASE | re.DOTALL,
        ):
            table_name = match.group(1)
            body = match.group(2)
            columns = [
                col_match.group(1)
                for col_match in re.finditer(r"^\s*[`\"]?(\w+)[`\"]?\s+\w+", body, re.MULTILINE)
                if col_match.group(1).upper() not in ("PRIMARY", "FOREIGN", "UNIQUE", "INDEX", "KEY", "CONSTRAINT", "CHECK")
            ]
            tables[table_name] = columns

        return [
            StatePatch(
                agent_id="schema_parser",
                target="facts.parsed_schema",
                value=tables or None,
                reason=f"Parsed {len(tables)} table(s) from DDL",
            ),
        ]
