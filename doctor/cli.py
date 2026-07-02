import typer
from rich.console import Console

from doctor.registry import get_plugins
from doctor.report import render_report
from doctor.scoring import compute_health_score

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
console = Console()


@app.command()
def main():
    """Run all diagnostics and print a health report."""
    results = [plugin.run() for plugin in get_plugins()]
    score = compute_health_score(results)
    render_report(results, score, console)


if __name__ == "__main__":
    app()