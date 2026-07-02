import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class PluginsConfig(BaseModel):
    """Controls which plugins run.

    If `enabled` is non-empty, it acts as a whitelist — ONLY those
    plugins run (still subject to is_supported()). Otherwise, `disabled`
    acts as a blacklist on top of the full built-in set.
    """

    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)


class DoctorConfig(BaseModel):
    """Root config model for doctor.toml (§15)."""

    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    thresholds: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Per-plugin threshold overrides, e.g. thresholds.cpu.warn_percent = 60",
    )


DEFAULT_CONFIG = DoctorConfig()


def find_config_file(start: Path | None = None) -> Path | None:
    """Search upward from `start` (default: cwd) for a doctor.toml file,
    the same way Git searches for a .git directory — supports running
    `doctor` from any subdirectory of a project."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / "doctor.toml"
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> DoctorConfig:
    """Load doctor.toml, or return defaults if none exists / it's invalid.

    A missing or malformed config file is never fatal — doctor must work
    with zero configuration out of the box (§2.1).
    """
    config_path = path or find_config_file()
    if config_path is None:
        return DEFAULT_CONFIG

    try:
        raw = tomllib.loads(config_path.read_text())
        return DoctorConfig.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return DEFAULT_CONFIG