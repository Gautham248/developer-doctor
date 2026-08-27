from abc import ABC, abstractmethod

from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


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
