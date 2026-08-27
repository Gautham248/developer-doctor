from pathlib import Path

import typer
from rich.console import Console

from doctor.baseline import diff_reports, load_baseline, save_baseline
from doctor.config import load_config
from doctor.discovery import load_plugins_from_file
from doctor.formatters.html_formatter import render_html
from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Report, CleanupReport
from doctor.registry import discover_all_plugins
from concurrent.futures import ThreadPoolExecutor
from doctor.cleanup import ALL_SCANNERS
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService
from doctor.cleanup_render import render_cleanup_scan, render_cleanup_summary, format_bytes
from doctor.report import render_diff, render_report, render_trends
from doctor.scoring import compute_health_score, has_critical_failures
from doctor.sdk.lint import lint_plugin
from doctor.sdk.package import package_plugin
from doctor.sdk.publish import check_package, upload_package
from doctor.sdk.scaffold import scaffold_plugin
from doctor.sdk.testing import PluginTestHarness
from doctor.snapshot import find_closest_snapshot, load_snapshots, parse_time_spec, save_snapshot
from doctor.trend import MIN_SNAPSHOTS_FOR_TREND, compute_trends

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
baseline_app = typer.Typer(help="Capture and compare baseline system snapshots (§16).")
plugin_app = typer.Typer(help="Scaffold, validate, lint, package, and publish Developer Doctor plugins (§22).")
app.add_typer(baseline_app, name="baseline")
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


@plugin_app.command("lint")
def plugin_lint(
    path: Path = typer.Argument(..., help="Path to a plugin file or project directory to lint."),
) -> None:
    """Run ruff and mypy against a plugin (each tool is skipped, not
    failed, if it isn't installed)."""
    result = lint_plugin(path)
    for tool_result in result.results:
        status = "skipped" if not tool_result.ran else ("passed" if tool_result.passed else "FAILED")
        console.print(f"\n[bold]{tool_result.tool}[/bold]: {status}")
        if tool_result.output:
            console.print(tool_result.output)

    if not result.passed:
        console.print("\n[bold red]Lint failed.[/bold red]")
        raise typer.Exit(code=1)
    console.print("\n[green]Lint passed.[/green]")


@plugin_app.command("package")
def plugin_package(
    path: Path = typer.Argument(
        ..., help="Path to the plugin project directory (containing pyproject.toml)."
    ),
) -> None:
    """Build a plugin into a wheel + sdist via `uv build`."""
    result = package_plugin(path)
    if result.output:
        console.print(result.output)

    if not result.success:
        console.print("\n[bold red]Package build failed.[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"\n[green]Built {len(result.artifacts)} artifact(s):[/green]")
    for artifact in result.artifacts:
        console.print(f"  {artifact}")


@plugin_app.command("publish")
def plugin_publish(
    path: Path = typer.Argument(
        ..., help="Path to the plugin project directory (containing built dist/ artifacts)."
    ),
    repository: str = typer.Option(
        "testpypi",
        "--repository",
        help="twine repository to publish to. Defaults to testpypi — pass "
        "'--repository pypi' explicitly to publish to the real index.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the interactive confirmation prompt. The action is still explicit — "
        "you must pass this flag deliberately.",
    ),
) -> None:
    """Validate and publish a plugin package via twine.

    Always runs `twine check` first (local, no network). Actually
    uploading is a real, irreversible action against an external
    package index, so it never happens without an explicit
    confirmation — either an interactive 'yes' or the --yes flag.
    """
    check_result = check_package(path)
    if check_result.output:
        console.print(check_result.output)

    if not check_result.success:
        console.print("\n[bold red]Package validation (twine check) failed. Not publishing.[/bold red]")
        raise typer.Exit(code=1)

    console.print("[green]Package validation passed.[/green]")
    console.print(
        f"\nAbout to upload to repository '[bold]{repository}[/bold]'. "
        f"This is a real, irreversible action."
    )

    if not yes:
        confirmed = typer.confirm(f"Upload to '{repository}' now?")
        if not confirmed:
            console.print("Aborted. No upload performed.")
            raise typer.Exit(code=0)

    upload_result = upload_package(path, repository)
    if upload_result.output:
        console.print(upload_result.output)

    if not upload_result.success:
        console.print("\n[bold red]Upload failed.[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"\n[green]Published to '{repository}'.[/green]")


@app.command("cleanup")
def cleanup_cmd(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Clean all safe categories automatically without prompting.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Scan and report sizes only; do not delete anything.",
    ),
    categories: list[str] = typer.Option(
        None,
        "--category",
        "-c",
        help="Restrict to specific category name(s), e.g. -c docker -c xcode (can be repeated).",
    ),
    include_unsafe: bool = typer.Option(
        False,
        "--include-unsafe",
        help="Also clean categories marked unsafe to auto-clean (like local node_modules).",
    ),
) -> None:
    """Scan and clean up residual junk files from the system and build tools."""
    # 1. Initialize and run scanners
    supported_scanners = [s() for s in ALL_SCANNERS if s().is_supported()]
    
    if categories:
        cat_names = [c.lower().strip() for c in categories]
        supported_scanners = [s for s in supported_scanners if s.name in cat_names]
        if not supported_scanners:
            console.print(f"[yellow]No supported scanners match the categories: {categories}[/yellow]")
            raise typer.Exit(code=0)

    cleanup_service = CleanupService()
    scan_results = []

    console.print("[bold cyan]Scanning for junk files...[/bold cyan]")
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(s.scan, cleanup_service): s for s in supported_scanners}
        for fut in futures:
            s = futures[fut]
            try:
                res = fut.result()
                if res.size_bytes > 0:
                    scan_results.append(res)
            except Exception as e:
                console.print(f"[yellow]Warning: Scanner {s.name} failed to scan: {e}[/yellow]")

    scan_results.sort(key=lambda x: x.size_bytes, reverse=True)
    report = CleanupReport(
        categories=scan_results,
        total_size_bytes=sum(c.size_bytes for c in scan_results),
    )

    if not scan_results:
        console.print("\n[green]No cleanup required. Everything is clean![/green]")
        raise typer.Exit(code=0)

    render_cleanup_scan(report, console)

    if dry_run:
        console.print("[yellow]Dry-run mode active. No files were deleted.[/yellow]")
        raise typer.Exit(code=0)

    selected_categories = []
    
    if not yes:
        proceed = typer.confirm("Do you want to proceed with cleaning up?")
        if not proceed:
            console.print("Cleanup aborted. No files were deleted.")
            raise typer.Exit(code=0)

        # Interactive picker
        console.print("\n[bold]Select which categories you want to clean up:[/bold]")
        for idx, cat in enumerate(scan_results, 1):
            warning = " [bold yellow](WARNING: contains workspace files)[/bold yellow]" if not cat.is_safe_to_auto_clean else ""
            console.print(f"  [{idx}] {cat.label} ({format_bytes(cat.size_bytes)}){warning}")
        
        selection_input = typer.prompt(
            "\nEnter numbers (comma-separated, e.g. 1,3), 'all', or 'none'",
            default="all",
        )
        
        sel = selection_input.strip().lower()
        if sel == "all":
            selected_categories = list(scan_results)
        elif sel in ("none", ""):
            console.print("No categories selected. Exiting.")
            raise typer.Exit(code=0)
        else:
            try:
                indices = [int(i.strip()) for i in sel.split(",")]
                for idx in indices:
                    if 1 <= idx <= len(scan_results):
                        selected_categories.append(scan_results[idx - 1])
                    else:
                        console.print(f"[yellow]Warning: Invalid index {idx} ignored.[/yellow]")
            except ValueError:
                console.print("[bold red]Error: Invalid selection input format.[/bold red]")
                raise typer.Exit(code=1)
    else:
        for cat in scan_results:
            if cat.is_safe_to_auto_clean or include_unsafe:
                selected_categories.append(cat)
            else:
                console.print(
                    f"[yellow]Skipping category '{cat.name}' as it contains workspace files "
                    "and --include-unsafe was not set.[/yellow]"
                )

    to_clean = []
    for cat in selected_categories:
        if not cat.is_safe_to_auto_clean and not include_unsafe:
            confirm_unsafe = typer.confirm(
                f"Category '{cat.name}' is marked as unsafe to auto-clean (workspace files). Proceed anyway?",
                default=False,
            )
            if not confirm_unsafe:
                console.print(f"Skipping {cat.label}.")
                continue
        to_clean.append(cat)

    if not to_clean:
        console.print("No categories to clean. Exiting.")
        raise typer.Exit(code=0)

    clean_service = CleanService()
    total_freed = 0
    cleaned_names = []

    console.print("\n[bold cyan]Cleaning up...[/bold cyan]")
    scanner_map = {s.name: s for s in supported_scanners}
    
    for cat in to_clean:
        scanner = scanner_map.get(cat.name)
        if scanner:
            console.print(f"  Cleaning {cat.label}...", end="")
            try:
                freed = scanner.clean(clean_service, cat)
                total_freed += freed
                cleaned_names.append(cat.name)
                console.print(f" [green]Done (reclaimed {format_bytes(freed)})[/green]")
            except Exception as e:
                console.print(f" [red]Failed: {e}[/red]")

    render_cleanup_summary(total_freed, cleaned_names, console)


if __name__ == "__main__":
    app()