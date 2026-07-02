import json
from pathlib import Path

import platformdirs

APP_NAME = "developer-doctor"


def _state_dir() -> Path:
    path = Path(platformdirs.user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(key: str) -> dict[str, str]:
    """Load persisted state for a given key (typically a plugin name).

    Returns an empty dict if no state file exists yet, or if it's
    corrupted — state is a best-effort cache a plugin can lose without
    consequence, never something to crash over.
    """
    state_file = _state_dir() / f"{key}.json"
    if not state_file.exists():
        return {}
    try:
        data: dict[str, str] = json.loads(state_file.read_text())
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(key: str, data: dict[str, str]) -> None:
    """Persist state for a given key. Best-effort — write failures are
    swallowed, since losing historical state should never crash a
    diagnostic run."""
    state_file = _state_dir() / f"{key}.json"
    try:
        state_file.write_text(json.dumps(data))
    except OSError:
        pass