import sys
import os
from pathlib import Path

from doctor.cleanup.base import BaseScanner, is_safe_workspace_dir, SYSTEM_IGNORED_DIRS
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService

PYTHON_CACHE_NAMES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


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

        # 2. Local workspace python artifacts (only if inside a project workspace, not ~ or /)
        cwd = Path.cwd()
        if is_safe_workspace_dir(cwd):
            try:
                for root, dirs, files in os.walk(cwd, followlinks=False):
                    dirs[:] = [
                        d for d in dirs
                        if d in PYTHON_CACHE_NAMES or (d not in SYSTEM_IGNORED_DIRS and not d.startswith("."))
                    ]
                    for d in list(dirs):
                        if d in PYTHON_CACHE_NAMES:
                            p = Path(root) / d
                            sz = cleanup_service.measure_path(p)
                            if sz > 0:
                                paths_to_check.append(str(p))
                                size_bytes += sz
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
