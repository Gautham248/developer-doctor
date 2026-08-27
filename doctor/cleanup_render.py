from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from doctor.models import CleanupReport


def format_bytes(bytes_count: int) -> str:
    """Format bytes into a human-readable string."""
    if bytes_count <= 0:
        return "0 B"
    units = [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]
    for unit, multiplier in units:
        if bytes_count >= multiplier:
            return f"{bytes_count / multiplier:.1f} {unit}"
    return f"{bytes_count} B"


def render_cleanup_scan(report: CleanupReport, console: Console) -> None:
    """Render the cleanup categories scan results in a rich table."""
    console.print()
    console.print(Text("Disk Space Scan Summary", style="bold cyan"))
    console.print(Text("Analyze potential space savings before cleaning up caches and builds.", style="dim"))
    console.print()

    table = Table(
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
    )
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Category", style="bold white")
    table.add_column("Size", justify="right")
    table.add_column("Auto Clean?", justify="center")
    table.add_column("Details", style="dim")

    for idx, cat in enumerate(report.categories, 1):
        # Format size column with colors based on magnitude
        size_str = format_bytes(cat.size_bytes)
        if cat.size_bytes >= 1024**3:  # >= 1GB
            size_styled = f"[bold red]{size_str}[/bold red]"
        elif cat.size_bytes >= 100 * 1024**2:  # >= 100MB
            size_styled = f"[bold yellow]{size_str}[/bold yellow]"
        elif cat.size_bytes > 0:
            size_styled = f"[green]{size_str}[/green]"
        else:
            size_styled = "[dim]0 B[/dim]"

        safe_styled = "[green]Yes[/green]" if cat.is_safe_to_auto_clean else "[bold yellow]No (workspace files)[/bold yellow]"

        details_str = ", ".join(cat.paths[:3])
        if len(cat.paths) > 3:
            details_str += f" (+{len(cat.paths) - 3} more)"
        if not details_str:
            details_str = "No files found"

        table.add_row(
            str(idx),
            cat.label,
            size_styled,
            safe_styled,
            details_str
        )

    console.print(table)
    console.print()

    total_formatted = format_bytes(report.total_size_bytes)
    summary_panel = Panel(
        Text(f"Total Reclaimable Space: {total_formatted}", style="bold green", justify="center"),
        border_style="green",
        expand=False,
    )
    console.print(summary_panel)
    console.print()


def render_cleanup_summary(freed_bytes: int, categories: list[str], console: Console) -> None:
    """Render a summary panel after cleanup completes."""
    freed_str = format_bytes(freed_bytes)
    cats_str = ", ".join(categories) if categories else "none"

    body = [
        Text(f"Successfully reclaimed: {freed_str}", style="bold green"),
        Text(f"Categories cleaned: {cats_str}", style="dim"),
    ]

    panel = Panel(
        "\n".join(str(t) for t in body),
        title="[bold green]Cleanup Completed[/bold green]",
        border_style="green",
        expand=False,
    )
    console.print()
    console.print(panel)
    console.print()
