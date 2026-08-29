import sys
import os
from pathlib import Path

from doctor.cleanup.base import BaseScanner, is_safe_workspace_dir, IGNORED_FOR_NODE_SCAN
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class NodeScanner(BaseScanner):
    name = "node"
    label = "Node.js dependencies and package caches (npm, yarn, pnpm caches, local node_modules)"
    is_safe_to_auto_clean = True

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        paths_to_check = []
        size_bytes = 0
        has_local_node_modules = False

        # 1. System caches
        home = Path.home()
        npm_cache = home / ".npm"

        if sys.platform == "darwin":
            yarn_cache = home / "Library/Caches/Yarn"
            pnpm_cache = home / "Library/Caches/pnpm"
        else:
            yarn_cache = home / ".cache/yarn"
            pnpm_cache = home / ".cache/pnpm"

        pnpm_store = home / ".local/share/pnpm/store"

        for cache_path in [npm_cache, yarn_cache, pnpm_cache, pnpm_store]:
            if cache_path.exists():
                sz = cleanup_service.measure_path(cache_path)
                if sz > 0:
                    paths_to_check.append(str(cache_path))
                    size_bytes += sz

        # 2. Local node_modules in workspace (only if inside a project workspace, not ~ or /)
        cwd = Path.cwd()
        if is_safe_workspace_dir(cwd):
            try:
                for root, dirs, files in os.walk(cwd, followlinks=False):
                    # Don't recurse into tool installations, system dirs, or hidden dot-dirs
                    dirs[:] = [
                        d for d in dirs
                        if d not in IGNORED_FOR_NODE_SCAN and (not d.startswith(".") or d == "node_modules")
                    ]
                    if "node_modules" in dirs:
                        p = Path(root) / "node_modules"
                        sz = cleanup_service.measure_path(p)
                        if sz > 0:
                            paths_to_check.append(str(p))
                            size_bytes += sz
                            has_local_node_modules = True
                        # Don't recurse into node_modules itself
                        dirs.remove("node_modules")
            except OSError:
                pass

        # If local node_modules were found, this category is NOT safe to auto-clean
        # and requires explicit user review / confirmation.
        is_safe = not has_local_node_modules

        return CleanupCategory(
            name=self.name,
            label=self.label,
            size_bytes=size_bytes,
            paths=paths_to_check,
            is_safe_to_auto_clean=is_safe,
        )

    def clean(self, clean_service: CleanService, category_detail: CleanupCategory) -> int:
        freed = 0
        for path_str in category_detail.paths:
            freed += clean_service.remove_path(Path(path_str))

        # Run npm cache clean CLI command as a fallback
        clean_service.npm_cache_clean()
        return freed
