import yaml

from doctor.models import Report


def render_yaml(report: Report) -> str:
    """Render a Report as YAML."""
    data = report.model_dump(mode="json")
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)