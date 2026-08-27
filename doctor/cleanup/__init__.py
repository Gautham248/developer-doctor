from doctor.cleanup.base import BaseScanner
from doctor.cleanup.docker_scanner import DockerScanner
from doctor.cleanup.xcode_scanner import XcodeScanner
from doctor.cleanup.python_scanner import PythonScanner
from doctor.cleanup.node_scanner import NodeScanner
from doctor.cleanup.macos_scanner import MacOSScanner
from doctor.cleanup.build_scanner import BuildScanner

ALL_SCANNERS: list[type[BaseScanner]] = [
    DockerScanner,
    XcodeScanner,
    PythonScanner,
    NodeScanner,
    MacOSScanner,
    BuildScanner,
]

__all__ = [
    "BaseScanner",
    "DockerScanner",
    "XcodeScanner",
    "PythonScanner",
    "NodeScanner",
    "MacOSScanner",
    "BuildScanner",
    "ALL_SCANNERS",
]
