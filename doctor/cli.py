import typer
from rich.console import Console
from pathlib import Path

from doctor.discovery import load_plugins_from_file
from doctor.sdk.scaffold import scaffold_plugin
from doctor.sdk.testing import PluginTestHarness

from doctor.baseline import diff_reports, load_baseline, save_baseline
from doctor.config import load_config
from doctor.formatters.html_formatter import render_html
from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Report
from doctor.registry import discover_all_plugins
from doctor.report import render_diff, render_report, render_trends
from doctor.scoring import compute_health_score, has_critical_failures
from doctor.snapshot import find_closest_snapshot, load_snapshots, parse_time_spec, save_snapshot
from doctor.trend import MIN_SNAPSHOTS_FOR_TREND, compute_trends

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
baseline_app = typer.Typer(help="Capture and compare baseline system snapshots (§16).")
app.add_typer(baseline_app, name="baseline")
plugin_app = typer.Typer(help="Scaffold, and validate Developer Doctor plugins (§22).")
app.add_typer(plugin_app, name="plugin")

console = Console()


def _generate_report() -> tuple[Report, list[str]]:
    config = load_config()
    plugins, discovery_errors = discover_all_plugins(config)
    results = [plugin.run() for plugin in plugins]
    score = compute_health_score(results)
    return Report(score=score, results=results), discovery_errors


def _print_discovery_warnings(errors: list[str]) -> None:
    for error in errors:
        console.print(f"[yellow]Warning:[/yellow] {error}")


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
        _print_discovery_warnings(discovery_errors)

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
    _print_discovery_warnings(discovery_errors)
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
    _print_discovery_warnings(discovery_errors)

    diffs = diff_reports(baseline, current)
    render_diff(
        f"Baseline Comparison (captured {baseline.generated_at.date().isoformat()})",
        diffs,
        baseline.score,
        current.score,
        console,
    )


@app.command("snapshot")
def snapshot_cmd() -> None:
    """Capture the current system state as a new historical snapshot (§17)."""
    report, discovery_errors = _generate_report()
    _print_discovery_warnings(discovery_errors)

    save_snapshot(report)
    total = len(load_snapshots())
    console.print(
        f"[green]Snapshot captured.[/green] Health score: {report.score} / 100 "
        f"({total} snapshot{'s' if total != 1 else ''} stored)"
    )


@app.command("diff")
def diff_cmd(
    target: str = typer.Argument(
        "yesterday",
        help='Time to diff against: "yesterday", "today", "Nd" (N days ago), or an ISO date.',
    ),
) -> None:
    """Compare current system state against a historical snapshot."""
    target_time = parse_time_spec(target)
    if target_time is None:
        console.print(
            f"[bold red]Error:[/bold red] Could not parse '{target}'. "
            f'Try "yesterday", "7d", or an ISO date like "2026-06-25".'
        )
        raise typer.Exit(code=1)

    snapshots = load_snapshots()
    closest = find_closest_snapshot(target_time, snapshots)
    if closest is None:
        console.print(
            "[bold red]Error:[/bold red] No snapshots found. "
            "Run `doctor snapshot` first, ideally on a regular schedule."
        )
        raise typer.Exit(code=1)

    current, discovery_errors = _generate_report()
    _print_discovery_warnings(discovery_errors)

    diffs = diff_reports(closest.report, current)
    render_diff(
        f"Diff vs {closest.captured_at.date().isoformat()} "
        f"({closest.captured_at.strftime('%H:%M UTC')})",
        diffs,
        closest.report.score,
        current.score,
        console,
    )


@app.command("trend")
def trend_cmd() -> None:
    """Analyze trends across all historical snapshots (§17)."""
    snapshots = load_snapshots()
    if len(snapshots) < MIN_SNAPSHOTS_FOR_TREND:
        console.print(
            f"[yellow]Not enough snapshots for trend analysis "
            f"({len(snapshots)}/{MIN_SNAPSHOTS_FOR_TREND} minimum).[/yellow] "
            f"Run `doctor snapshot` a few more times, ideally spread over several days."
        )
        raise typer.Exit(code=1)

    trends = compute_trends(snapshots)
    render_trends(trends, len(snapshots), console)

@plugin_app.command("create")
def plugin_create(
    name: str = typer.Argument(
        ..., help="Plugin name, lowercase, e.g. 'postgres' or 'my-cool-thing'."
    ),
) -> None:
    """Scaffold a new third-party plugin package."""
    try:
        path = scaffold_plugin(name)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1) from e

    console.print(f"[green]Created plugin scaffold at[/green] {path}")
    console.print(f"\nNext steps:\n  cd {path.name}\n  uv pip install -e .\n  pytest")


@plugin_app.command("validate")
def plugin_validate(
    path: Path = typer.Argument(..., help="Path to a plugin .py file to validate."),
) -> None:
    """Load a plugin file and sanity-check it before publishing."""
    if not path.is_file():
        console.print(f"[bold red]Error:[/bold red] '{path}' is not a file.")
        raise typer.Exit(code=1)

    plugins, load_errors = load_plugins_from_file(path)
    for error in load_errors:
        console.print(f"[bold red]Error:[/bold red] {error}")

    if not plugins and not load_errors:
        console.print(f"[yellow]Warning:[/yellow] No DoctorPlugin subclasses found in '{path}'.")

    harness = PluginTestHarness()
    any_failed = bool(load_errors)

    for plugin in plugins:
        console.print(f"\n[bold]{plugin.name}[/bold] ({type(plugin).__name__})")
        console.print(f"  description: {plugin.description}")
        console.print(f"  capabilities: {[c.value for c in plugin.capabilities] or 'none'}")

        try:
            supported = harness.check_is_supported(plugin)
            console.print(f"  is_supported(): {supported}")
            if supported:
                result = harness.run(plugin)
                console.print(
                    f"  run() → status={result.status.value}, {len(result.findings)} finding(s)"
                )
        except Exception as e:
            console.print(f"  [bold red]run() raised an exception:[/bold red] {e}")
            console.print(
                "  [dim]Plugins must never raise from run()/is_supported() — "
                "catch exceptions internally and return a FAIL PluginResult instead.[/dim]"
            )
            any_failed = True

    if any_failed or (not plugins and not load_errors):
        raise typer.Exit(code=1)

    console.print("\n[green]Validation passed.[/green]")

if __name__ == "__main__":
    app()