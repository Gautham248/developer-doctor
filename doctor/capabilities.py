from enum import Enum


class Capability(str, Enum):
    """Capabilities a plugin may declare it needs (§11.2).

    The core decides at runtime whether declared capabilities are
    granted (§11.1). Currently enforced ONLY at the shared-services
    boundary (§12): DoctorPlugin.use_service() refuses to hand out a
    service instance unless its required capability was declared.

    Known gap, stated plainly: plugins that call subprocess/psutil
    directly instead of going through a service are NOT checked. True
    sandboxing of arbitrary system calls is deferred to future
    hardening work (§11.3) — this is declaration + partial enforcement,
    not a security boundary yet.
    """

    PROCESS_INSPECTION = "process_inspection"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK_SOCKETS = "network_sockets"
    PACKAGE_MANAGERS = "package_managers"
    SHELL_COMMANDS = "shell_commands"
    SYSTEM_PROFILER = "system_profiler"
    BATTERY_INFORMATION = "battery_information"
    DOCKER_DAEMON_ACCESS = "docker_daemon_access"
    KUBERNETES_API_ACCESS = "kubernetes_api_access"
    GIT_REPOSITORY_ACCESS = "git_repository_access"
    FILESYSTEM_SCAN = "filesystem_scan"
    FILESYSTEM_CLEAN = "filesystem_clean"


class CapabilityError(Exception):
    """Raised when a plugin tries to use a shared service without having
    declared the capability that service requires."""