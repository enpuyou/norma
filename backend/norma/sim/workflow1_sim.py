"""Simulation for Workflow 1 — Dynamic Authority Calibration.

Drives the FinancialReportAgent step-by-step and prints a live narrative:
 • Trust score progression per run
 • Tier proposal after 10 clean runs (pending human approval)
 • Contract expansion after approval
 • Violation on run 23 → automatic demotion
 • Audit log summary
"""

from __future__ import annotations

import time

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

from norma.workflows.workflow1_financial import FinancialReportAgent


def run_wf1(console: Console, quiet: bool = False) -> None:
    agent = FinancialReportAgent()
    rows: list[tuple] = []

    def _step(msg: str) -> None:
        if not quiet:
            console.print(f"  [dim]{msg}[/dim]")

    # ── Phase 1: Runs 1–10 (earn standard tier) ──────────────────────────────
    _step("Starting in Restricted Tier (initial trust score: 0.40)")
    for i in range(1, 11):
        agent.run_clean()
        rows.append((str(i), f"{agent.trust_score:.3f}", agent.current_tier,
                     "clean", "-"))

    # Tier upgrade proposed
    proposal = agent.pending_contract_version
    if not quiet:
        console.print(f"\n  [yellow]⚡ Tier upgrade proposed after run 10: "
                      f"[bold]{proposal}[/bold] (awaiting human approval)[/yellow]")
        console.print(f"  [dim]Tier is still [bold]restricted[/bold] until a human approves.[/dim]")

    # Human approves → tier becomes standard
    agent.approve_pending_contract(approver="demo-approver")
    if not quiet:
        console.print(f"  [green]✓ Contract approved by demo-approver. "
                      f"Tier → [bold]standard[/bold][/green]")
        console.print(f"  [dim]reports/internal/** now accessible[/dim]")

    # ── Phase 2: Runs 11–22 (continue clean) ─────────────────────────────────
    for i in range(11, 23):
        agent.run_clean()
        rows.append((str(i), f"{agent.trust_score:.3f}", agent.current_tier,
                     "clean", "-"))

    # ── Phase 3: Run 23 — violation ──────────────────────────────────────────
    score_before = agent.trust_score
    tier_before  = agent.current_tier
    result = agent.inject_violation(resource="reports/confidential/exec-comp.pdf")
    rows.append(("23", f"{agent.trust_score:.3f}", agent.current_tier,
                 "[red]VIOLATION[/red]",
                 "[red]BLOCKED[/red]"))

    if not quiet:
        console.print(
            f"\n  [bold red]🚨 Run 23 — policy violation[/bold red]\n"
            f"  Attempted: [bold]GET reports/confidential/exec-comp.pdf[/bold]\n"
            f"  Rule triggered: {result.policy_rule}\n"
            f"  Trust: {score_before:.3f} → {agent.trust_score:.3f} "
            f"(−{score_before - agent.trust_score:.3f})\n"
            f"  Tier: {tier_before} → [bold red]{agent.current_tier}[/bold red] (auto-reverted)\n"
            f"  Internal access revoked. No human intervention required."
        )

    # ── Summary table ─────────────────────────────────────────────────────────
    t = Table(title="WF1: Trust Score Progression", box=box.SIMPLE_HEAVY,
              show_header=True, header_style="bold cyan")
    t.add_column("Run", style="dim", width=4)
    t.add_column("Trust Score", width=12)
    t.add_column("Tier", width=12)
    t.add_column("Status", width=14)
    t.add_column("Action", width=10)

    for run_n, score, tier, status, action in rows:
        # Highlight tier change boundary
        style = ""
        if "VIOLATION" in status:
            style = "red"
        elif tier == "standard" and int(run_n) == 11:
            style = "green"
        t.add_row(run_n, score, tier, status, action, style=style)

    console.print(t)

    # ── VP summary ────────────────────────────────────────────────────────────
    audit = agent.get_audit_log()
    revocations = [e for e in audit if e["event_type"] == "tier_revocation"]
    console.print(
        "\n  [bold]VP view:[/bold] Financial Report Agent earned expanded access after "
        "10 clean runs. It attempted to access confidential files on run 23. "
        "Access was automatically restricted. No customer data was exposed. "
        "No human intervention was required.\n"
    )
    console.print(
        f"  [bold]Engineer view:[/bold] {len(audit)} audit events. "
        f"{len(revocations)} tier revocation(s). "
        f"Final tier: [bold]{agent.current_tier}[/bold]. "
        f"Final trust score: [bold]{agent.trust_score:.3f}[/bold]."
    )
