from doctor.formatters.html_formatter import render_html
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
            )
        ],
    )


def test_render_html_is_well_formed():
    output = render_html(_sample_report())
    assert output.startswith("<!DOCTYPE html>")
    assert "</html>" in output
    assert "<title>Developer Doctor Report</title>" in output


def test_render_html_includes_score_and_plugin_data():
    output = render_html(_sample_report())
    assert "95 / 100" in output
    assert "cpu" in output
    assert "CPU usage: 75%" in output
    assert "Check top processes." in output
    assert "WARN" in output


def test_render_html_escapes_untrusted_content():
    report = Report(
        score=100,
        results=[
            PluginResult(
                plugin_name="git",
                status=Status.PASS,
                findings=[Finding(summary="<script>alert('xss')</script>")],
            )
        ],
    )
    output = render_html(report)
    assert "<script>alert" not in output
    assert "&lt;script&gt;" in output


def test_render_html_handles_no_findings():
    report = Report(
        score=100,
        results=[PluginResult(plugin_name="empty", status=Status.INFO, findings=[])],
    )
    output = render_html(report)
    assert "No findings" in output