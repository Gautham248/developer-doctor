import os
import shutil
import subprocess
from pathlib import Path

from doctor.capabilities import Capability
from doctor.services.base import BaseService

DOCKER_TIMEOUT_SECONDS = 15


class CleanService(BaseService):
    """Shared service for performing deletions and pruning resources."""

    required_capability = Capability.FILESYSTEM_CLEAN

    def remove_path(self, path: Path) -> int:
        """Measure size and remove a file or directory. Returns bytes freed."""
        if not path.exists():
            return 0

        # Measure size before deletion
        size = self._measure_path(path)

        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            return size
        except OSError:
            return 0

    def remove_glob(self, base_dir: Path, pattern: str) -> int:
        """Expand a glob pattern in base_dir and remove all matching paths. Returns total bytes freed."""
        if not base_dir.exists():
            return 0

        total_freed = 0
        try:
            for p in base_dir.glob(pattern):
                total_freed += self.remove_path(p)
        except OSError:
            pass
        return total_freed

    def docker_prune_images(self) -> int:
        """Prune all unused Docker images. Returns bytes freed."""
        return self._run_docker_prune(["docker", "image", "prune", "-a", "-f"])

    def docker_prune_containers(self) -> int:
        """Prune stopped Docker containers. Returns bytes freed."""
        return self._run_docker_prune(["docker", "container", "prune", "-f"])

    def docker_prune_volumes(self) -> int:
        """Prune unused Docker volumes. Returns bytes freed."""
        return self._run_docker_prune(["docker", "volume", "prune", "-f"])

    def docker_prune_build_cache(self) -> int:
        """Prune all unused Docker build cache. Returns bytes freed."""
        return self._run_docker_prune(["docker", "builder", "prune", "-a", "-f"])

    def brew_cleanup(self) -> int:
        """Run `brew cleanup`."""
        if shutil.which("brew") is None:
            return 0
        try:
            subprocess.run(["brew", "cleanup"], capture_output=True, timeout=30)
        except (subprocess.SubprocessError, OSError):
            pass
        return 0

    def uv_cache_clean(self) -> int:
        """Run `uv cache clean`."""
        if shutil.which("uv") is None:
            return 0
        try:
            subprocess.run(["uv", "cache", "clean"], capture_output=True, timeout=10)
        except (subprocess.SubprocessError, OSError):
            pass
        return 0

    def pip_cache_purge(self) -> int:
        """Run `pip cache purge`."""
        if shutil.which("pip") is None:
            return 0
        try:
            subprocess.run(["pip", "cache", "purge"], capture_output=True, timeout=10)
        except (subprocess.SubprocessError, OSError):
            pass
        return 0

    def npm_cache_clean(self) -> int:
        """Run `npm cache clean --force`."""
        if shutil.which("npm") is None:
            return 0
        try:
            subprocess.run(["npm", "cache", "clean", "--force"], capture_output=True, timeout=15)
        except (subprocess.SubprocessError, OSError):
            pass
        return 0

    def _run_docker_prune(self, command: list[str]) -> int:
        if shutil.which("docker") is None:
            return 0
        try:
            res = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT_SECONDS,
            )
            if res.returncode == 0:
                # Docker prune output usually ends with "Total reclaimed space: X.YMB" or "Total reclaimed space: 0B"
                for line in res.stdout.splitlines():
                    if "total reclaimed space:" in line.lower():
                        parts = line.split(":")
                        if len(parts) >= 2:
                            size_str = parts[1].strip()
                            return self._parse_size_string(size_str)
        except (subprocess.SubprocessError, OSError):
            pass
        return 0

    def _measure_path(self, path: Path) -> int:
        """Measure size of file or directory in bytes."""
        if not path.exists():
            return 0
        if path.is_file() and not path.is_symlink():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total_size = 0
        try:
            for root, dirs, files in os.walk(path, followlinks=False):
                for f in files:
                    fp = Path(root) / f
                    try:
                        if not fp.is_symlink():
                            total_size += fp.stat().st_size
                    except OSError:
                        continue
        except OSError:
            pass
        return total_size

    def _parse_size_string(self, value: str) -> int:
        """Parse a size string (e.g. '1.2GB', '512MB', '10.5kB', '0B') into bytes."""
        units = [
            ("tib", 1024**4),
            ("gib", 1024**3),
            ("mib", 1024**2),
            ("kib", 1024),
            ("tb", 1000**4),
            ("gb", 1000**3),
            ("mb", 1000**2),
            ("kb", 1000),
            ("b", 1),
        ]
        val_lower = value.strip().lower()
        for suffix, multiplier in units:
            if val_lower.endswith(suffix):
                number = val_lower[:-len(suffix)].strip()
                try:
                    return int(float(number) * multiplier)
                except ValueError:
                    return 0
        try:
            return int(float(val_lower))
        except ValueError:
            return 0
