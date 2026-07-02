from doctor.models import Report


def render_json(report: Report) -> str:
    """Render a Report as pretty-printed JSON."""
    return report.model_dump_json(indent=2)