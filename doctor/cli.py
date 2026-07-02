import typer
from rich.console import Console

from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Report
from doctor.registry import get_plugins
from doctor.report import render_report
from doctor.scoring import compute_health_score

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
console = Console()


@app.command()
def main(
    json_output: bool = typer.Option(False, "--json", help="Output a machine-readable JSON report."),
    yaml_output: bool = typer.Option(False, "--yaml", help="Output a machine-readable YAML report."),
) -> None:
    """Run all diagnostics and print a health report."""
    if json_output and yaml_output:
        console.print("[bold red]Error:[/bold red] --json and --yaml cannot be used together.")
        raise typer.Exit(code=1)

    results = [plugin.run() for plugin in get_plugins()]
    score = compute_health_score(results)
    report = Report(score=score, results=results)

    if json_output:
        print(render_json(report))
    elif yaml_output:
        print(render_yaml(report))
    else:
        render_report(results, score, console)


if __name__ == "__main__":
    app()