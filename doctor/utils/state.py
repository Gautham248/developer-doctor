import json
from pathlib import Path
from typing import Any

import platformdirs

APP_NAME = "developer-doctor"


def _state_dir() -> Path:
    path = Path(platformdirs.user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(key: str) -> Any | None:
    """Load arbitrary JSON-serializable state for a given key.

    Returns None if no state file exists yet, or if it's corrupted —
    state is a best-effort cache a caller can lose without consequence,
    never something to crash over.
    """
    state_file = _state_dir() / f"{key}.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_json(key: str, data: Any) -> None:
    """Persist arbitrary JSON-serializable state for a given key.
    Best-effort — write failures are swallowed, since losing state
    should never crash a diagnostic run."""
    state_file = _state_dir() / f"{key}.json"
    try:
        state_file.write_text(json.dumps(data))
    except OSError:
        pass


def load_state(key: str) -> dict[str, str]:
    """Typed convenience wrapper over load_json for simple string-keyed
    state (used by the AI IDE plugin). Returns {} if missing, corrupted,
    or not shaped as a dict."""
    data = load_json(key)
    return data if isinstance(data, dict) else {}


def save_state(key: str, data: dict[str, str]) -> None:
    save_json(key, data)