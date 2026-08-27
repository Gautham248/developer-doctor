import sys
from pathlib import Path

from doctor.cleanup.base import BaseScanner
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class MacOSScanner(BaseScanner):
    name = "macos"
    label = "macOS caches (Homebrew cache, Trash bin)"
    is_safe_to_auto_clean = True

    def is_supported(self) -> bool:
        return sys.platform == "darwin"

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        paths_to_check = []
        size_bytes = 0

        home = Path.home()
        trash_path = home / ".Trash"
        if trash_path.exists():
            sz = cleanup_service.measure_path(trash_path)
            if sz > 0:
                paths_to_check.append(str(trash_path))
                size_bytes += sz

        brew_cache = cleanup_service.get_brew_cache_path()
        if brew_cache and brew_cache.exists():
            sz = cleanup_service.measure_path(brew_cache)
            if sz > 0:
                paths_to_check.append(str(brew_cache))
                size_bytes += sz

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

        # Run brew cleanup CLI command
        clean_service.brew_cleanup()
        return freed
