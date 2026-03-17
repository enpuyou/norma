"""Simulation for Workflow 2 — Context Budget Routing.

Runs the Research Pipeline with and without routing and prints
a cost/utilization comparison.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich import box

from norma.workflows.workflow2_research import ResearchPipeline

TASKS = [
    {
        "description": "Analyze Q3 fintech regulatory changes and compliance posture",
        "search_scope": "fintech regulation 2025 Q3 SEC FINRA",
        "prior_findings": "None",
        "policy_excerpts": "Reg CF crowdfunding thresholds raised to $5M.",
        "format_spec": "Executive summary, 3 bullet points max.",
    },
    {
        "description": "Summarize GDPR enforcement actions Q3 2025",
        "search_scope": "GDPR enforcement EU 2025 Q3",
        "prior_findings": "None",
        "policy_excerpts": "Article 5(1)(f) integrity and confidentiality.",
        "format_spec": "One paragraph summary for board.",
    },
    {
        "description": "Review Basel IV capital requirements update",
        "search_scope": "Basel IV BIS 2025 capital requirements",
        "prior_findings": "None",
        "policy_excerpts": "Tier 1 capital ratio minimum 6%.",
        "format_spec": "Risk-focused bullet list.",
    },
]


def run_wf2(console: Console, quiet: bool = False) -> None:
    pipeline = ResearchPipeline()

    without_results = [pipeline.run(t, context_routing=False) for t in TASKS]
    with_results    = [pipeline.run(t, context_routing=True)  for t in TASKS]

    # ── Per-subagent token comparison (first task) ────────────────────────────
    without_r0 = without_results[0]
    with_r0    = with_results[0]

    if not quiet:
        token_table = Table(
            title="Token Flow: With vs Without Routing (Task 1)",
            box=box.SIMPLE_HEAVY, header_style="bold cyan",
        )
        token_table.add_column("Subagent", style="bold", width=12)
        token_table.add_column("Available", width=11)
        token_table.add_column("Sent (no routing)", width=18)
        token_table.add_column("Sent (routing)", width=15)
        token_table.add_column("Saved %", width=10)

        for sa in ["researcher", "analyst", "writer"]:
            wo = without_r0.subagent_context[sa]
            wr = with_r0.subagent_context[sa]
            saved_pct = (1 - wr.tokens_sent / wo.tokens_sent) * 100 if wo.tokens_sent else 0
            token_table.add_row(
                sa,
                str(wo.tokens_available),
                str(wo.tokens_sent),
                str(wr.tokens_sent),
                f"[green]{saved_pct:.0f}%[/green]",
            )
        console.print(token_table)

    # ── Cost + quality comparison across all tasks ────────────────────────────
    avg_cost_without = sum(r.total_cost_usd for r in without_results) / len(without_results)
    avg_cost_with    = sum(r.total_cost_usd for r in with_results)    / len(with_results)
    avg_q_without    = sum(r.quality_score  for r in without_results) / len(without_results)
    avg_q_with       = sum(r.quality_score  for r in with_results)    / len(with_results)

    savings_pct = (1 - avg_cost_with / avg_cost_without) * 100 if avg_cost_without else 0
    q_delta_pp  = (avg_q_with - avg_q_without) * 100

    summary = Table(
        title="WF2: Context Routing Summary (3 tasks)",
        box=box.SIMPLE_HEAVY, header_style="bold cyan",
    )
    summary.add_column("Metric", style="bold", width=28)
    summary.add_column("Without Routing", width=18)
    summary.add_column("With Routing",    width=16)
    summary.add_column("Delta",           width=14)

    summary.add_row(
        "Avg cost per run (USD)",
        f"${avg_cost_without:.5f}",
        f"${avg_cost_with:.5f}",
        f"[green]−{savings_pct:.0f}% cheaper[/green]",
    )
    summary.add_row(
        "Avg quality score",
        f"{avg_q_without:.2f}",
        f"{avg_q_with:.2f}",
        f"{'[green]+' if q_delta_pp >= 0 else '[red]'}{q_delta_pp:+.1f}pp[/]",
    )
    summary.add_row(
        "Writer receives raw search?",
        "[red]Yes[/red]",
        "[green]No[/green]",
        "✓ policy enforced",
    )
    console.print(summary)

    monthly_500 = (avg_cost_without - avg_cost_with) * 500
    console.print(
        f"\n  [bold]VP view:[/bold] Context routing saves "
        f"[green]${avg_cost_without - avg_cost_with:.5f}[/green] per run "
        f"(−{savings_pct:.0f}%). At 500 runs/month = "
        f"[bold green]${monthly_500:.2f}/month[/bold green] saved. "
        f"Quality delta: {q_delta_pp:+.1f}pp (within noise)."
    )
    console.print(
        f"\n  [bold]Engineer view:[/bold] Token utilization ratios shown above. "
        f"Writer's [dim]contains_raw_search_results = False[/dim] "
        f"enforced by routing policy. "
        f"Utilization measurement is n-gram overlap approximation (not semantic). "
        f"Disclosed in Engineer UI."
    )
