import json
import os
import shutil
import subprocess
from pathlib import Path

from doctor.capabilities import Capability
from doctor.services.base import BaseService

DOCKER_TIMEOUT_SECONDS = 5


class CleanupService(BaseService):
    """Shared service for measuring file/directory sizes and querying external systems (e.g. Docker, Homebrew)."""

    required_capability = Capability.FILESYSTEM_SCAN

    def measure_path(self, path: Path) -> int:
        """Measure the size of a file or directory in bytes. Ignores errors (e.g. permission/missing)."""
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

    def glob_size(self, base_dir: Path, pattern: str) -> int:
        """Expand a glob pattern in base_dir and sum the size of all matching paths."""
        if not base_dir.exists():
            return 0

        total_size = 0
        try:
            for p in base_dir.glob(pattern):
                total_size += self.measure_path(p)
        except OSError:
            pass
        return total_size

    def is_docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def docker_disk_usage(self) -> dict[str, int]:
        """Query docker system df to get reclaimable size of images, containers, volumes, and build cache.

        Returns a dictionary mapping category key to reclaimable size in bytes.
        """
        results = {
            "images": 0,
            "containers": 0,
            "volumes": 0,
            "build_cache": 0,
        }
        if not self.is_docker_available():
            return results

        try:
            # docker system df --format "{{json .}}" prints one JSON line per category.
            # E.g. {"Type":"Images","TotalCount":5,"Active":2,"Size":"1.5GB","Reclaimable":"1.2GB (80%)"}
            # We look at the 'Reclaimable' field, parsing it.
            res = subprocess.run(
                ["docker", "system", "df", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT_SECONDS,
            )
            if res.returncode != 0:
                return results

            for line in res.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    dtype = data.get("Type", "").lower()
                    reclaimable_str = data.get("Reclaimable", "0B")
                    # Reclaimable can be "1.2GB (80%)" or "0B" or "500MB"
                    mem_part = reclaimable_str.split()[0]
                    bytes_val = self._parse_size_string(mem_part)
                    if "image" in dtype:
                        results["images"] = bytes_val
                    elif "container" in dtype:
                        results["containers"] = bytes_val
                    elif "volume" in dtype:
                        results["volumes"] = bytes_val
                    elif "build" in dtype or "cache" in dtype:
                        results["build_cache"] = bytes_val
                except (json.JSONDecodeError, KeyError, IndexError, ValueError):
                    continue
        except (subprocess.SubprocessError, OSError):
            pass

        return results

    def get_brew_cache_path(self) -> Path | None:
        """Run `brew --cache` to find the Homebrew cache location."""
        if shutil.which("brew") is None:
            return None
        try:
            res = subprocess.run(
                ["brew", "--cache"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                path_str = res.stdout.strip()
                if path_str:
                    return Path(path_str)
        except (subprocess.SubprocessError, OSError):
            pass
        return None

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
