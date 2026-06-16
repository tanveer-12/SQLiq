# SQLiq — Complete Implementation Guide

A bidirectional SQL intelligence **web app** built on top of `agentstatelib`.
This lives in a **new, separate GitHub repo**. It depends on `agentstatelib` from PyPI.

---

## What This Builds

- Paste a natural-language question → get SQL back (NL → SQL)
- Paste SQL → get a plain-English explanation (SQL → NL)
- Optional DDL schema grounding for both directions
- Risk scoring with a human approval gate for risky rewrites
- **Terminal dashboard** (Rich, live) showing every agent turn, model latency, token counts
- **Light-themed web UI** (elegant, not neon) with SSE live trace and an in-browser approval UI
- Works with Ollama (local/Colab+ngrok), OpenAI, or any OpenAI-compatible endpoint

---

## Repository Setup

```
# Create the new repo
mkdir sqliq && cd sqliq
git init
uv init --no-workspace   # or: python -m venv .venv && pip install -e ".[dev]"
```

```
# Activate the venv from root:
.venv\Scripts\activate
```
---

## Project Layout

```
sqliq/
├── pyproject.toml
├── .env.example
├── .gitignore
├── main.py                         ← entry point: web server OR terminal chat
├── app/
│   ├── __init__.py
│   ├── state.py                    ← SharedState factory
│   ├── workflow.py                 ← run_workflow(), resolve_approval()
│   ├── graphs.py                   ← AgentGraph wiring (two graphs)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 ← call_model_with_events() + ModelClient
│   │   ├── schema_parser.py        ← rule-based DDL parser (no LLM)
│   │   ├── nl_to_sql.py
│   │   ├── explainer.py
│   │   ├── risk_validator.py
│   │   ├── rewrite.py
│   │   └── finalizer.py            ← rule-based result assembler (no LLM)
│   ├── prompts/
│   │   ├── nl_to_sql.txt
│   │   ├── explainer.txt
│   │   ├── risk_validator.txt
│   │   └── rewrite.txt
│   └── api/
│       ├── __init__.py
│       ├── routes.py               ← POST /api/run, POST /api/approve/{wf_id}
│       └── server.py               ← FastAPI app assembly
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── index.html                  ← Vite entry point
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css               ← Tailwind base + CSS custom properties
│       ├── types.ts                ← shared TypeScript types
│       ├── api.ts                  ← typed fetch wrappers
│       ├── pages/
│       │   ├── Home.tsx            ← mode selector + input forms
│       │   └── Workflow.tsx        ← live trace + result + approval
│       └── components/
│           ├── Header.tsx
│           ├── TracePanel.tsx      ← SSE consumer, live event list
│           ├── ApprovalBox.tsx     ← side-by-side diff + decision buttons
│           └── ResultBox.tsx       ← final SQL + explanation + risk badge
├── notebooks/
│   └── colab_ollama_backend.ipynb  ← Colab setup for local models
└── tests/
    ├── conftest.py
    ├── test_e2e_nl_to_sql.py
    ├── test_e2e_sql_to_nl.py
    ├── test_approval_flow.py
    ├── test_trace_events.py
    └── test_local_model_retry.py
```

---

## `pyproject.toml`

```toml
[project]
name = "sqliq"
version = "0.1.0"
description = "Bidirectional SQL intelligence powered by agentstatelib"
requires-python = ">=3.11"

dependencies = [
    "agentstate-lib[api,dashboard]>=0.5.0",
    "openai>=1.30",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools]
packages = ["app"]

[tool.uv.sources]
# If agentstate-lib is not yet on PyPI, reference it from GitHub:
# agentstate-lib = { git = "https://github.com/yourname/agentstate" }
```

---

## `.env.example`

```bash
# ── Model backend (choose ONE block) ────────────────────────────────────────

# Option A: Ollama running locally
# SQLIQ_API_BASE=http://localhost:11434/v1
# SQLIQ_API_KEY=ollama
# SQLIQ_MODEL=qwen2.5-coder:7b

# Option B: Ollama on Colab via ngrok (paste the ngrok URL)
 SQLIQ_API_BASE=https://abc123.ngrok-free.app/v1
 SQLIQ_API_KEY=ollama
 SQLIQ_MODEL=qwen2.5-coder:7b

# Option C: OpenAI
# SQLIQ_API_BASE=https://api.openai.com/v1
# SQLIQ_API_KEY=sk-...
# SQLIQ_MODEL=gpt-4o-mini

# ── App settings ─────────────────────────────────────────────────────────────
AGENTSTATE_API_KEYS=dev-key-change-me
SQLIQ_DB_PATH=sqliq.db
SQLIQ_MAX_RETRIES=3
SQLIQ_HOST=0.0.0.0
SQLIQ_PORT=8000
```

---

## `app/state.py`

```python
"""SharedState factory for SQLiq workflows."""
from __future__ import annotations

import uuid
from typing import Literal

from agentstatelib import Artifact, Goal, SharedState, Task


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

    goals = {
        "sql_task": Goal(
            goal_id="sql_task",
            description=description,
            status="in_progress",
        )
    }

    task_ids = (
        ["parse_schema", "translate", "validate_risk", "rewrite", "explain", "finalize"]
        if mode == "nl_to_sql"
        else ["parse_schema", "explain", "validate_risk", "finalize"]
    )
    tasks = {
        t: Task(task_id=t, goal_id="sql_task", status="pending", description=t)
        for t in task_ids
    }

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
        goals=goals,
        tasks=tasks,
        facts=facts,
        artifacts={},
        decisions=[],
        status="running",
    )


RESULT_ARTIFACT_ID = "result"
```

---

## `app/agents/base.py`

```python
"""
Model-agnostic agent base for SQLiq.

Uses the openai SDK with a configurable base_url.
This covers: Ollama (local or Colab+ngrok), OpenAI, and any
OpenAI-compatible endpoint. Switch backends via .env — no code changes.

Emits the full agentstatelib trace event set:
PromptAssembled → ModelCalled → ModelReturned → (ValidationFailed + RetryAttempted)*.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from openai import AsyncOpenAI

from agentstatelib import (
    ModelCalled,
    ModelReturned,
    PromptAssembled,
    RetryAttempted,
    StateStore,
    ValidationFailed,
)


def _build_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client from env vars. Works for Ollama and OpenAI."""
    base_url = os.getenv("SQLIQ_API_BASE")       # None → uses api.openai.com
    api_key = os.getenv("SQLIQ_API_KEY", "ollama")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


_MODEL = os.getenv("SQLIQ_MODEL", "qwen2.5-coder:7b")
_MAX_RETRIES = int(os.getenv("SQLIQ_MAX_RETRIES", "3"))


async def call_model_with_events(
    *,
    store: StateStore,
    workflow_id: str,
    agent_id: str,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    max_retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """
    Call the model with a retry-with-correction loop.

    Emits PromptAssembled, ModelCalled, ModelReturned, ValidationFailed,
    and RetryAttempted events into the store on every attempt.

    Returns parsed JSON dict on success.
    Raises RuntimeError after max_retries exhausted.
    """
    last_error: str | None = None

    for attempt in range(max_retries):
        correction = (
            f"\n\nYour previous response failed JSON parsing: {last_error}."
            " Return ONLY valid JSON. No markdown. No explanation. No code fences."
            if last_error
            else ""
        )
        final_user = user_message + correction

        await store.append(
            PromptAssembled(
                workflow_id=workflow_id,
                agent_id=agent_id,
                prompt_text=final_user,
                system_prompt_length=len(system_prompt),
                context_length=len(final_user),
                is_correction_attempt=last_error is not None,
                attempt_number=attempt,
            )
        )

        call_id = str(uuid.uuid4())
        await store.append(
            ModelCalled(
                workflow_id=workflow_id,
                agent_id=agent_id,
                model=model,
                provider="openai_compatible",
                attempt_number=attempt,
                call_id=call_id,
            )
        )

        t0 = time.perf_counter()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_user},
            ],
            temperature=0.1,
        )
        latency = time.perf_counter() - t0
        raw: str = response.choices[0].message.content or ""
        usage = response.usage

        await store.append(
            ModelReturned(
                workflow_id=workflow_id,
                agent_id=agent_id,
                call_id=call_id,
                raw_response=raw,
                latency_seconds=latency,
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                estimated_cost_usd=None,
            )
        )

        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            will_retry = attempt < max_retries - 1
            await store.append(
                ValidationFailed(
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                    attempt_number=attempt,
                    error_type="json_decode_error",
                    error_message=str(exc),
                    raw_output=raw,
                    will_retry=will_retry,
                )
            )
            if will_retry:
                await store.append(
                    RetryAttempted(
                        workflow_id=workflow_id,
                        agent_id=agent_id,
                        attempt_number=attempt + 1,
                        previous_error=str(exc),
                    )
                )

    raise RuntimeError(
        f"[{agent_id}] max retries ({max_retries}) exhausted. Last error: {last_error}"
    )
```

---

## `app/prompts/nl_to_sql.txt`

```
You are an expert SQL developer. Given a natural-language question and an optional database schema, generate a syntactically correct SQL query that answers the question.

Rules:
- Output ONLY the JSON object below. No markdown. No explanation. No code fences.
- If a schema is provided, use only the tables and columns it defines.
- If no schema is provided, use plausible generic table/column names and note your assumptions.
- Do NOT generate DROP, TRUNCATE, or DELETE statements unless the user's question explicitly requests data deletion.
- Prefer readable, well-formatted SQL.
- Always include a LIMIT clause for SELECT queries unless the question specifically asks for all rows.

Return this exact JSON structure:
{
  "sql": "<the complete SQL query>",
  "confidence": <float 0.0 to 1.0>,
  "assumptions": ["<assumption 1>", "<assumption 2>"]
}
```

---

## `app/prompts/explainer.txt`

```
You are a patient database teacher. Given a SQL query and an optional schema, explain exactly what the query does in plain English that a non-technical person can understand.

Rules:
- Output ONLY the JSON object below. No markdown. No explanation. No code fences.
- Walk through the query step by step: what tables are touched, what filters are applied, what is joined to what, what is aggregated, what is ordered, and what the result set looks like.
- Be concrete. Reference actual table and column names from the query.
- Keep the explanation under 150 words.

Return this exact JSON structure:
{
  "explanation": "<plain-English explanation>",
  "table_references": ["<table1>", "<table2>"]
}
```

---

## `app/prompts/risk_validator.txt`

```
You are a database security auditor. Given a SQL query, assess its safety and correctness.

Rules:
- Output ONLY the JSON object below. No markdown. No explanation. No code fences.
- risk_score must be a float from 0.0 (completely safe) to 1.0 (extremely dangerous).
- Assign high risk (>0.7) for: DELETE/UPDATE/DROP/TRUNCATE without a WHERE clause, DROP TABLE, TRUNCATE TABLE, queries that would affect all rows in a large table.
- Assign moderate risk (0.3-0.7) for: DELETE/UPDATE with a WHERE clause, missing LIMIT on large-table SELECTs, Cartesian joins, subqueries on unindexed columns.
- Assign low risk (<0.3) for: normal SELECT queries with proper filtering.
- validation_ok should be false only if the SQL has a clear syntax error.

Return this exact JSON structure:
{
  "risk_score": <float 0.0 to 1.0>,
  "risk_reasons": ["<reason 1>", "<reason 2>"],
  "validation_ok": <true or false>,
  "validation_notes": "<one sentence about SQL validity>"
}
```

---

## `app/prompts/rewrite.txt`

```
You are a SQL safety engineer. You have been given a SQL query that was flagged as risky, along with the specific risk reasons. Your job is to propose the MINIMAL edit that eliminates the identified risks without changing what the query is trying to do.

Rules:
- Output ONLY the JSON object below. No markdown. No explanation. No code fences.
- Make the smallest possible change. Do not rewrite the entire query.
- If a DELETE has no WHERE clause, add a specific WHERE clause that limits scope.
- If a DROP TABLE is requested, rewrite it as a comment explaining why it was removed.
- Explain your change in one sentence in rewrite_reason.

Return this exact JSON structure:
{
  "rewrite_sql": "<the safer SQL query>",
  "rewrite_reason": "<one sentence explaining the change>"
}
```

---

## `app/agents/schema_parser.py`

```python
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
            StatePatch(
                agent_id="schema_parser",
                target="tasks.parse_schema.status",
                value="complete",
                reason="Schema parsing complete",
            ),
        ]
```

---

## `app/agents/nl_to_sql.py`

```python
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
            StatePatch(
                agent_id="nl_to_sql",
                target="tasks.translate.status",
                value="complete",
                reason="Translation complete",
            ),
        ]
```

---

## `app/agents/explainer.py`

```python
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
            StatePatch(
                agent_id="explainer",
                target="tasks.explain.status",
                value="complete",
                reason="Explanation complete",
            ),
        ]
```

---

## `app/agents/risk_validator.py`

```python
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
            StatePatch(
                agent_id="risk_validator",
                target="tasks.validate_risk.status",
                value="complete",
                reason="Validation complete",
            ),
        ]
```

---

## `app/agents/rewrite.py`

```python
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
            StatePatch(
                agent_id="rewrite_agent",
                target="tasks.rewrite.status",
                value="complete",
                reason="Rewrite proposed",
            ),
        ]
```

---

## `app/agents/finalizer.py`

```python
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
            artifact_id=RESULT_ARTIFACT_ID,
            producer_id="finalizer",
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
                target="goals.sql_task.status",
                value="complete",
                reason="Workflow goal achieved",
            ),
            StatePatch(
                agent_id="finalizer",
                target="tasks.finalize.status",
                value="complete",
                reason="Finalization complete",
            ),
            StatePatch(
                agent_id="finalizer",
                target="status",
                value="complete",
                reason="Workflow complete",
            ),
        ]
```

---

## `app/graphs.py`

```python
"""
Two AgentGraph instances:
  - build_analysis_graph()  → runs all agents except finalizer
  - build_finalizer_graph() → runs only the finalizer

Keeping them separate means the approval gate in workflow.py
sits between the two graph.run() calls, which is simpler and
more debuggable than trying to pause a single graph mid-run.
"""
from __future__ import annotations

from openai import AsyncOpenAI

from agentstatelib import AgentGraph, StateStore

from app.agents.base import _build_client, _MODEL
from app.agents.schema_parser import SchemaParserAgent
from app.agents.nl_to_sql import NLToSQLAgent
from app.agents.explainer import ExplainerAgent
from app.agents.risk_validator import RiskValidatorAgent
from app.agents.rewrite import RewriteAgent
from app.agents.finalizer import FinalizerAgent


def build_analysis_graph(store: StateStore, client: AsyncOpenAI | None = None) -> AgentGraph:
    """
    Phase-1 graph: parse schema → translate/explain → validate risk → (optionally) rewrite.
    Does NOT include the finalizer — that runs in Phase 2 after any approval.
    """
    c = client or _build_client()

    schema_parser = SchemaParserAgent(store=store)
    nl_to_sql = NLToSQLAgent(store=store, client=c)
    explainer = ExplainerAgent(store=store, client=c)
    risk_validator = RiskValidatorAgent(store=store, client=c)
    rewrite = RewriteAgent(store=store, client=c)

    graph = AgentGraph(store=store)

    @graph.node("schema_parser", context=["workflow_id", "facts.schema_text", "facts.mode"])
    async def _schema_parser(ctx: dict):
        return await schema_parser(ctx)

    @graph.node("nl_to_sql", context=["workflow_id", "facts.nl_input", "facts.parsed_schema"])
    async def _nl_to_sql(ctx: dict):
        return await nl_to_sql(ctx)

    @graph.node("explainer", context=["workflow_id", "facts.mode", "facts.generated_sql", "facts.sql_input", "facts.parsed_schema"])
    async def _explainer(ctx: dict):
        return await explainer(ctx)

    @graph.node("risk_validator", context=["workflow_id", "facts.mode", "facts.generated_sql", "facts.sql_input"])
    async def _risk_validator(ctx: dict):
        return await risk_validator(ctx)

    @graph.node("rewrite_agent", context=["workflow_id", "facts.generated_sql", "facts.risk_reasons", "facts.risk_score"])
    async def _rewrite(ctx: dict):
        return await rewrite(ctx)

    # ── NL→SQL edges ─────────────────────────────────────────────────────────
    # schema_parser → nl_to_sql (only used when starting from schema_parser)
    graph.edge("schema_parser", "nl_to_sql")

    # nl_to_sql fans out to risk_validator AND explainer (parallel round)
    graph.edge("nl_to_sql", "risk_validator")
    graph.edge("nl_to_sql", "explainer")

    # risk_validator → rewrite_agent only when risk is high
    graph.edge(
        "risk_validator",
        "rewrite_agent",
        condition=lambda s: (s.get("facts") or {}).get("risk_score", 0.0) > 0.7,
    )

    # ── SQL→NL edges ─────────────────────────────────────────────────────────
    # schema_parser → explainer (used when starting from schema_parser in sql_to_nl mode)
    graph.edge("schema_parser", "explainer",
               condition=lambda s: (s.get("facts") or {}).get("mode") == "sql_to_nl")

    # explainer → risk_validator in sql_to_nl mode (info only, no approval gate)
    graph.edge(
        "explainer",
        "risk_validator",
        condition=lambda s: (s.get("facts") or {}).get("mode") == "sql_to_nl",
    )

    return graph


def build_finalizer_graph(store: StateStore) -> AgentGraph:
    """Phase-2 graph: just the finalizer."""
    finalizer = FinalizerAgent(store=store)
    graph = AgentGraph(store=store)

    @graph.node(
        "finalizer",
        context=[
            "workflow_id", "facts.mode", "facts.generated_sql", "facts.sql_input",
            "facts.sql_explanation", "facts.risk_score", "facts.risk_reasons",
            "facts.validation_ok", "facts.validation_notes",
            "facts.rewrite_proposal", "facts.rewrite_reason", "facts.rewrite_approved",
        ],
    )
    async def _finalizer(ctx: dict):
        return await finalizer(ctx)

    return graph
```

---

## `app/workflow.py`

```python
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
) -> tuple[SharedState, str | None]:
    """
    Run the SQL intelligence workflow.

    Returns (state, approval_id).
    If approval_id is not None, the workflow is paused awaiting human review.
    Call resolve_approval() with the returned approval_id to complete it.
    """
    if store is None:
        store = get_store()

    state = create_workflow_state(mode, nl_input, sql_input, schema_text)

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
```

---

## `app/cli.py`

The terminal entry point. Uses the library's `WorkflowDashboard` for live agent tracing, and Rich prompts for input collection and the approval gate.

```python
"""Terminal interface for SQLiq."""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from agentstatelib import SQLiteStore, WorkflowDashboard

from app.workflow import get_pending_approval, resolve_approval, run_workflow

load_dotenv()
console = Console()


def _banner() -> None:
    console.print()
    console.print(Rule("[bold]SQLiq[/bold]  ·  SQL Intelligence", style="blue"))
    console.print(
        "  Powered by [dim]agentstatelib[/dim]  ·  "
        f"Model: [cyan]{os.getenv('SQLIQ_MODEL', 'qwen2.5-coder:7b')}[/cyan]  ·  "
        f"Backend: [cyan]{os.getenv('SQLIQ_API_BASE', 'http://localhost:11434/v1')}[/cyan]"
    )
    console.print()


def _get_multiline(prompt_text: str) -> str:
    """Collect multi-line input until two consecutive blank lines."""
    console.print(f"[dim]{prompt_text}[/dim] [dim](blank line to finish)[/dim]")
    lines: list[str] = []
    while True:
        line = input()
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _show_approval_panel(state) -> None:
    facts = state.facts
    original = facts.get("generated_sql", "")
    proposal = facts.get("rewrite_proposal", "")
    reason = facts.get("rewrite_reason", "")
    score = facts.get("risk_score", 0.0)
    reasons = facts.get("risk_reasons", [])

    console.print()
    console.print(
        Panel(
            f"[bold red]Risk Score: {score:.2f}[/bold red]\n"
            + "\n".join(f"  • {r}" for r in reasons),
            title="⚠  Approval Required",
            border_style="red",
        )
    )
    console.print()
    console.print(
        Columns(
            [
                Panel(
                    Syntax(original, "sql", theme="github-dark", line_numbers=False),
                    title="[red]Original (risky)[/red]",
                    width=60,
                ),
                Panel(
                    Syntax(proposal, "sql", theme="github-dark", line_numbers=False),
                    title="[green]Proposed rewrite[/green]",
                    width=60,
                ),
            ]
        )
    )
    if reason:
        console.print(f"  [dim]Reason: {reason}[/dim]")
    console.print()


def _show_result(state) -> None:
    facts = state.facts
    mode = facts.get("mode", "nl_to_sql")
    sql = facts.get("final_sql") or ""
    explanation = facts.get("final_explanation") or ""
    risk_score = facts.get("risk_score")

    console.print()
    console.print(Rule("Result", style="green"))

    if mode == "nl_to_sql" and sql:
        console.print(
            Panel(
                Syntax(sql, "sql", theme="github-dark", line_numbers=True),
                title="Generated SQL",
                border_style="green",
            )
        )

    if explanation:
        console.print(
            Panel(Text(explanation), title="Explanation", border_style="blue")
        )

    if risk_score is not None:
        color = "green" if risk_score < 0.3 else ("yellow" if risk_score < 0.7 else "red")
        approved = facts.get("rewrite_approved")
        rewrite_note = ""
        if approved is True:
            rewrite_note = "  [green]Rewrite accepted.[/green]"
        elif approved is False:
            rewrite_note = "  [dim]Rewrite rejected — original kept.[/dim]"
        console.print(
            f"  Risk: [{color}]{risk_score:.2f}[/{color}]{rewrite_note}"
        )

    console.print()
    wf_id = state.workflow_id
    console.print(
        f"  [dim]Workflow ID: {wf_id}  ·  "
        f"Full trace: http://localhost:{os.getenv('SQLIQ_PORT', '8000')}/dashboard[/dim]"
    )
    console.print()


async def _run_with_dashboard(coro, event_queue):
    """Run a workflow coroutine alongside the library's WorkflowDashboard."""
    dashboard = WorkflowDashboard(event_queue)
    results = await asyncio.gather(coro, dashboard.run(), return_exceptions=False)
    return results[0]  # coro result; dashboard.run() returns None


async def main() -> None:
    _banner()

    # ── Mode selection ────────────────────────────────────────────────────────
    mode_choice = Prompt.ask(
        "  What would you like to do?",
        choices=["1", "2"],
        default="1",
        show_choices=False,
        show_default=False,
    )
    console.print("  [dim]1 = NL → SQL    2 = SQL → Plain English[/dim]\n")

    nl_input: str | None = None
    sql_input: str | None = None

    if mode_choice == "1":
        nl_input = Prompt.ask("  Your question")
        mode = "nl_to_sql"
    else:
        sql_input = _get_multiline("  Paste your SQL")
        mode = "sql_to_nl"

    schema_raw = Prompt.ask(
        "  Schema DDL [dim](optional — press Enter to skip)[/dim]",
        default="",
    )
    schema_text = schema_raw.strip() or None

    store = SQLiteStore(os.getenv("SQLIQ_DB_PATH", "sqliq.db"))
    console.print()

    # ── Phase 1: analysis agents ──────────────────────────────────────────────
    event_queue: asyncio.Queue = asyncio.Queue()
    result = await _run_with_dashboard(
        run_workflow(
            mode=mode,
            nl_input=nl_input,
            sql_input=sql_input,
            schema_text=schema_text,
            store=store,
            event_queue=event_queue,
        ),
        event_queue,
    )
    state, approval_id = result

    # ── Approval gate (only when risk is high) ────────────────────────────────
    if approval_id:
        _show_approval_panel(state)
        decision_choice = Prompt.ask(
            "  Decision",
            choices=["a", "r", "m"],
            default="a",
        )
        console.print("  [dim]a = approve rewrite    r = reject (keep original)    m = modify[/dim]\n")
        modified_sql: str | None = None
        if decision_choice == "m":
            modified_sql = _get_multiline("  Enter your modified SQL")

        decision_map = {"a": "approved", "r": "rejected", "m": "modified"}

        event_queue2: asyncio.Queue = asyncio.Queue()
        state = await _run_with_dashboard(
            resolve_approval(
                workflow_id=state.workflow_id,
                decision=decision_map[decision_choice],
                modified_sql=modified_sql,
                event_queue=event_queue2,
            ),
            event_queue2,
        )

    _show_result(state)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## `app/api/routes.py`

```python
"""SQLiq-specific FastAPI routes. Mounted at /api."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, model_validator

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

    background_tasks.add_task(
        _background_run_with_id, req, store, workflow_id
    )
    return RunResponse(workflow_id=workflow_id)


async def _background_run_with_id(req: RunRequest, store, workflow_id: str) -> None:
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


@router.get("/result/{workflow_id}")
async def get_result(workflow_id: str) -> dict:
    entry = _workflow_states.get(workflow_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Workflow not found")

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
        raise HTTPException(status_code=404, detail="No pending approval for this workflow")

    state = await resolve_approval(
        workflow_id=workflow_id,
        decision=body.decision,
        modified_sql=body.modified_sql,
    )
    _workflow_states[workflow_id] = {"state": state, "approval_id": None}
    return {"status": "resolved", "decision": body.decision}
```

---

## `app/api/server.py`

```python
"""Assemble the FastAPI application."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agentstatelib.api import create_app as create_library_app

from app.api.routes import router as sqliq_router


def create_app() -> FastAPI:
    db_path = os.getenv("SQLIQ_DB_PATH", "sqliq.db")

    # The library's app provides:
    #   GET/POST  /v1/workflows/...      (state CRUD)
    #   GET       /v1/workflows/{id}/events  (SSE stream)
    #   GET/POST  /v1/workflows/{id}/approvals/...
    #   GET       /v1/workflows/{id}/turns
    #   GET       /dashboard             (library's built-in trace dashboard)
    app = create_library_app(db_path=db_path)

    # Add SQLiq-specific routes (/api/run, /api/result/{id}, /api/approve/{id})
    app.include_router(sqliq_router)

    # Serve the compiled frontend (npm run build outputs to frontend/dist/)
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
    if os.path.isdir(frontend_dir):
        app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app
```

---

## `main.py`

```python
"""
SQLiq entry points.

  python main.py          → start web server (default)
  python main.py server   → start web server
  python main.py chat     → launch terminal dashboard
"""
from __future__ import annotations

import sys


def _serve() -> None:
    import os
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv()
    from app.api.server import create_app
    app = create_app()
    uvicorn.run(
        app,
        host=os.getenv("SQLIQ_HOST", "0.0.0.0"),
        port=int(os.getenv("SQLIQ_PORT", "8000")),
        reload=False,
    )


def _chat() -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    from app.cli import main
    asyncio.run(main())


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "server"
    if command == "chat":
        _chat()
    else:
        _serve()
```

---

## Frontend Setup

The frontend is a **React 18 + TypeScript + Vite + Tailwind CSS** SPA. During development, Vite's proxy forwards `/api` and `/v1` requests to the FastAPI backend, so you only need two terminals.

```
# One-time setup (from repo root)
cd frontend
npm install

# Development — Vite dev server with HMR at http://localhost:5173
npm run dev

# Production build — outputs to frontend/dist/ (served by FastAPI at /ui/)
npm run build
```

---

## `frontend/package.json`

```json
{
  "name": "sqliq-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.27.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.15",
    "typescript": "^5.6.3",
    "vite": "^5.4.10"
  }
}
```

---

## `frontend/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

---

## `frontend/vite.config.ts`

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/v1':  'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
```

---

## `frontend/tailwind.config.ts`

```typescript
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:           '#F7F6F3',
        surface:      '#FFFFFF',
        border:       '#E4E4E7',
        text:         '#18181B',
        muted:        '#71717A',
        accent:       '#2563EB',
        'accent-dark':'#1D4ED8',
        success:      '#16A34A',
        warning:      '#CA8A04',
        danger:       '#DC2626',
        'code-bg':    '#F4F4F5',
      },
      fontFamily: {
        mono: ['SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
```

---

## `frontend/postcss.config.js`

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

---

## `frontend/index.html`

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SQLiq — SQL Intelligence</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

---

## `frontend/src/index.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --font-mono: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  }

  body {
    @apply bg-bg text-text text-[15px] leading-relaxed;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }

  textarea,
  input {
    font-family: var(--font-mono);
  }
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
.animate-pulse-dot {
  animation: pulse-dot 1.2s ease-in-out infinite;
}
```

---

## `frontend/src/main.tsx`

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
```

---

## `frontend/src/App.tsx`

```tsx
import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Workflow from './pages/Workflow'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/workflow" element={<Workflow />} />
    </Routes>
  )
}
```

---

## `frontend/src/types.ts`

```typescript
export type Mode = 'nl_to_sql' | 'sql_to_nl'

export interface RunRequest {
  mode: Mode
  nl_input?: string
  sql_input?: string
  schema_text?: string
}

export interface RunResponse {
  workflow_id: string
  status: string
}

export interface PendingApproval {
  approval_id: string
  workflow_id: string
  original_sql: string
  rewrite_proposal: string
  rewrite_reason: string
  risk_score: number
  risk_reasons: string[]
}

export interface WorkflowResult {
  workflow_id: string
  status: 'running' | 'complete' | 'awaiting_approval' | 'failed'
  mode: Mode
  final_sql: string | null
  final_explanation: string | null
  generated_sql: string | null
  sql_explanation: string | null
  risk_score: number | null
  risk_reasons: string[]
  validation_ok: boolean | null
  validation_notes: string | null
  pending_approval: PendingApproval | null
}

export interface ApproveRequest {
  decision: 'approved' | 'rejected' | 'modified'
  modified_sql?: string
}

export interface TraceEvent {
  event_type?: string
  type?: string
  agent_id?: string
  latency_seconds?: number
  input_tokens?: number
  output_tokens?: number
  attempt_number?: number
  target?: string
  path?: string
  winner_agent_id?: string
  decision?: string
}
```

---

## `frontend/src/api.ts`

```typescript
import type { ApproveRequest, RunRequest, RunResponse, WorkflowResult } from './types'

const API_KEY = 'dev-key-change-me' // must match AGENTSTATE_API_KEYS in .env

const headers = {
  'Content-Type': 'application/json',
  'x-api-key': API_KEY,
}

export async function startWorkflow(req: RunRequest): Promise<RunResponse> {
  const res = await fetch('/api/run', { method: 'POST', headers, body: JSON.stringify(req) })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getResult(workflowId: string): Promise<WorkflowResult> {
  const res = await fetch(`/api/result/${workflowId}`, { headers })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitApproval(workflowId: string, body: ApproveRequest): Promise<void> {
  const res = await fetch(`/api/approve/${workflowId}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
}
```

---

## `frontend/src/components/Header.tsx`

```tsx
import { Link } from 'react-router-dom'

interface HeaderProps {
  tagline?: string
}

export default function Header({ tagline }: HeaderProps) {
  return (
    <header className="bg-surface border-b border-border sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 py-3.5 flex items-center gap-4">
        <Link
          to="/"
          className="text-[18px] font-bold tracking-tight text-text no-underline"
        >
          SQLiq
        </Link>
        {tagline && (
          <span className="text-muted text-[13px] flex-1">{tagline}</span>
        )}
        <a
          href="/dashboard"
          target="_blank"
          rel="noreferrer"
          className="text-[13px] text-accent no-underline px-2.5 py-1 border border-border rounded-md hover:bg-code-bg"
        >
          Agent Dashboard ↗
        </a>
      </div>
    </header>
  )
}
```

---

## `frontend/src/components/TracePanel.tsx`

```tsx
import { useEffect, useRef, useState } from 'react'
import type { TraceEvent } from '../types'

interface TraceItem {
  color: 'green' | 'amber' | 'red' | 'gray' | 'blue'
  time: string
  text: string
}

interface TracePanelProps {
  workflowId: string
  onApprovalRequested: () => void
  onComplete: () => void
}

const DOT_CLASSES: Record<TraceItem['color'], string> = {
  green: 'bg-success',
  amber: 'bg-warning',
  red:   'bg-danger',
  gray:  'bg-muted',
  blue:  'bg-accent',
}

function formatEventLabel(ev: TraceEvent): { color: TraceItem['color']; text: string } | null {
  const agent = ev.agent_id ?? 'system'
  const type  = ev.event_type ?? ev.type ?? ''

  switch (type) {
    case 'workflow_started':
      return { color: 'blue',  text: '<strong>workflow started</strong>' }
    case 'context_sliced':
      return { color: 'gray',  text: `<strong>${agent}</strong> — context ready` }
    case 'prompt_assembled':
      return { color: 'gray',  text: `<strong>${agent}</strong> — prompt built (attempt ${(ev.attempt_number ?? 0) + 1})` }
    case 'model_called':
      return { color: 'amber', text: `<strong>${agent}</strong> — calling model…` }
    case 'model_returned': {
      const ms  = ev.latency_seconds ? (ev.latency_seconds * 1000).toFixed(0) : '?'
      const tok = (ev.input_tokens ?? 0) + (ev.output_tokens ?? 0)
      return { color: 'green', text: `<strong>${agent}</strong> — responded in ${ms}ms · ${tok} tokens` }
    }
    case 'validation_failed':
      return { color: 'red',   text: `<strong>${agent}</strong> — JSON parse failed (attempt ${(ev.attempt_number ?? 0) + 1}), retrying…` }
    case 'retry_attempted':
      return { color: 'amber', text: `<strong>${agent}</strong> — retry ${ev.attempt_number}` }
    case 'patch_applied':
      return { color: 'green', text: `<strong>${agent}</strong> — updated <code class="bg-code-bg px-1 rounded text-[11px]">${ev.target}</code>` }
    case 'conflict_detected':
      return { color: 'red',   text: `conflict on <code class="bg-code-bg px-1 rounded text-[11px]">${ev.path}</code> — ${ev.winner_agent_id} wins` }
    case 'human_approval_requested':
      return { color: 'amber', text: '<strong>approval gate</strong> — rewrite proposed' }
    case 'human_approval_resolved':
      return { color: 'blue',  text: `<strong>approval resolved</strong> — ${ev.decision}` }
    case 'workflow_completed':
      return { color: 'blue',  text: '<strong>workflow complete</strong>' }
    default:
      return null
  }
}

export default function TracePanel({ workflowId, onApprovalRequested, onComplete }: TracePanelProps) {
  const [items,  setItems]  = useState<TraceItem[]>([])
  const [stats,  setStats]  = useState({ tokens: 0, calls: 0, retries: 0 })
  const startTs  = useRef(Date.now())
  const bottomRef = useRef<HTMLDivElement>(null)
  const API_KEY  = 'dev-key-change-me'

  useEffect(() => {
    const sse = new EventSource(`/v1/workflows/${workflowId}/events?key=${API_KEY}`)
    let tokens = 0, calls = 0, retries = 0

    function addItem(color: TraceItem['color'], text: string) {
      const time = ((Date.now() - startTs.current) / 1000).toFixed(1)
      setItems(prev => [...prev, { color, time, text }])
      setTimeout(() => bottomRef.current?.scrollIntoView({ block: 'nearest' }), 0)
    }

    sse.onmessage = (e) => {
      let ev: TraceEvent
      try { ev = JSON.parse(e.data) } catch { return }

      const type   = ev.event_type ?? ev.type ?? ''
      const label  = formatEventLabel(ev)
      if (label) addItem(label.color, label.text)

      if (type === 'model_returned') {
        tokens += (ev.input_tokens ?? 0) + (ev.output_tokens ?? 0)
        calls++
        setStats({ tokens, calls, retries })
      }
      if (type === 'validation_failed') {
        retries++
        setStats({ tokens, calls, retries })
      }
      if (type === 'human_approval_requested') { onApprovalRequested(); sse.close() }
      if (type === 'workflow_completed')        { onComplete();          sse.close() }
    }

    sse.onerror = () => sse.close()
    return () => sse.close()
  }, [workflowId, onApprovalRequested, onComplete])

  const elapsed = ((Date.now() - startTs.current) / 1000).toFixed(1)

  return (
    <aside className="bg-surface border border-border rounded-[10px] p-4 sticky top-[70px] max-h-[calc(100vh-90px)] overflow-y-auto">
      <div className="flex justify-between items-center text-[13px] font-semibold mb-3 pb-2.5 border-b border-border">
        <span>Live Agent Trace</span>
        <a href="/dashboard" target="_blank" rel="noreferrer" className="text-[12px] text-accent no-underline">
          Full trace ↗
        </a>
      </div>

      <ul className="flex flex-col gap-1 list-none">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 items-start text-[12px] px-1.5 py-1 rounded-[6px] hover:bg-code-bg">
            <span className={`w-[7px] h-[7px] rounded-full flex-shrink-0 mt-1 ${DOT_CLASSES[item.color]}`} />
            <span className="text-muted flex-shrink-0 tabular-nums">{item.time}s</span>
            <span
              className="text-text leading-[1.4]"
              dangerouslySetInnerHTML={{ __html: item.text }}
            />
          </li>
        ))}
        <div ref={bottomRef} />
      </ul>

      {items.length > 0 && (
        <div className="mt-3 pt-2.5 border-t border-border text-[12px] text-muted leading-[1.8]">
          {stats.tokens} tokens · {stats.calls} LLM calls<br />
          {stats.retries} retries · {elapsed}s elapsed
        </div>
      )}
    </aside>
  )
}
```

---

## `frontend/src/components/ApprovalBox.tsx`

```tsx
import { useState } from 'react'
import { submitApproval } from '../api'
import type { PendingApproval } from '../types'

interface ApprovalBoxProps {
  approval: PendingApproval
  onResolved: () => void
}

function riskClass(score: number) {
  if (score < 0.3) return 'bg-green-100 text-success'
  if (score < 0.7) return 'bg-yellow-100 text-warning'
  return 'bg-red-100 text-danger'
}

function riskLabel(score: number) {
  if (score < 0.3) return `Risk ${score.toFixed(2)} — Safe`
  if (score < 0.7) return `Risk ${score.toFixed(2)} — Moderate`
  return `Risk ${score.toFixed(2)} — High`
}

export default function ApprovalBox({ approval, onResolved }: ApprovalBoxProps) {
  const [modifyOpen,  setModifyOpen]  = useState(false)
  const [modifiedSql, setModifiedSql] = useState(approval.rewrite_proposal)
  const [loading,     setLoading]     = useState(false)

  async function decide(decision: 'approved' | 'rejected' | 'modified') {
    setLoading(true)
    await submitApproval(approval.workflow_id, {
      decision,
      ...(decision === 'modified' ? { modified_sql: modifiedSql } : {}),
    })
    onResolved()
  }

  return (
    <div className="bg-surface border border-red-300 rounded-[10px] p-5 mb-5">
      <div className="flex items-center gap-2.5 mb-2">
        <span className={`text-[12px] font-semibold px-2 py-0.5 rounded ${riskClass(approval.risk_score)}`}>
          {riskLabel(approval.risk_score)}
        </span>
        <strong>Approval Required</strong>
      </div>

      <p className="text-muted text-[13px] mb-4">
        {approval.risk_reasons.map(r => `• ${r}`).join('  ')}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3.5">
        <div>
          <div className="text-[12px] font-semibold text-danger mb-1">Original (risky)</div>
          <pre className="font-mono text-[13px] bg-code-bg rounded-[6px] p-3.5 whitespace-pre-wrap break-words overflow-x-auto m-0">
            {approval.original_sql}
          </pre>
        </div>
        <div>
          <div className="text-[12px] font-semibold text-success mb-1">Proposed rewrite</div>
          <pre className="font-mono text-[13px] bg-code-bg rounded-[6px] p-3.5 whitespace-pre-wrap break-words overflow-x-auto m-0">
            {approval.rewrite_proposal}
          </pre>
        </div>
      </div>

      {approval.rewrite_reason && (
        <p className="text-muted text-[13px] mb-3.5">Reason: {approval.rewrite_reason}</p>
      )}

      <div className="flex gap-2.5 flex-wrap">
        <button
          onClick={() => decide('approved')}
          disabled={loading}
          className="bg-success text-white text-[14px] font-medium rounded-[6px] px-5 py-2 disabled:opacity-50"
        >
          ✓ Approve Rewrite
        </button>
        <button
          onClick={() => decide('rejected')}
          disabled={loading}
          className="bg-transparent text-text border border-border text-[14px] font-medium rounded-[6px] px-5 py-2 hover:bg-code-bg disabled:opacity-50"
        >
          ✕ Keep Original
        </button>
        <button
          onClick={() => setModifyOpen(o => !o)}
          className="bg-transparent text-text border border-border text-[14px] font-medium rounded-[6px] px-5 py-2 hover:bg-code-bg"
        >
          ✎ Modify…
        </button>
      </div>

      {modifyOpen && (
        <div className="mt-3.5 flex flex-col gap-2">
          <textarea
            value={modifiedSql}
            onChange={e => setModifiedSql(e.target.value)}
            rows={6}
            placeholder="Edit the SQL here…"
            className="font-mono text-[13px] bg-code-bg border border-border rounded-[6px] px-3 py-2.5 resize-y outline-none focus:border-accent"
          />
          <button
            onClick={() => decide('modified')}
            disabled={loading || !modifiedSql.trim()}
            className="self-start bg-accent hover:bg-accent-dark text-white text-[14px] font-medium rounded-[6px] px-5 py-2 disabled:opacity-50"
          >
            Submit Modified SQL
          </button>
        </div>
      )}
    </div>
  )
}
```

---

## `frontend/src/components/ResultBox.tsx`

```tsx
import type { WorkflowResult } from '../types'

interface ResultBoxProps {
  result: WorkflowResult
}

function riskClass(score: number) {
  if (score < 0.3) return 'bg-green-100 text-success'
  if (score < 0.7) return 'bg-yellow-100 text-warning'
  return 'bg-red-100 text-danger'
}

function riskLabel(score: number) {
  if (score < 0.3) return `Risk ${score.toFixed(2)} — Safe`
  if (score < 0.7) return `Risk ${score.toFixed(2)} — Moderate`
  return `Risk ${score.toFixed(2)} — High`
}

function CopyButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => navigator.clipboard.writeText(text)}
      className="text-[12px] text-muted bg-transparent border border-border rounded px-2 py-0.5 cursor-pointer hover:bg-code-bg"
    >
      Copy
    </button>
  )
}

export default function ResultBox({ result }: ResultBoxProps) {
  const isNL = result.mode === 'nl_to_sql'

  return (
    <div className="flex flex-col gap-4">
      {isNL && result.final_sql && (
        <div className="bg-surface border border-border rounded-[10px] overflow-hidden">
          <div className="flex justify-between items-center px-4 py-2.5 border-b border-border text-[13px] font-medium">
            <span>Generated SQL</span>
            <CopyButton text={result.final_sql} />
          </div>
          <pre className="font-mono text-[13px] leading-relaxed p-4 bg-code-bg whitespace-pre-wrap break-words overflow-x-auto m-0">
            {result.final_sql}
          </pre>
        </div>
      )}

      <div className="bg-surface border border-border rounded-[10px] overflow-hidden">
        <div className="flex justify-between items-center px-4 py-2.5 border-b border-border text-[13px] font-medium">
          <span>Explanation</span>
          <CopyButton text={result.final_explanation ?? ''} />
        </div>
        <p className="px-4 py-3.5 leading-[1.7] text-[14px]">
          {result.final_explanation ?? '(no explanation generated)'}
        </p>
      </div>

      <div className="flex items-center gap-3 py-1">
        {result.risk_score != null && (
          <span className={`text-[12px] font-semibold px-2 py-0.5 rounded ${riskClass(result.risk_score)}`}>
            {riskLabel(result.risk_score)}
          </span>
        )}
        {result.validation_notes && (
          <span className="text-[13px] text-muted">{result.validation_notes}</span>
        )}
      </div>
    </div>
  )
}
```

---

## `frontend/src/pages/Home.tsx`

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Header from '../components/Header'
import { startWorkflow } from '../api'
import type { Mode } from '../types'

function ModeCard({ mode }: { mode: Mode }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)
  const isNL = mode === 'nl_to_sql'

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const payload = {
      mode,
      ...(isNL
        ? { nl_input: fd.get('nl_input') as string }
        : { sql_input: fd.get('sql_input') as string }),
      ...(fd.get('schema_text') ? { schema_text: fd.get('schema_text') as string } : {}),
    }
    setLoading(true)
    setError(null)
    try {
      const { workflow_id } = await startWorkflow(payload)
      navigate(`/workflow?id=${workflow_id}`)
    } catch (err) {
      setError(String(err))
      setLoading(false)
    }
  }

  const textareaClass =
    'font-mono text-[13px] bg-code-bg border border-border rounded-[6px] px-3 py-2.5 resize-y outline-none focus:border-accent'

  return (
    <div className="bg-surface border border-border rounded-[10px] p-7 shadow-sm">
      <div className="flex items-center gap-2.5 mb-2">
        <span className="text-xl">{isNL ? '⟶' : '⟵'}</span>
        <h2 className="text-[17px] font-semibold">
          {isNL ? 'Natural Language → SQL' : 'SQL → Plain English'}
        </h2>
      </div>
      <p className="text-muted text-sm mb-5">
        {isNL
          ? 'Ask a question about your data in plain English and get a SQL query back.'
          : 'Paste a SQL query and get a plain-English explanation of what it does.'}
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
        {isNL ? (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Your question
            <textarea
              name="nl_input"
              rows={3}
              required
              placeholder="Show me the top 10 customers by total order value in the last 90 days"
              className={textareaClass}
            />
          </label>
        ) : (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Your SQL
            <textarea
              name="sql_input"
              rows={6}
              required
              placeholder={
                'SELECT c.name, SUM(o.total) AS revenue\n' +
                'FROM customers c\n' +
                'JOIN orders o ON c.id = o.customer_id\n' +
                'GROUP BY c.id, c.name\n' +
                'ORDER BY revenue DESC\n' +
                'LIMIT 10'
              }
              className={textareaClass}
            />
          </label>
        )}

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Schema DDL{' '}
          <span className="font-normal text-muted">(optional)</span>
          <textarea
            name="schema_text"
            rows={3}
            placeholder="CREATE TABLE customers (id INT, name TEXT, ...);"
            className={textareaClass}
          />
        </label>

        {error && <p className="text-danger text-[13px]">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="bg-accent hover:bg-accent-dark text-white text-[14px] font-medium rounded-[6px] px-5 py-2.5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Starting…' : isNL ? 'Generate SQL →' : 'Explain SQL →'}
        </button>
      </form>
    </div>
  )
}

export default function Home() {
  return (
    <>
      <Header tagline="SQL Intelligence · powered by agentstatelib" />
      <main className="max-w-6xl mx-auto px-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-10">
          <ModeCard mode="nl_to_sql" />
          <ModeCard mode="sql_to_nl" />
        </div>
      </main>
    </>
  )
}
```

---

## `frontend/src/pages/Workflow.tsx`

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Header from '../components/Header'
import TracePanel from '../components/TracePanel'
import ApprovalBox from '../components/ApprovalBox'
import ResultBox from '../components/ResultBox'
import { getResult } from '../api'
import type { WorkflowResult } from '../types'

type PageStatus = 'running' | 'awaiting_approval' | 'complete' | 'failed'

function StatusBar({ status }: { status: PageStatus }) {
  const dotClass = {
    running:           'bg-warning animate-pulse-dot',
    awaiting_approval: 'bg-danger',
    complete:          'bg-success',
    failed:            'bg-danger',
  }[status]

  const label = {
    running:           'Agents are running…',
    awaiting_approval: 'Awaiting your approval',
    complete:          'Complete',
    failed:            'Failed',
  }[status]

  return (
    <div className="flex items-center gap-2 px-4 py-2.5 bg-surface border border-border rounded-[10px] mb-4 text-[14px]">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotClass}`} />
      <span>{label}</span>
    </div>
  )
}

export default function Workflow() {
  const [params]    = useSearchParams()
  const wfId        = params.get('id')
  const [status,    setStatus]    = useState<PageStatus>('running')
  const [result,    setResult]    = useState<WorkflowResult | null>(null)
  const [modeLabel, setModeLabel] = useState('Loading…')
  const pollRef     = useRef<ReturnType<typeof setTimeout> | null>(null)

  const poll = useCallback(async () => {
    if (!wfId) return
    try {
      const data = await getResult(wfId)
      setModeLabel(data.mode === 'nl_to_sql' ? 'NL → SQL' : 'SQL → Plain English')
      if (data.status === 'awaiting_approval') {
        setStatus('awaiting_approval')
        setResult(data)
      } else if (data.status === 'complete') {
        setStatus('complete')
        setResult(data)
      } else if (data.status === 'running') {
        pollRef.current = setTimeout(poll, 2500)
      }
    } catch {
      pollRef.current = setTimeout(poll, 3000)
    }
  }, [wfId])

  useEffect(() => {
    pollRef.current = setTimeout(poll, 3000)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [poll])

  const handleApprovalRequested = useCallback(() => {
    setStatus('awaiting_approval')
    poll()
  }, [poll])

  const handleComplete = useCallback(() => {
    setStatus('complete')
    poll()
  }, [poll])

  const handleApprovalResolved = useCallback(() => {
    setStatus('running')
    pollRef.current = setTimeout(poll, 1500)
  }, [poll])

  if (!wfId) {
    return (
      <>
        <Header />
        <main className="max-w-6xl mx-auto px-6 mt-6">
          <p className="text-muted">No workflow ID in URL.</p>
        </main>
      </>
    )
  }

  return (
    <>
      <Header tagline={modeLabel} />
      <main className="max-w-6xl mx-auto px-6 mt-6 grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6 items-start">
        <section>
          <StatusBar status={status} />

          {status === 'awaiting_approval' && result?.pending_approval && (
            <ApprovalBox
              approval={result.pending_approval}
              onResolved={handleApprovalResolved}
            />
          )}

          {status === 'complete' && result && (
            <ResultBox result={result} />
          )}
        </section>

        <TracePanel
          workflowId={wfId}
          onApprovalRequested={handleApprovalRequested}
          onComplete={handleComplete}
        />
      </main>
    </>
  )
}
```

---

## `notebooks/colab_ollama_backend.ipynb` — Setup Steps

Create this as a Colab notebook with these cells. Use "Text" cells for headings and "Code" cells for the commands:

**Cell 1 — Install Ollama:**
```bash
!curl -fsSL https://ollama.com/install.sh | sh
```

**Cell 2 — Start Ollama server:**
```python
import subprocess, time
proc = subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)
print("Ollama server started")
```

**Cell 3 — Pull the model:**
```bash
!ollama pull qwen2.5-coder:7b
```

**Cell 4 — Expose via ngrok:**
```python
from google.colab import userdata
from pyngrok import ngrok

# Set your ngrok auth token in Colab Secrets (key: NGROK_TOKEN)
ngrok.set_auth_token(userdata.get('NGROK_TOKEN'))
tunnel = ngrok.connect(11434)
base_url = tunnel.public_url

print("=" * 60)
print(f"Add these to your .env file:")
print(f"SQLIQ_API_BASE={base_url}/v1")
print(f"SQLIQ_API_KEY=ollama")
print(f"SQLIQ_MODEL=qwen2.5-coder:7b")
print("=" * 60)
```

**Cell 5 — Keep-alive (run last):**
```python
# Keep Colab session alive while you use SQLiq
import time
while True:
    time.sleep(60)
    print(".", end="", flush=True)
```

---

## `tests/conftest.py`

```python
"""Shared fixtures for SQLiq tests."""
import asyncio
import json
import pytest
from agentstatelib import InMemoryStore


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def fake_client_factory():
    """
    Returns a factory that builds a fake AsyncOpenAI-compatible client.
    The responses list is consumed in order; the last item is repeated.
    Pass a list of strings (raw model responses) or dicts (auto-serialised to JSON).
    """
    from unittest.mock import AsyncMock, MagicMock

    def _make(responses: list):
        client = MagicMock()
        serialised = [
            r if isinstance(r, str) else json.dumps(r)
            for r in responses
        ]
        call_count = [-1]

        async def _create(**kwargs):
            call_count[0] += 1
            idx = min(call_count[0], len(serialised) - 1)
            raw = serialised[idx]
            choice = MagicMock()
            choice.message.content = raw
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage.prompt_tokens = 100
            resp.usage.completion_tokens = 50
            return resp

        client.chat.completions.create = _create
        return client

    return _make
```

---

## `tests/test_e2e_nl_to_sql.py`

```python
"""End-to-end NL→SQL workflow with mocked model calls."""
import pytest
from agentstatelib import InMemoryStore, WorkflowCompleted, WorkflowStarted, PatchApplied

from app.workflow import run_workflow
from app.graphs import build_analysis_graph, build_finalizer_graph
from app.agents.nl_to_sql import NLToSQLAgent
from app.agents.explainer import ExplainerAgent
from app.agents.risk_validator import RiskValidatorAgent


@pytest.mark.asyncio
async def test_nl_to_sql_safe_completes(store, fake_client_factory):
    """Full NL→SQL workflow with low risk completes without approval."""
    nl_resp  = {"sql": "SELECT * FROM users LIMIT 10", "confidence": 0.9, "assumptions": []}
    exp_resp = {"explanation": "Fetches all users, up to 10.", "table_references": ["users"]}
    risk_resp = {"risk_score": 0.1, "risk_reasons": [], "validation_ok": True, "validation_notes": "Safe SELECT."}

    client = fake_client_factory([
        nl_resp, exp_resp, risk_resp
    ])

    # Patch agents to use fake client
    import app.graphs as graphs_mod
    original_build = graphs_mod.build_analysis_graph

    def patched_build(store, c=None):
        return original_build(store, client=client)

    graphs_mod.build_analysis_graph = patched_build
    try:
        state, approval_id = await run_workflow(
            mode="nl_to_sql",
            nl_input="Show me all users",
            store=store,
        )
    finally:
        graphs_mod.build_analysis_graph = original_build

    assert approval_id is None, "Safe workflow should not require approval"
    assert state.status == "complete"
    assert state.facts["generated_sql"] == "SELECT * FROM users LIMIT 10"
    assert state.facts["final_sql"] == "SELECT * FROM users LIMIT 10"
    assert state.facts["risk_score"] == pytest.approx(0.1)
    assert state.facts["sql_explanation"] is not None
    assert "result" in state.artifacts

    events = await store.get_workflow(state.workflow_id)
    types = [type(e).__name__ for e in events]
    assert "WorkflowStarted" in types
    assert "PatchApplied" in types
    assert "WorkflowCompleted" in types
```

---

## `tests/test_approval_flow.py`

```python
"""Approval gate: high-risk SQL pauses workflow; approve and reject paths both work."""
import pytest
from app.workflow import run_workflow, resolve_approval


async def _run_high_risk(store, fake_client_factory):
    nl_resp   = {"sql": "DELETE FROM orders", "confidence": 0.8, "assumptions": []}
    risk_resp = {
        "risk_score": 0.85,
        "risk_reasons": ["DELETE without WHERE clause"],
        "validation_ok": True,
        "validation_notes": "Dangerous.",
    }
    rw_resp   = {"rewrite_sql": "DELETE FROM orders WHERE created_at < NOW() - INTERVAL '1 year'", "rewrite_reason": "Added time-bound guard."}
    exp_resp  = {"explanation": "Deletes orders.", "table_references": ["orders"]}

    client = fake_client_factory([nl_resp, exp_resp, risk_resp, rw_resp])

    import app.graphs as g
    orig = g.build_analysis_graph
    g.build_analysis_graph = lambda s, c=None: orig(s, client=client)
    try:
        state, approval_id = await run_workflow(
            mode="nl_to_sql", nl_input="Delete all orders", store=store
        )
    finally:
        g.build_analysis_graph = orig

    return state, approval_id


@pytest.mark.asyncio
async def test_high_risk_pauses_for_approval(store, fake_client_factory):
    state, approval_id = await _run_high_risk(store, fake_client_factory)
    assert approval_id is not None
    assert state.status != "complete"
    assert state.facts["risk_score"] > 0.7
    assert state.facts["rewrite_proposal"] is not None


@pytest.mark.asyncio
async def test_approve_applies_rewrite(store, fake_client_factory):
    state, approval_id = await _run_high_risk(store, fake_client_factory)
    wf_id = state.workflow_id

    final = await resolve_approval(workflow_id=wf_id, decision="approved")
    assert final.status == "complete"
    assert final.facts["rewrite_approved"] is True
    assert final.facts["final_sql"] == state.facts["rewrite_proposal"]


@pytest.mark.asyncio
async def test_reject_keeps_original(store, fake_client_factory):
    state, approval_id = await _run_high_risk(store, fake_client_factory)
    wf_id = state.workflow_id
    original_sql = state.facts["generated_sql"]

    final = await resolve_approval(workflow_id=wf_id, decision="rejected")
    assert final.status == "complete"
    assert final.facts["rewrite_approved"] is False
    assert final.facts["final_sql"] == original_sql


@pytest.mark.asyncio
async def test_modify_uses_custom_sql(store, fake_client_factory):
    state, approval_id = await _run_high_risk(store, fake_client_factory)
    custom = "DELETE FROM orders WHERE id = 999"

    final = await resolve_approval(
        workflow_id=state.workflow_id,
        decision="modified",
        modified_sql=custom,
    )
    assert final.facts["final_sql"] == custom
```

---

## `tests/test_trace_events.py`

```python
"""Verify event log completeness and ordering."""
import pytest
from agentstatelib import (
    ModelCalled, ModelReturned, PatchApplied,
    PromptAssembled, WorkflowCompleted, WorkflowStarted,
    get_agent_turns, analyze_workflow,
)
from app.workflow import run_workflow


@pytest.mark.asyncio
async def test_event_ordering(store, fake_client_factory):
    client = fake_client_factory([
        {"sql": "SELECT 1", "confidence": 0.9, "assumptions": []},
        {"explanation": "Selects one.", "table_references": []},
        {"risk_score": 0.05, "risk_reasons": [], "validation_ok": True, "validation_notes": "Safe."},
    ])
    import app.graphs as g
    orig = g.build_analysis_graph
    g.build_analysis_graph = lambda s, c=None: orig(s, client=client)
    try:
        state, _ = await run_workflow(mode="nl_to_sql", nl_input="Test", store=store)
    finally:
        g.build_analysis_graph = orig

    events = await store.get_workflow(state.workflow_id)
    types = [type(e).__name__ for e in events]

    assert types[0]  == "WorkflowStarted"
    assert types[-1] == "WorkflowCompleted"

    # Every PromptAssembled must precede its corresponding ModelCalled
    for i, ev in enumerate(events):
        if isinstance(ev, ModelCalled):
            preceding = [type(e).__name__ for e in events[:i]]
            assert "PromptAssembled" in preceding

    # No conflicts expected (one writer per state path by design)
    assert "ConflictDetected" not in types

    summary = analyze_workflow(events)
    assert summary.total_model_calls >= 3
    assert summary.total_patches >= 5


@pytest.mark.asyncio
async def test_agent_turns_grouped_correctly(store, fake_client_factory):
    client = fake_client_factory([
        {"sql": "SELECT 1", "confidence": 0.9, "assumptions": []},
        {"explanation": "Selects one.", "table_references": []},
        {"risk_score": 0.05, "risk_reasons": [], "validation_ok": True, "validation_notes": "Safe."},
    ])
    import app.graphs as g
    orig = g.build_analysis_graph
    g.build_analysis_graph = lambda s, c=None: orig(s, client=client)
    try:
        state, _ = await run_workflow(mode="nl_to_sql", nl_input="Test", store=store)
    finally:
        g.build_analysis_graph = orig

    events = await store.get_workflow(state.workflow_id)
    turns = get_agent_turns(events)
    agent_ids = {t.agent_id for t in turns}
    assert "nl_to_sql" in agent_ids
    assert "explainer" in agent_ids
    assert "risk_validator" in agent_ids
```

---

## `tests/test_local_model_retry.py`

```python
"""Verify retry-with-correction loop fires correctly on bad JSON."""
import pytest
from agentstatelib import ValidationFailed, RetryAttempted
from app.agents.base import call_model_with_events
from agentstatelib import InMemoryStore


@pytest.mark.asyncio
async def test_retry_on_bad_json(store, fake_client_factory):
    client = fake_client_factory([
        "not json at all",
        "```json\nstill broken\n```",
        '{"sql": "SELECT 1", "confidence": 0.9, "assumptions": []}',
    ])

    result = await call_model_with_events(
        store=store,
        workflow_id="test-wf",
        agent_id="nl_to_sql",
        client=client,
        model="test-model",
        system_prompt="You are a test agent.",
        user_message="Test prompt.",
        max_retries=3,
    )

    assert result["sql"] == "SELECT 1"

    events = await store.get_workflow("test-wf")
    types = [type(e).__name__ for e in events]
    assert types.count("ValidationFailed") == 2
    assert types.count("RetryAttempted") == 2
    assert types.count("ModelCalled") == 3
    assert types.count("ModelReturned") == 3


@pytest.mark.asyncio
async def test_max_retries_raises(store, fake_client_factory):
    client = fake_client_factory(["not json"] * 3)

    with pytest.raises(RuntimeError, match="max retries"):
        await call_model_with_events(
            store=store,
            workflow_id="test-wf-2",
            agent_id="nl_to_sql",
            client=client,
            model="test-model",
            system_prompt="You are a test agent.",
            user_message="Test prompt.",
            max_retries=3,
        )
```

---

## Build Order

### Day 1 — Model backend first
1. Create repo, `pyproject.toml`, `.env.example`, `.gitignore`
2. Run Ollama (local or Colab notebook)
3. Write `app/agents/base.py` — `call_model_with_events`
4. **Smoke test the connection**: a 10-line script that calls `call_model_with_events` directly with a hello-world prompt. Nothing else works until this passes.

### Day 2 — Core agents
5. `app/state.py`
6. `app/prompts/*.txt` — all four prompts
7. `app/agents/schema_parser.py` (no LLM)
8. `app/agents/nl_to_sql.py`
9. `app/agents/explainer.py`
10. `app/agents/risk_validator.py`
11. `app/agents/rewrite.py`
12. `app/agents/finalizer.py` (no LLM)

### Day 3 — Graph and workflow
13. `app/graphs.py` — wire both graphs
14. `app/workflow.py` — two-phase orchestration
15. Run `tests/test_e2e_nl_to_sql.py` (mocked) — graph wiring verified
16. Run `tests/test_approval_flow.py` (mocked)

### Day 4 — Terminal dashboard
17. `app/cli.py`
18. **End-to-end terminal test with real model**: `python main.py chat`
    - Verify live Rich dashboard renders
    - Verify approval prompt appears for risky SQL

### Day 5 — API + server
19. `app/api/routes.py`
20. `app/api/server.py`
21. `main.py`
22. `curl -X POST http://localhost:8000/api/run -H 'x-api-key: dev-key-change-me' -H 'Content-Type: application/json' -d '{"mode":"nl_to_sql","nl_input":"Show me all users"}'`

### Day 6 — Frontend
23. Scaffold: `cd frontend && npm install`
24. `npm run dev` — Vite dev server at http://localhost:5173 (proxies `/api` and `/v1` to FastAPI)
25. Write `src/types.ts`, `src/api.ts`, then the five components and two pages
26. Browser end-to-end: submit query → watch SSE trace in TracePanel → see result in ResultBox
27. `npm run build` — outputs to `frontend/dist/`; restart FastAPI and verify `/ui/` serves the app

### Day 7 — Polish and tests
28. `tests/test_trace_events.py`
29. `tests/test_local_model_retry.py`
30. Verify library's `/dashboard` page loads and shows the workflow
31. `notebooks/colab_ollama_backend.ipynb`

---

## Running SQLiq

```bash
# 1. Clone and install Python dependencies
git clone https://github.com/you/sqliq && cd sqliq
uv sync   # or: pip install -e ".[dev]"

# 2. Copy and fill in env
cp .env.example .env
# Edit .env: set SQLIQ_API_BASE, SQLIQ_API_KEY, SQLIQ_MODEL

# 3a. Terminal mode (Rich dashboard — no frontend needed)
python main.py chat

# 3b. Dev mode — two terminals
#   Terminal 1: FastAPI backend
python main.py server

#   Terminal 2: Vite dev server with HMR
cd frontend
npm install       # first time only
npm run dev
# Open http://localhost:5173/          ← Vite (proxies /api and /v1 to FastAPI)
# Open http://localhost:8000/dashboard ← library's agent trace dashboard

# 3c. Production build (frontend bundled, FastAPI serves everything)
cd frontend && npm run build
python main.py server
# Open http://localhost:8000/ui/       ← FastAPI serves frontend/dist/
# Open http://localhost:8000/dashboard ← library's agent trace dashboard
```

---

## What Each Dashboard Shows

### Terminal dashboard (`python main.py chat`)
The library's `WorkflowDashboard` renders a live Rich table showing:
- One row per agent turn: agent ID, attempt count, duration, success/fail badge
- Expanded details for the most recent turn: context paths, prompt preview, model name, latency, any validation failures
- Header: workflow goal, status, elapsed time, token count, retry count, conflict count
- Approval gate: Rich Panel with side-by-side SQL diff + `[a/r/m]` prompt

### Web dashboard (`http://localhost:8000/dashboard`)
The library's built-in dashboard. Shows:
- List of all workflows run against this SQLite file
- Per-workflow event timeline (all 16 event types, raw payloads)
- Per-agent stats from `analyze_workflow()`: tokens, latency, validation failures
- This is the **observability proof point** — zero extra code required

### Custom web UI (`http://localhost:8000/ui/`)
- Home: two-card mode selector + input forms
- Workflow page: SSE live trace (right column) + result/approval UI (left column)
- Links to the library's `/dashboard` for deep inspection

---

*SQLiq is a five-agent, event-sourced SQL intelligence web app that converts natural language to SQL and back, pauses for human approval on risky rewrites, and streams every model call and state change to both a Rich terminal and a browser — proving `agentstatelib` as a real multi-agent orchestration backbone.*