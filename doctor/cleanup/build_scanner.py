import os
from pathlib import Path

from doctor.cleanup.base import BaseScanner, is_safe_workspace_dir, SYSTEM_IGNORED_DIRS
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class BuildScanner(BaseScanner):
    name = "build"
    label = "Other build artifacts and caches (Cargo, Gradle, Maven, workspace build/dist/target directories)"
    is_safe_to_auto_clean = True

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        paths_to_check = []
        size_bytes = 0

        # 1. System caches
        home = Path.home()
        maven_repo = home / ".m2" / "repository"
        gradle_caches = home / ".gradle" / "caches"
        cargo_registry = home / ".cargo" / "registry"
        cargo_git = home / ".cargo" / "git"

        for cache_path in [maven_repo, gradle_caches, cargo_registry, cargo_git]:
            if cache_path.exists():
                sz = cleanup_service.measure_path(cache_path)
                if sz > 0:
                    paths_to_check.append(str(cache_path))
                    size_bytes += sz

        # 2. Local workspace build directories
        cwd = Path.cwd()
        if is_safe_workspace_dir(cwd):
            try:
                for root, dirs, files in os.walk(cwd, followlinks=False):
                    # Prune system, package (like node_modules), and hidden directories
                    dirs[:] = [
                        d for d in dirs
                        if d not in SYSTEM_IGNORED_DIRS and not d.startswith(".")
                    ]
                    for d in list(dirs):
                        if d in ("build", "dist", "target", ".gradle", "out"):
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
        return freed
