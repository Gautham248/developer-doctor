import json

import yaml

from doctor.formatters.json_formatter import render_json
from doctor.formatters.yaml_formatter import render_yaml
from doctor.models import Finding, PluginResult, Report, Status


def _sample_report() -> Report:
    return Report(
        score=95,
        results=[
            PluginResult(
                plugin_name="cpu",
                status=Status.WARN,
                score_delta=5,
                findings=[Finding(summary="CPU usage: 75%")],
                recommendations=["Check top processes."],
                metadata={"cpu_percent": 75.0},
            )
        ],
    )


def test_render_json_is_valid_and_complete():
    report = _sample_report()
    output = render_json(report)
    parsed = json.loads(output)

    assert parsed["score"] == 95
    assert parsed["results"][0]["plugin_name"] == "cpu"
    assert parsed["results"][0]["status"] == "WARN"
    assert parsed["results"][0]["findings"][0]["summary"] == "CPU usage: 75%"


def test_render_yaml_is_valid_and_complete():
    report = _sample_report()
    output = render_yaml(report)
    parsed = yaml.safe_load(output)

    assert parsed["score"] == 95
    assert parsed["results"][0]["plugin_name"] == "cpu"
    assert parsed["results"][0]["status"] == "WARN"


def test_json_and_yaml_report_same_data():
    report = _sample_report()
    json_data = json.loads(render_json(report))
    yaml_data = yaml.safe_load(render_yaml(report))

    assert json_data["score"] == yaml_data["score"]
    assert len(json_data["results"]) == len(yaml_data["results"])