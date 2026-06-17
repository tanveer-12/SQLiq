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
    console.print("  [bold]1[/bold]  NL → SQL        Ask a question, get a SQL query")
    console.print("  [bold]2[/bold]  SQL → English   Paste a query, get a plain-English explanation")
    console.print()
    mode_choice = Prompt.ask(
        "  Select mode",
        choices=["1", "2"],
        default="1",
    )

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
        console.print("  [bold]a[/bold]  Approve rewrite   Accept the safer version")
        console.print("  [bold]r[/bold]  Reject            Keep the original SQL as-is")
        console.print("  [bold]m[/bold]  Modify            Edit the SQL yourself")
        console.print()
        decision_choice = Prompt.ask(
            "  Decision",
            choices=["a", "r", "m"],
            default="a",
        )
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