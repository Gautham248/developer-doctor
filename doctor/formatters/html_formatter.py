import html

from doctor.models import PluginResult, Report, Status

STATUS_COLORS: dict[Status, str] = {
    Status.PASS: "#2e8b57",
    Status.WARN: "#b8860b",
    Status.FAIL: "#c0392b",
    Status.INFO: "#2980b9",
}

STATUS_BG: dict[Status, str] = {
    Status.PASS: "#f0f9f4",
    Status.WARN: "#fdf6e8",
    Status.FAIL: "#fbeae8",
    Status.INFO: "#eaf3fb",
}


def render_html(report: Report) -> str:
    """Render a Report as a single self-contained HTML page.

    All plugin-supplied strings (findings, recommendations, metadata keys
    reflected in text) originate from system state — process names, git
    remotes, error messages — which is untrusted enough to escape
    defensively even though this isn't a multi-user web context.
    """
    score_color = _score_color(report.score)
    plugin_sections = "\n".join(_render_plugin_section(result) for result in report.results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Developer Doctor Report</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #fafafa;
    color: #1a1a1a;
    max-width: 800px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.5;
  }}
  h1 {{ font-size: 1.5rem; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 2rem; }}
  .score-panel {{
    border: 2px solid {score_color};
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 2rem;
    background: white;
  }}
  .score-value {{ font-size: 2rem; font-weight: bold; color: {score_color}; }}
  .plugin-panel {{
    border: 1px solid #ddd;
    border-left: 4px solid;
    border-radius: 6px;
    padding: 14px 18px;
    margin-bottom: 14px;
  }}
  .plugin-title {{ font-weight: 600; font-size: 1rem; margin-bottom: 8px; }}
  .status-badge {{
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 4px;
    margin-left: 8px;
  }}
  ul {{ margin: 6px 0; padding-left: 20px; }}
  li {{ margin: 3px 0; }}
  .recommendation {{ color: #8a6d00; }}
</style>
</head>
<body>
<h1>Developer Doctor Report</h1>
<div class="meta">Generated at {html.escape(report.generated_at.isoformat())}</div>

<div class="score-panel">
  <div>Health Score</div>
  <div class="score-value">{report.score} / 100</div>
</div>

{plugin_sections}

</body>
</html>
"""


def _render_plugin_section(result: PluginResult) -> str:
    color = STATUS_COLORS[result.status]
    bg = STATUS_BG[result.status]
    name = html.escape(result.plugin_name)
    status_label = html.escape(result.status.value)

    findings_html = "".join(
        f"<li>{html.escape(finding.summary)}</li>" for finding in result.findings
    )
    findings_block = f"<ul>{findings_html}</ul>" if findings_html else "<p><em>No findings</em></p>"

    recommendations_html = ""
    if result.recommendations:
        rec_items = "".join(
            f"<li>{html.escape(rec)}</li>" for rec in result.recommendations
        )
        recommendations_html = f'<ul class="recommendation">{rec_items}</ul>'

    return f"""<div class="plugin-panel" style="border-left-color: {color}; background: {bg};">
  <div class="plugin-title">
    {name}
    <span class="status-badge" style="background: {color}; color: white;">{status_label}</span>
  </div>
  {findings_block}
  {recommendations_html}
</div>"""


def _score_color(score: int) -> str:
    if score >= 90:
        return "#2e8b57"
    if score >= 70:
        return "#b8860b"
    return "#c0392b"