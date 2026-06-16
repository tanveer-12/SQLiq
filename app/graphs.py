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