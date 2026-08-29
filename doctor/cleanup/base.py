from abc import ABC, abstractmethod
from pathlib import Path

from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


def is_safe_workspace_dir(cwd: Path | None = None) -> bool:
    """Return False if cwd is a system root or the user's home directory.

    Running recursive workspace scans (for local node_modules, build/dist, __pycache__)
    from ~ or / is dangerous because it traverses into global tool installations
    (like mise, nvm, cargo, virtualenvs) and corrupts runtime dependencies.
    """
    path = (cwd or Path.cwd()).resolve()
    try:
        home = Path.home().resolve()
        if path == home:
            return False
    except (RuntimeError, OSError):
        pass

    root = Path("/").resolve()
    if path == root or path.parent == path:
        return False

    if path in (Path("/Users").resolve(), Path("/home").resolve(), Path("/root").resolve()):
        return False

    return True


SYSTEM_IGNORED_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    ".local",
    ".cache",
    ".mise",
    ".nvm",
    ".cargo",
    ".rustup",
    ".config",
    ".Trash",
    "Library",
    "Applications",
    "vendor",
    "Pods",
})

IGNORED_FOR_NODE_SCAN = frozenset({
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    ".local",
    ".cache",
    ".mise",
    ".nvm",
    ".cargo",
    ".rustup",
    ".config",
    ".Trash",
    "Library",
    "Applications",
    "vendor",
    "Pods",
})


class BaseScanner(ABC):
    """Base class for all space-scanning and cleanup units."""

    name: str
    label: str
    is_safe_to_auto_clean: bool = True

    def is_supported(self) -> bool:
        """Return True if the scanner is supported on the current workstation/OS."""
        return True

    @abstractmethod
    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        """Measure files or systems and return a CleanupCategory with sizes and metadata."""
        pass

    @abstractmethod
    def clean(self, clean_service: CleanService, category_detail: CleanupCategory) -> int:
        """Clean up resources of this category and return total bytes freed."""
        pass

