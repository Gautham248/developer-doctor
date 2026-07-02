from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from doctor.models import PluginResult, Status
from datetime import datetime
from doctor.baseline import PluginDiff

STATUS_STYLE: dict[Status, tuple[str, str]] = {
    Status.PASS: ("green", "✓"),
    Status.WARN: ("yellow", "⚠"),
    Status.FAIL: ("red", "✗"),
    Status.INFO: ("cyan", "ℹ"),
}

def render_baseline_diff(
    diffs: list[PluginDiff],
    baseline_score: int,
    current_score: int,
    baseline_generated_at: datetime,
    console: Console,
) -> None:
    """Render a baseline comparison (§16) to the terminal."""
    console.print()
    console.print(Text("Baseline Comparison", style="bold"))
    console.print(Text(f"Baseline captured: {baseline_generated_at.isoformat()}", style="dim"))
    console.print()

    score_diff = current_score - baseline_score
    score_color = "green" if score_diff >= 0 else "red"
    sign = "+" if score_diff >= 0 else ""
    console.print(
        f"Health Score: {baseline_score} → {current_score} "
        f"([{score_color}]{sign}{score_diff}[/{score_color}])"
    )
    console.print()

    changed = [d for d in diffs if d.has_changes]
    unchanged = [d for d in diffs if not d.has_changes]

    if not changed:
        console.print("[green]No changes detected since baseline.[/green]")
        return

    for diff in changed:
        console.print(_render_diff_panel(diff))
        console.print()

    if unchanged:
        names = ", ".join(d.plugin_name for d in unchanged)
        console.print(f"[dim]Unchanged: {names}[/dim]")


def _render_diff_panel(diff: PluginDiff) -> Panel:
    lines: list[Text] = []
    if diff.status_changed:
        lines.append(
            Text(f"Status: {diff.baseline_status or '—'} → {diff.current_status or '—'}")
        )
    for key, (old, new) in diff.changed_metadata.items():
        lines.append(Text(f"{key}: {old} → {new}"))

    body = Group(*lines) if lines else Text("(no details)", style="dim")
    color = "yellow" if diff.status_changed else "cyan"
    return Panel(
        body,
        title=f"[bold {color}]{diff.plugin_name}[/bold {color}]",
        title_align="left",
        border_style=color,
    )

def render_report(results: list[PluginResult], score: int, console: Console) -> None:
    """Render a full diagnostic report to the terminal.

    This is the sole place that knows how to turn structured PluginResults
    into human-facing output — plugins and the scoring engine never format
    anything themselves (§19).
    """
    console.print()
    console.print(Text("Developer Doctor", style="bold"))
    console.print()

    for result in results:
        console.print(_render_plugin_panel(result))
        console.print()

    console.print(_render_score_panel(score, results))
    console.print()


def _render_plugin_panel(result: PluginResult) -> Panel:
    color, icon = STATUS_STYLE[result.status]

    body_lines: list[Text] = []
    for idx, finding in enumerate(result.findings):
        style = color if idx == 0 else ""
        body_lines.append(Text(f"{icon} {finding.summary}", style=style))

    for rec in result.recommendations:
        body_lines.append(Text(f"→ {rec}", style="yellow"))

    body = Group(*body_lines) if body_lines else Text("(no findings)", style="dim")

    return Panel(
        body,
        title=f"[bold {color}]{result.plugin_name}[/bold {color}] — {result.status.value}",
        title_align="left",
        border_style=color,
    )

def _render_score_panel(score: int, results: list[PluginResult]) -> Panel:
    if score >= 90:
        color = "green"
    elif score >= 70:
        color = "yellow"
    else:
        color = "red"

    warn_count = sum(1 for r in results if r.status == Status.WARN)
    fail_count = sum(1 for r in results if r.status == Status.FAIL)

    summary_line = Text()
    summary_line.append(f"{score} / 100", style=f"bold {color}")
    if warn_count or fail_count:
        parts = []
        if fail_count:
            parts.append(f"{fail_count} failing")
        if warn_count:
            parts.append(f"{warn_count} warning")
        summary_line.append(f"  ({', '.join(parts)})", style="dim")

    return Panel(
        Padding(summary_line, (0, 1)),
        title="[bold]Health Score[/bold]",
        title_align="left",
        border_style=color,
    )