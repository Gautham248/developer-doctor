import typer
from rich.console import Console

from doctor.config import load_config
from doctor.formatters.html_formatter import render_html
from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Report
from doctor.registry import discover_all_plugins
from doctor.report import render_report
from doctor.scoring import compute_health_score

app = typer.Typer(help="Developer Doctor — diagnose your dev workstation")
console = Console()


@app.command()
def main(
    json_output: bool = typer.Option(False, "--json", help="Output a machine-readable JSON report."),
    yaml_output: bool = typer.Option(False, "--yaml", help="Output a machine-readable YAML report."),
    html_output: bool = typer.Option(False, "--html", help="Output a self-contained HTML report."),
) -> None:
    """Run all diagnostics and print a health report."""
    selected_formats = [f for f in (json_output, yaml_output, html_output) if f]
    if len(selected_formats) > 1:
        console.print("[bold red]Error:[/bold red] --json, --yaml, and --html are mutually exclusive.")
        raise typer.Exit(code=1)

    config = load_config()
    plugins, discovery_errors = discover_all_plugins(config)

    machine_readable = json_output or yaml_output or html_output
    if discovery_errors and not machine_readable:
        for error in discovery_errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

    results = [plugin.run() for plugin in plugins]
    score = compute_health_score(results)
    report = Report(score=score, results=results)

    if json_output:
        print(render_json(report))
    elif yaml_output:
        print(render_yaml(report))
    elif html_output:
        print(render_html(report))
    else:
        render_report(results, score, console)


if __name__ == "__main__":
    app()