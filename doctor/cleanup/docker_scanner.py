from doctor.cleanup.base import BaseScanner
from doctor.models import CleanupCategory
from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


class DockerScanner(BaseScanner):
    name = "docker"
    label = "Docker resources (images, containers, volumes, build cache)"
    is_safe_to_auto_clean = True

    def is_supported(self) -> bool:
        # Check if docker is installed/available
        import shutil
        return shutil.which("docker") is not None

    def scan(self, cleanup_service: CleanupService) -> CleanupCategory:
        usage = cleanup_service.docker_disk_usage()
        total_size = sum(usage.values())

        # Build paths or description items for informational display
        paths = []
        if usage["images"] > 0:
            paths.append(f"Dangling images: {usage['images'] / (1024**2):.1f} MB")
        if usage["containers"] > 0:
            paths.append(f"Stopped containers: {usage['containers'] / (1024**2):.1f} MB")
        if usage["volumes"] > 0:
            paths.append(f"Unused volumes: {usage['volumes'] / (1024**2):.1f} MB")
        if usage["build_cache"] > 0:
            paths.append(f"Build cache: {usage['build_cache'] / (1024**2):.1f} MB")

        return CleanupCategory(
            name=self.name,
            label=self.label,
            size_bytes=total_size,
            paths=paths,
            is_safe_to_auto_clean=self.is_safe_to_auto_clean,
        )

    def clean(self, clean_service: CleanService, category_detail: CleanupCategory) -> int:
        freed = 0
        freed += clean_service.docker_prune_containers()
        freed += clean_service.docker_prune_images()
        freed += clean_service.docker_prune_build_cache()
        freed += clean_service.docker_prune_volumes()
        return freed
