"""
norma-demo — runs all three workflows using the live system with zero LLM calls.

The core capabilities (trust engine, enforcement, attribution, context routing)
are all deterministic Python. This runner drives them with realistic simulated
run data and prints a rich terminal walkthrough.

Run:
    poetry run norma-demo
    poetry run norma-demo --workflow 1   # single workflow
    poetry run norma-demo --quiet        # only final results
"""

from __future__ import annotations

import time
from typing import Callable

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

from norma.sim.workflow1_sim import run_wf1
from norma.sim.workflow2_sim import run_wf2
from norma.sim.workflow3_sim import run_wf3

console = Console()

WORKFLOWS: dict[int, tuple[str, Callable]] = {
    1: ("Dynamic Authority Calibration — Financial Report Agent", run_wf1),
    2: ("Context Budget Routing — Research Pipeline",             run_wf2),
    3: ("Failure Attribution — Customer Support Triage",          run_wf3),
}


def _header(wf_num: int, title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]Workflow {wf_num}: {title}[/bold cyan]")
    console.print()


def _separator() -> None:
    console.print()
    console.rule("[dim]─[/dim]")
    console.print()


@click.command()
@click.option("--workflow", "-w", type=int, default=None,
              help="Run a single workflow (1, 2, or 3). Default: all.")
@click.option("--quiet", "-q", is_flag=True, default=False,
              help="Suppress step-by-step output; show only final results.")
def main(workflow: int | None, quiet: bool) -> None:
    """Run norma.ai demo workflows — zero LLM calls, live system output."""
    console.print(Panel.fit(
        "[bold white]norma.ai demo runner[/bold white]\n"
        "[dim]No API calls · Live system · Deterministic outputs[/dim]",
        border_style="cyan",
    ))

    targets = [workflow] if workflow else [1, 2, 3]
    for wf in targets:
        if wf not in WORKFLOWS:
            console.print(f"[red]Unknown workflow: {wf}. Choose 1, 2 or 3.[/red]")
            continue
        title, fn = WORKFLOWS[wf]
        _header(wf, title)
        fn(console, quiet=quiet)
        if wf != targets[-1]:
            _separator()

    console.print()
    console.print("[bold green]✓ All workflows complete.[/bold green] "
                  "Run [cyan]poetry run pytest tests/[/cyan] to verify all asserts pass.")


if __name__ == "__main__":
    main()
