import sys
from pathlib import Path

from doctor.cleanup.base import BaseScanner
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class XcodeScanner(BaseScanner):
    name = "xcode"
    label = "Xcode build caches (DerivedData, Archives)"
    is_safe_to_auto_clean = True

    def is_supported(self) -> bool:
        return sys.platform == "darwin"

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        home = Path.home()
        derived_data_path = home / "Library/Developer/Xcode/DerivedData"
        archives_path = home / "Library/Developer/Xcode/Archives"

        paths_to_check = []
        size_bytes = 0

        if derived_data_path.exists():
            dd_size = cleanup_service.measure_path(derived_data_path)
            if dd_size > 0:
                paths_to_check.append(str(derived_data_path))
                size_bytes += dd_size

        if archives_path.exists():
            arc_size = cleanup_service.measure_path(archives_path)
            if arc_size > 0:
                paths_to_check.append(str(archives_path))
                size_bytes += arc_size

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
