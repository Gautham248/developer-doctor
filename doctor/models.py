from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


class Finding(BaseModel):
    """A single observation made by a plugin."""

    summary: str
    detail: str | None = None


class PluginResult(BaseModel):
    """Structured output every plugin must return from run()."""

    plugin_name: str
    status: Status
    score_delta: int = Field(
        default=0,
        description="Points to subtract from the health score (0 for PASS/INFO).",
    )
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional raw machine-readable payload for JSON/YAML renderers.",
    )


class Report(BaseModel):
    """The full output of a doctor run — the single object every renderer
    (Rich terminal, JSON, YAML, future HTML/SARIF/JUnit) consumes."""

    score: int
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    results: list[PluginResult]