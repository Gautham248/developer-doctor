from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from doctor.models import PluginResult, Status
from doctor.baseline import PluginDiff
from doctor.trend import MetricTrend

STATUS_STYLE: dict[Status, tuple[str, str]] = {
    Status.PASS: ("green", "✓"),
    Status.WARN: ("yellow", "⚠"),
    Status.FAIL: ("red", "✗"),
    Status.INFO: ("cyan", "ℹ"),
}

def render_diff(
    title: str,
    diffs: list[PluginDiff],
    before_score: int,
    after_score: int,
    console: Console,
) -> None:
    """Render a diff between two reports — shared by baseline compare
    (§16) and snapshot diff (§17); both ultimately compare two Reports,
    they just differ in how the "before" report was chosen."""
    console.print()
    console.print(Text(title, style="bold"))
    console.print()

    score_diff = after_score - before_score
    score_color = "green" if score_diff >= 0 else "red"
    sign = "+" if score_diff >= 0 else ""
    console.print(
        f"Health Score: {before_score} → {after_score} "
        f"([{score_color}]{sign}{score_diff}[/{score_color}])"
    )
    console.print()

    changed = [d for d in diffs if d.has_changes]
    unchanged = [d for d in diffs if not d.has_changes]

    if not changed:
        console.print("[green]No changes detected.[/green]")
        return

    for diff in changed:
        console.print(_render_diff_panel(diff))
        console.print()

    if unchanged:
        names = ", ".join(d.plugin_name for d in unchanged)
        console.print(f"[dim]Unchanged: {names}[/dim]")


def render_trends(trends: list[MetricTrend], num_snapshots: int, console: Console) -> None:
    """Render trend analysis (§17) to the terminal."""
    console.print()
    console.print(Text("Trend Analysis", style="bold"))
    console.print(Text(f"Computed across {num_snapshots} snapshots", style="dim"))
    console.print()

    if not trends:
        console.print(
            "[dim]No significant trends detected — need enough snapshots per "
            "metric and a meaningful change to report.[/dim]"
        )
        return

    for trend in trends:
        console.print(_render_trend_line(trend))


def _render_trend_line(trend: MetricTrend) -> Text:
    color = "red" if trend.direction == "up" else "green" if trend.direction == "down" else "white"
    arrow = "↑" if trend.direction == "up" else "↓" if trend.direction == "down" else "→"
    pct = trend.percent_change
    span_days = max(1, (trend.last_seen - trend.first_seen).days)

    pct_str = f"{pct:+.0f}%" if pct is not None else f"{trend.last_value - trend.first_value:+.2f}"
    text = Text()
    text.append(f"{arrow} ", style=color)
    text.append(f"{trend.plugin_name}.{trend.metric_key}: ", style="bold")
    text.append(f"{trend.first_value:.1f} → {trend.last_value:.1f} ", style=color)
    text.append(f"({pct_str} over {span_days}d, {trend.num_points} snapshots)", style="dim")
    return text

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