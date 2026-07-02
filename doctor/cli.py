import typer
from rich.console import Console

from doctor.baseline import diff_reports, load_baseline, save_baseline
from doctor.config import load_config
from doctor.formatters.html_formatter import render_html
from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Report
from doctor.registry import discover_all_plugins
from doctor.report import render_baseline_diff, render_report
from doctor.scoring import compute_health_score, has_critical_failures

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
baseline_app = typer.Typer(help="Capture and compare baseline system snapshots (§16).")
app.add_typer(baseline_app, name="baseline")

console = Console()


def _generate_report() -> tuple[Report, list[str]]:
    config = load_config()
    plugins, discovery_errors = discover_all_plugins(config)
    results = [plugin.run() for plugin in plugins]
    score = compute_health_score(results)
    return Report(score=score, results=results), discovery_errors


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output a machine-readable JSON report."),
    yaml_output: bool = typer.Option(False, "--yaml", help="Output a machine-readable YAML report."),
    html_output: bool = typer.Option(False, "--html", help="Output a self-contained HTML report."),
    ci: bool = typer.Option(
        False,
        "--ci",
        help="CI mode: exit with a non-zero status code if any plugin reports a critical (FAIL) issue.",
    ),
) -> None:
    """Run all diagnostics and print a health report."""
    if ctx.invoked_subcommand is not None:
        return

    selected_formats = [f for f in (json_output, yaml_output, html_output) if f]
    if len(selected_formats) > 1:
        console.print("[bold red]Error:[/bold red] --json, --yaml, and --html are mutually exclusive.")
        raise typer.Exit(code=1)

    report, discovery_errors = _generate_report()

    machine_readable = json_output or yaml_output or html_output
    if discovery_errors and not machine_readable:
        for error in discovery_errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

    if json_output:
        print(render_json(report))
    elif yaml_output:
        print(render_yaml(report))
    elif html_output:
        print(render_html(report))
    else:
        render_report(report.results, report.score, console)

    if ci and has_critical_failures(report.results):
        if not machine_readable:
            console.print("[bold red]CI mode:[/bold red] critical issues detected, exiting non-zero.")
        raise typer.Exit(code=1)


@baseline_app.command("create")
def baseline_create() -> None:
    """Capture the current system state as the baseline snapshot."""
    report, discovery_errors = _generate_report()
    for error in discovery_errors:
        console.print(f"[yellow]Warning:[/yellow] {error}")

    save_baseline(report)
    console.print(f"[green]Baseline captured.[/green] Health score: {report.score} / 100")


@baseline_app.command("compare")
def baseline_compare() -> None:
    """Compare the current system state against the saved baseline."""
    baseline = load_baseline()
    if baseline is None:
        console.print(
            "[bold red]Error:[/bold red] No baseline found. Run `doctor baseline create` first."
        )
        raise typer.Exit(code=1)

    current, discovery_errors = _generate_report()
    for error in discovery_errors:
        console.print(f"[yellow]Warning:[/yellow] {error}")

    diffs = diff_reports(baseline, current)
    render_baseline_diff(diffs, baseline.score, current.score, baseline.generated_at, console)


if __name__ == "__main__":
    app()