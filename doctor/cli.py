from pathlib import Path
from typing import Any

import psutil
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
from doctor.services.thermal_service import ThermalService, KillSafety
from doctor.services.thermal_optimizer import (
    ThermalOptimizer,
    OptimizationAction,
    OptimizationCategory,
)
from doctor.services.process_service import ProcessService
from doctor.services.memory_optimizer import MemoryOptimizer

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



# ---------------------------------------------------------------------------
# `doctor thermal` command
# ---------------------------------------------------------------------------

@app.command("thermal")
def thermal_cmd(
    watch: bool = typer.Option(False, "--watch", "-w", help="Refresh every N seconds (Ctrl+C to quit)."),
    interval: int = typer.Option(3, "--interval", help="Refresh interval in seconds (watch mode)."),
    top: int = typer.Option(10, "--top", help="Number of top processes to display."),
    threshold: float = typer.Option(1.0, "--threshold", help="Min CPU % to include a process."),
    kill: bool = typer.Option(False, "--kill", help="Interactive per-process kill mode."),
    optimize: bool = typer.Option(False, "--optimize", help="Scan and propose optimization plan."),
    auto_optimize: bool = typer.Option(False, "--auto-optimize", help="Silently apply all SAFE optimizations."),
) -> None:
    """Show thermal pressure, power draw, and heat-generating processes.

    Use --optimize to get an actionable plan to reduce CPU heat.
    Use --kill to manually terminate specific processes.
    """
    import time as _time

    service = ThermalService()
    optimizer = ThermalOptimizer()

    def _run_once() -> None:
        state = service.get_thermal_state()
        processes = service.get_thermal_processes(limit=top, min_cpu_percent=threshold)

        _render_thermal_header(state, console)
        _render_process_table(processes, console)

        if optimize or auto_optimize:
            _run_optimize_flow(
                processes, optimizer, console, auto_mode=auto_optimize
            )
        elif kill:
            _run_kill_flow(processes, console)

    if watch:
        try:
            while True:
                console.clear()
                _run_once()
                console.print(
                    f"\n[dim]Refreshing every {interval}s — Ctrl+C to quit[/dim]"
                )
                _time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
    else:
        _run_once()


# ---------------------------------------------------------------------------
# Thermal rendering helpers
# ---------------------------------------------------------------------------

_LEVEL_STYLES = {
    "nominal":  ("green",  "NOMINAL"),
    "fair":     ("yellow", "FAIR"),
    "serious":  ("red",    "SERIOUS ⚠"),
    "critical": ("bold red", "CRITICAL 🔥"),
    "unknown":  ("dim",    "UNKNOWN"),
}

_SAFETY_DISPLAY = {
    KillSafety.SAFE:    ("[green]✓ SAFE[/green]",    "green"),
    KillSafety.CAUTION: ("[yellow]⚠ CAUTION[/yellow]", "yellow"),
    KillSafety.UNSAFE:  ("[red]✗ UNSAFE[/red]",      "red"),
}


def _render_thermal_header(state: "ThermalState", console: Console) -> None:  # type: ignore[name-defined]
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from doctor.services.thermal_service import ThermalState  # noqa: F401

    level = state.level
    style, label = _LEVEL_STYLES.get(level, ("dim", level.upper()))

    lines = Text()
    lines.append("🌡  Thermal Pressure:  ", style="bold")
    lines.append(label + "\n", style=style)

    if state.temperature_c is not None:
        lines.append(f"   Temperature:        {state.temperature_c:.1f} °C\n")
    else:
        lines.append("   Temperature:        N/A  (Apple Silicon — no raw °C)\n", style="dim")

    if state.cpu_power_mw is not None:
        lines.append(f"   CPU Power:          {state.cpu_power_mw:,.0f} mW\n")
    if state.gpu_power_mw is not None:
        lines.append(f"   GPU Power:          {state.gpu_power_mw:,.0f} mW\n")
    if state.ane_power_mw is not None:
        lines.append(f"   ANE Power:          {state.ane_power_mw:,.0f} mW\n")

    source_labels = {
        "macos_powermetrics":    "sudo powermetrics",
        "macos_swift_fallback":  "Swift thermalState (sudo unavailable)",
        "linux_sysfs":           "/sys/class/thermal",
        "unavailable":           "unavailable",
    }
    lines.append(
        f"   Data source:        {source_labels.get(state.source, state.source)}\n",
        style="dim",
    )
    if state.pmset_warnings:
        lines.append("   ⚠ pmset warnings:   Thermal/performance warnings recorded\n", style="yellow")

    console.print(Panel(lines, title="[bold]Thermal Status[/bold]", border_style=style))
    console.print()


def _render_process_table(processes: list, console: Console) -> None:
    from rich.table import Table

    if not processes:
        console.print("[dim]No processes above threshold.[/dim]")
        return

    table = Table(
        title="Top Heat-Generating Processes",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("PID", width=7)
    table.add_column("Process", width=26)
    table.add_column("CPU %", justify="right", width=8)
    table.add_column("User", width=12)
    table.add_column("Safe to Kill?", width=16)

    for idx, proc in enumerate(processes, 1):
        safety_display, _ = _SAFETY_DISPLAY[proc.kill_safety]
        table.add_row(
            str(idx),
            str(proc.pid),
            proc.name,
            f"{proc.cpu_percent:.1f}%",
            proc.username or "?",
            safety_display,
        )

    console.print(table)
    console.print(
        "[dim]  Tip: high mW with low CPU % can indicate GPU/ANE load.[/dim]"
    )
    console.print(
        "[dim]  Run with --kill to terminate processes, "
        "--optimize to auto-reduce heat.[/dim]\n"
    )


def _run_kill_flow(processes: list, console: Console) -> None:
    """Interactive per-process kill loop. Generic over anything exposing
    .pid/.name/.kill_safety/.kill_reason — used by both `doctor thermal
    --kill` (CPU-ranked) and `doctor memory --kill` (RSS-ranked)."""
    candidates = [p for p in processes if p.kill_safety != KillSafety.UNSAFE]
    if not candidates:
        console.print("[yellow]No killable processes in the current list.[/yellow]")
        return

    console.print("[bold]Kill mode[/bold] — enter a PID to terminate (or 'q' to quit):\n")
    pid_map = {p.pid: p for p in candidates}

    while True:
        raw = typer.prompt("PID to kill", default="q")
        if raw.strip().lower() == "q":
            break
        try:
            pid = int(raw.strip())
        except ValueError:
            console.print("[red]Invalid input — enter a numeric PID.[/red]")
            continue

        proc = pid_map.get(pid)
        if proc is None:
            console.print(f"[yellow]PID {pid} not in the current list.[/yellow]")
            continue

        if proc.kill_safety == KillSafety.CAUTION:
            console.print(
                f"[yellow]⚠ '{proc.name}' is marked CAUTION: {proc.kill_reason}[/yellow]"
            )

        confirmed = typer.confirm(
            f"Kill '{proc.name}' (PID {proc.pid}) with SIGTERM?", default=False
        )
        if not confirmed:
            console.print("Skipped.")
            continue

        optimizer = ThermalOptimizer()
        success = optimizer.terminate_process(proc.pid, force=True)
        if success:
            console.print(f"[green]Sent SIGTERM to '{proc.name}' (PID {proc.pid}).[/green]")
            del pid_map[pid]
        else:
            console.print(f"[red]Failed to terminate '{proc.name}' (PID {proc.pid}).[/red]")


def _run_optimize_flow(
    processes: list,
    optimizer: ThermalOptimizer,
    console: Console,
    *,
    auto_mode: bool,
) -> None:
    """Scan + display optimization plan, then apply selected actions."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text

    console.print("[bold cyan]🔍 Scanning for optimization opportunities...[/bold cyan]\n")
    targets = optimizer.scan_optimizations(processes)

    if not targets:
        console.print("[green]No optimization opportunities found.[/green]\n")
        return

    actionable = [t for t in targets if t.action != OptimizationAction.SUGGESTION_ONLY]
    suggestions = [t for t in targets if t.action == OptimizationAction.SUGGESTION_ONLY]

    # -- Render plan ---------------------------------------------------------
    plan_lines = Text()

    if actionable:
        plan_lines.append("  Actions available:\n\n", style="bold")
        for idx, t in enumerate(actionable, 1):
            impact = "HIGH" if t.cpu_percent >= 30 else "MED" if t.cpu_percent >= 10 else "LOW"
            style = "red" if impact == "HIGH" else "yellow" if impact == "MED" else "dim"

            if t.action == OptimizationAction.CLOSE_TAB and t.browser_tabs:
                plan_lines.append(f"  [{idx}] {t.display_name}\n", style=style)
                plan_lines.append(
                    f"      {t.cpu_percent:.1f}% CPU  |  {t.reason}\n", style="dim"
                )
                plan_lines.append("      Open tabs:\n", style="dim")
                for tab in t.browser_tabs:
                    active_mark = " ← active" if tab.is_active else ""
                    short_url = tab.url[:55] + "…" if len(tab.url) > 55 else tab.url
                    plan_lines.append(
                        f"        [{tab.window_index}.{tab.tab_index}] "
                        f"{tab.title[:40]}  {short_url}{active_mark}\n",
                        style="dim",
                    )
            else:
                plan_lines.append(f"  [{idx}] {t.display_name}\n", style=style)
                plan_lines.append(
                    f"      {t.cpu_percent:.1f}% CPU  |  {t.reason}\n", style="dim"
                )

    if suggestions:
        plan_lines.append("\n  Suggestions (no auto-action):\n\n", style="bold dim")
        for s in suggestions:
            plan_lines.append(f"  [!] {s.display_name}\n", style="yellow")
            plan_lines.append(f"      {s.suggestion_text}\n", style="dim")

    console.print(Panel(plan_lines, title="[bold]Optimization Plan[/bold]", border_style="cyan"))

    # Print suggestions as standalone callouts too
    for s in suggestions:
        console.print(f"[yellow]  💡 {s.display_name}:[/yellow] {s.suggestion_text}")

    if not actionable:
        return

    # -- Apply ---------------------------------------------------------------
    to_apply: list = []

    if auto_mode:
        # Auto: only SAFE-classified kill targets
        to_apply = [
            t for t in actionable
            if t.action != OptimizationAction.CLOSE_TAB  # browser tabs need user input
        ]
        console.print(
            f"\n[cyan]Auto-optimize: applying {len(to_apply)} SAFE action(s)...[/cyan]\n"
        )
    else:
        console.print()
        raw = typer.prompt(
            "Apply actions? Enter numbers (e.g. 1,3), 'all', or 'none'",
            default="none",
        )
        sel = raw.strip().lower()
        if sel in ("none", ""):
            console.print("No actions applied.")
            return
        elif sel == "all":
            to_apply = list(actionable)
        else:
            try:
                indices = [int(i.strip()) for i in sel.split(",")]
                to_apply = [actionable[i - 1] for i in indices if 1 <= i <= len(actionable)]
            except (ValueError, IndexError):
                console.print("[red]Invalid selection.[/red]")
                return

    for t in to_apply:
        if t.action == OptimizationAction.CLOSE_TAB:
            _apply_browser_tab_close(t, optimizer, console)
        elif t.action == OptimizationAction.QUIT_APP and t.app_name:
            console.print(f"  Quitting '{t.app_name}'...", end="")
            ok = optimizer.quit_app_gracefully(t.app_name)
            console.print(" [green]Done[/green]" if ok else " [red]Failed[/red]")
        elif t.pid is not None:
            console.print(f"  Terminating '{t.display_name}' (PID {t.pid})...", end="")
            ok = optimizer.terminate_process(t.pid, force=True)
            console.print(" [green]Done[/green]" if ok else " [red]Failed[/red]")

    console.print("\n[green]Optimization complete.[/green]")


def _apply_browser_tab_close(target: "OptimizationTarget", optimizer: ThermalOptimizer, console: Console) -> None:  # type: ignore[name-defined]
    from doctor.services.thermal_optimizer import OptimizationTarget  # noqa: F401
    from doctor.services.browser_tab_service import BrowserTabService

    if not target.browser_tabs:
        console.print(f"[yellow]No open tabs found for {target.display_name}.[/yellow]")
        return

    console.print(f"\n[bold]Close tabs in {target.display_name}?[/bold]")
    for tab in target.browser_tabs:
        active_mark = " [cyan](active)[/cyan]" if tab.is_active else ""
        short_url = tab.url[:60] + "…" if len(tab.url) > 60 else tab.url
        console.print(
            f"  [{tab.window_index}.{tab.tab_index}] {tab.title[:45]}  "
            f"[dim]{short_url}[/dim]{active_mark}"
        )

    raw = typer.prompt(
        "\nEnter tab numbers to close (e.g. 1.2,1.3), 'all', or 'none'",
        default="none",
    )
    sel = raw.strip().lower()
    if sel in ("none", ""):
        console.print("  Skipped.")
        return

    browser_svc = BrowserTabService()
    tabs_to_close = []
    if sel == "all":
        tabs_to_close = [t for t in target.browser_tabs if not t.is_active]
        if not tabs_to_close:
            tabs_to_close = list(target.browser_tabs)
    else:
        tab_map = {f"{t.window_index}.{t.tab_index}": t for t in target.browser_tabs}
        for key in sel.split(","):
            k = key.strip()
            if k in tab_map:
                tabs_to_close.append(tab_map[k])
            else:
                console.print(f"  [yellow]'{k}' not recognised — skipped.[/yellow]")

    for tab in tabs_to_close:
        console.print(f"  Closing '{tab.title[:45]}'...", end="")
        ok = browser_svc.close_tab(tab)
        console.print(" [green]Done[/green]" if ok else " [red]Failed[/red]")


# ---------------------------------------------------------------------------
# `doctor memory` command
# ---------------------------------------------------------------------------

@app.command("memory")
def memory_cmd(
    top: int = typer.Option(10, "--top", help="Number of top RAM-consuming processes to display."),
    threshold: float = typer.Option(0.1, "--threshold", help="Min RSS in GB to include a process."),
    kill: bool = typer.Option(False, "--kill", help="Interactive per-process kill mode."),
    optimize: bool = typer.Option(False, "--optimize", help="Scan and propose a plan to free RAM."),
    auto_optimize: bool = typer.Option(False, "--auto-optimize", help="Silently apply all SAFE optimizations."),
) -> None:
    """Show RAM/swap usage and the top RAM-consuming processes.

    Use --optimize to get an actionable plan to free RAM.
    Use --kill to manually terminate specific processes.
    """
    process_service = ProcessService()
    optimizer = MemoryOptimizer()

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    processes = process_service.sample_memory_processes(limit=top, min_rss_gb=threshold)

    _render_memory_header(vm, swap, console)
    _render_memory_process_table(processes, console)

    if optimize or auto_optimize:
        _run_memory_optimize_flow(processes, optimizer, console, auto_mode=auto_optimize)
    elif kill:
        _run_kill_flow(processes, console)


# ---------------------------------------------------------------------------
# Memory rendering helpers
# ---------------------------------------------------------------------------

def _render_memory_header(vm: Any, swap: Any, console: Console) -> None:
    from rich.panel import Panel
    from rich.text import Text

    used_gb = vm.used / (1024**3)
    total_gb = vm.total / (1024**3)
    swap_gb = swap.used / (1024**3)

    style = "green" if vm.percent < 80 else "yellow" if vm.percent < 95 else "red"

    lines = Text()
    lines.append("RAM:   ", style="bold")
    lines.append(f"{used_gb:.1f} GB / {total_gb:.1f} GB  ({vm.percent:.0f}%)\n", style=style)
    lines.append("Swap:  ", style="bold")
    swap_style = "green" if swap_gb < 2 else "yellow" if swap_gb < 8 else "red"
    lines.append(f"{swap_gb:.1f} GB used\n", style=swap_style)

    console.print(Panel(lines, title="[bold]Memory Status[/bold]", border_style=style))
    console.print()


def _render_memory_process_table(processes: list, console: Console) -> None:
    from rich.table import Table

    if not processes:
        console.print("[dim]No processes above threshold.[/dim]")
        return

    table = Table(
        title="Top RAM-Consuming Processes",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("PID", width=7)
    table.add_column("Process", width=26)
    table.add_column("RAM", justify="right", width=9)
    table.add_column("User", width=12)
    table.add_column("Safe to Kill?", width=16)

    for idx, proc in enumerate(processes, 1):
        safety_display, _ = _SAFETY_DISPLAY[proc.kill_safety]
        table.add_row(
            str(idx),
            str(proc.pid),
            proc.name,
            f"{proc.rss_gb:.1f} GB",
            proc.username or "?",
            safety_display,
        )

    console.print(table)
    console.print(
        "[dim]  Run with --kill to terminate processes, "
        "--optimize to auto-reduce RAM usage.[/dim]\n"
    )


def _run_memory_optimize_flow(
    processes: list,
    optimizer: MemoryOptimizer,
    console: Console,
    *,
    auto_mode: bool,
) -> None:
    """Scan + display a RAM-reduction plan, then apply selected actions.

    Mirrors _run_optimize_flow's shape (thermal/CPU) but simpler — memory
    targets have no browser-tab-level granularity (§ deferred: closing
    individual RAM-heavy tabs rather than the whole renderer process)."""
    from rich.panel import Panel
    from rich.text import Text

    console.print("[bold cyan]🔍 Scanning for RAM to free...[/bold cyan]\n")
    targets = optimizer.scan(processes)

    if not targets:
        console.print("[green]No optimization opportunities found.[/green]\n")
        return

    actionable = [t for t in targets if t.action != OptimizationAction.SUGGESTION_ONLY]
    suggestions = [t for t in targets if t.action == OptimizationAction.SUGGESTION_ONLY]

    plan_lines = Text()

    if actionable:
        plan_lines.append("  Actions available:\n\n", style="bold")
        for idx, t in enumerate(actionable, 1):
            impact = "HIGH" if t.rss_gb >= 2 else "MED" if t.rss_gb >= 0.5 else "LOW"
            style = "red" if impact == "HIGH" else "yellow" if impact == "MED" else "dim"
            plan_lines.append(f"  [{idx}] {t.display_name}\n", style=style)
            plan_lines.append(f"      {t.rss_gb:.1f} GB RAM  |  {t.reason}\n", style="dim")

    if suggestions:
        plan_lines.append("\n  Suggestions (no auto-action):\n\n", style="bold dim")
        for s in suggestions:
            plan_lines.append(f"  [!] {s.display_name}\n", style="yellow")
            plan_lines.append(f"      {s.suggestion_text}\n", style="dim")

    console.print(Panel(plan_lines, title="[bold]Optimization Plan[/bold]", border_style="cyan"))

    for s in suggestions:
        console.print(f"[yellow]  💡 {s.display_name}:[/yellow] {s.suggestion_text}")

    if not actionable:
        return

    to_apply: list = []

    if auto_mode:
        to_apply = list(actionable)
        console.print(
            f"\n[cyan]Auto-optimize: applying {len(to_apply)} SAFE action(s)...[/cyan]\n"
        )
    else:
        console.print()
        raw = typer.prompt(
            "Apply actions? Enter numbers (e.g. 1,3), 'all', or 'none'",
            default="none",
        )
        sel = raw.strip().lower()
        if sel in ("none", ""):
            console.print("No actions applied.")
            return
        elif sel == "all":
            to_apply = list(actionable)
        else:
            try:
                indices = [int(i.strip()) for i in sel.split(",")]
                to_apply = [actionable[i - 1] for i in indices if 1 <= i <= len(actionable)]
            except (ValueError, IndexError):
                console.print("[red]Invalid selection.[/red]")
                return

    for t in to_apply:
        if t.action == OptimizationAction.QUIT_APP and t.app_name:
            console.print(f"  Quitting '{t.app_name}'...", end="")
            ok = optimizer.quit_app_gracefully(t.app_name)
            console.print(" [green]Done[/green]" if ok else " [red]Failed[/red]")
        else:
            console.print(f"  Terminating '{t.display_name}' (PID {t.pid})...", end="")
            ok = optimizer.terminate_process(t.pid, force=True)
            console.print(" [green]Done[/green]" if ok else " [red]Failed[/red]")

    console.print("\n[green]Optimization complete.[/green]")


if __name__ == "__main__":
    app()