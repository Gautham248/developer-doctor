import sys
import os
from pathlib import Path

from doctor.cleanup.base import BaseScanner
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class PythonScanner(BaseScanner):
    name = "python"
    label = "Python build and package caches (pip, uv, pycache, pytest, ruff, mypy)"
    is_safe_to_auto_clean = True

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        paths_to_check = []
        size_bytes = 0

        # 1. System caches
        home = Path.home()
        if sys.platform == "darwin":
            pip_cache = home / "Library/Caches/pip"
            uv_cache = home / "Library/Caches/uv"
        else:
            pip_cache = home / ".cache/pip"
            uv_cache = home / ".cache/uv"

        for cache_path in [pip_cache, uv_cache]:
            if cache_path.exists():
                sz = cleanup_service.measure_path(cache_path)
                if sz > 0:
                    paths_to_check.append(str(cache_path))
                    size_bytes += sz

        # 2. Local workspace python artifacts
        cwd = Path.cwd()
        # To avoid scanning huge directories or other projects, we only scan up to 3 levels deep
        # or recursively but ignoring node_modules, .git, etc.
        try:
            for root, dirs, files in os.walk(cwd, followlinks=False):
                # Modify dirs in-place to prune search
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv", "env")]
                for d in list(dirs):
                    if d in ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
                        p = Path(root) / d
                        sz = cleanup_service.measure_path(p)
                        if sz > 0:
                            paths_to_check.append(str(p))
                            size_bytes += sz
                        # Don't recurse into these since we are deleting them
                        dirs.remove(d)
        except OSError:
            pass

        return CleanupCategory(
            name=self.name,
            label=self.label,
            size_bytes=size_bytes,
            paths=paths_to_check,
            is_safe_to_auto_clean=self.is_safe_to_auto_clean,
        )

    def clean(self, clean_service: CleanService, category_detail: CleanupCategory) -> int:
        freed = 0
        for path_str in category_detail.paths:
            freed += clean_service.remove_path(Path(path_str))

        # Also run package managers' built-in prune commands as a fallback
        clean_service.pip_cache_purge()
        clean_service.uv_cache_clean()
        return freed
