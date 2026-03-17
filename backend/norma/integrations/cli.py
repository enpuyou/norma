"""
norma-import CLI — bulk-import existing agents into norma.ai.

Commands:
    norma-import registry norma-registry.yaml
    norma-import registry norma-registry.yaml --dry-run
    norma-import registry norma-registry.yaml --snippets      # print code snippets
    norma-import scan ./myapp/agents/                          # auto-discover
"""

from __future__ import annotations

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich import box

console = Console()


@click.group()
def norma_cmd() -> None:
    """norma command group."""
    pass


@norma_cmd.group("compliance")
def compliance_cmd() -> None:
    """Compliance commands."""
    pass


@compliance_cmd.command("check")
@click.option("--agent-id", required=True, help="Agent ID to evaluate.")
@click.option("--base-url", default="http://localhost:8080", show_default=True)
def compliance_check_cmd(agent_id: str, base_url: str) -> None:
    """Evaluate compliance posture and exit 0 (pass) or 1 (fail)."""
    url = f"{base_url.rstrip('/')}/api/compliance/{agent_id}/posture"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        console.print(f"[red]Compliance check failed to run:[/red] {exc}")
        raise SystemExit(1)

    passed = bool(data.get("passed"))
    summary = data.get("summary", {})
    total = summary.get("total_rules", 0)
    failed = summary.get("failed_rules", 0)

    if passed:
        console.print(
            f"[green]COMPLIANT[/green] agent={agent_id} rules={total} failed={failed}"
        )
        raise SystemExit(0)

    console.print(
        f"[red]NON-COMPLIANT[/red] agent={agent_id} rules={total} failed={failed}"
    )
    findings = data.get("findings", [])
    for f in findings:
        if not f.get("passed"):
            console.print(
                f"  - [red]{f.get('rule_id')}[/red] {f.get('message')}"
            )
    raise SystemExit(1)


@click.group()
def import_cmd() -> None:
    """Import existing agents into norma.ai."""
    pass


@import_cmd.command("registry")
@click.argument("registry_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, default=False,
              help="Parse and preview without writing to DB.")
@click.option("--snippets", is_flag=True, default=False,
              help="Print the two-line code snippet for each agent.")
def registry_cmd(registry_file: str, dry_run: bool, snippets: bool) -> None:
    """Import agents from a YAML registry file."""
    from norma.integrations.importer import NormaImporter

    console.print(Panel.fit(
        f"[bold white]norma-import[/bold white] — importing from [cyan]{registry_file}[/cyan]"
        + (" [yellow](dry-run)[/yellow]" if dry_run else ""),
        border_style="cyan",
    ))

    importer = NormaImporter()
    agents  = importer.load_registry(registry_file)
    results = importer.import_agents(agents, dry_run=dry_run)

    _print_import_results(results, snippets=snippets, dry_run=dry_run)


@import_cmd.command("scan")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, default=True,
              help="Default True for scan: preview discovered agents without writing to DB.")
@click.option("--snippets", is_flag=True, default=True)
def scan_cmd(directory: str, dry_run: bool, snippets: bool) -> None:
    """Auto-discover LangGraph graphs in a directory and import them."""
    from norma.integrations.importer import NormaImporter

    console.print(Panel.fit(
        f"[bold white]norma-import scan[/bold white] — scanning [cyan]{directory}[/cyan]"
        + (" [yellow](dry-run)[/yellow]" if dry_run else ""),
        border_style="cyan",
    ))

    importer = NormaImporter()
    agents = importer.scan_directory(directory)

    if not agents:
        console.print("[yellow]No LangGraph graphs found in the directory.[/yellow]")
        console.print("[dim]Tip: make sure the modules are importable (in PYTHONPATH).[/dim]")
        return

    console.print(f"[green]Found {len(agents)} agent(s).[/green]\n")
    results = importer.import_agents(agents, dry_run=dry_run)
    _print_import_results(results, snippets=snippets, dry_run=dry_run)


def _print_import_results(
    results: list[dict],
    *,
    snippets: bool,
    dry_run: bool,
) -> None:
    """Print a summary table + optional code snippets for all imported agents."""
    t = Table(
        title=f"Imported Agents {'(dry-run)' if dry_run else ''}",
        box=box.SIMPLE_HEAVY, header_style="bold cyan",
    )
    t.add_column("Agent ID",   style="bold", width=30)
    t.add_column("Type",       width=12)
    t.add_column("Owner",      width=22)
    t.add_column("Contract",   width=12)
    t.add_column("Enforcement", width=24)
    t.add_column("Status",     width=14)

    for r in results:
        t.add_row(
            r["id"],
            r["type"],
            r["owner"],
            "[green]✓ generated[/green]" if r["contract_generated"] else "[red]✗[/red]",
            "[yellow]DISABLED[/yellow] (pending approval)",
            "[dim]dry-run[/dim]" if dry_run else "[green]imported[/green]",
        )

    console.print(t)

    console.print(
        f"\n  [bold]Next steps:[/bold]\n"
        f"  1. Review the generated contract proposals in [cyan]norma dashboard → Contracts[/cyan]\n"
        f"  2. Approve each contract before enforcement activates\n"
        f"  3. Add the [cyan]track()[/cyan] call to your agent files (see --snippets)\n"
    )

    if snippets:
        for r in results:
            console.print(Panel(
                Syntax(r["snippet"], "python", theme="monokai", line_numbers=False),
                title=f"[bold]{r['id']}[/bold]",
                border_style="dim",
            ))

    # Print contract previews
    console.print("\n[dim]Contract proposals (review before approving):[/dim]\n")
    for r in results:
        console.print(Panel(
            Syntax(r["contract_yaml"], "yaml", theme="monokai", line_numbers=False),
            title=f"[bold]{r['id']}[/bold] — contract v1.0 (UNAPPROVED)",
            border_style="yellow",
        ))
