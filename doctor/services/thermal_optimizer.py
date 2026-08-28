"""Thermal optimizer service.

Scans running processes, classifies them into optimization categories,
and provides methods to gracefully close/terminate them.

Process categories and their actions:
  HIGH_CPU_USER_APP  — user-owned high-CPU app → graceful quit or SIGTERM
  HOT_BROWSER        — renderer processes → present tab list for user to choose
  AUTO_UPDATER       — background updater daemons → SIGTERM
  ANALYTICS_DAEMON   — crash reporters, telemetry agents → SIGTERM
  BACKGROUND_FETCH   — photo analysis, URL session → SIGTERM
  INDEXING_DAEMON    — Spotlight mds/mdworker → SUGGESTION_ONLY
  CLOUD_SYNC         — iCloud bird/cloudd, Dropbox etc. → SUGGESTION_ONLY
  UNUSED_GUI_APP     — GUI app open but idle → graceful quit

SUGGESTION_ONLY items are NEVER auto-acted on; we only print guidance.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch

import psutil

from doctor.services.browser_tab_service import BrowserTabService, BrowserTab
from doctor.services.thermal_service import ThermalProcess, KillSafety


# ---------------------------------------------------------------------------
# Enums & data types
# ---------------------------------------------------------------------------

class OptimizationCategory(str, Enum):
    HIGH_CPU_USER_APP = "high_cpu_user_app"
    HOT_BROWSER = "hot_browser"
    AUTO_UPDATER = "auto_updater"
    ANALYTICS_DAEMON = "analytics_daemon"
    BACKGROUND_FETCH = "background_fetch"
    INDEXING_DAEMON = "indexing_daemon"
    CLOUD_SYNC = "cloud_sync"
    UNUSED_GUI_APP = "unused_gui_app"


class OptimizationAction(str, Enum):
    QUIT_APP = "quit_app"          # osascript → SIGTERM fallback
    SIGTERM_PROCESS = "sigterm"    # SIGTERM → SIGKILL after 3s
    CLOSE_TAB = "close_tab"        # via BrowserTabService
    SUGGESTION_ONLY = "suggestion" # never auto-executed


@dataclass
class OptimizationTarget:
    display_name: str
    category: OptimizationCategory
    cpu_percent: float
    action: OptimizationAction
    reason: str
    pid: int | None = None         # set for process-level actions
    app_name: str | None = None    # set for app-quit actions (osascript name)
    browser_tabs: list[BrowserTab] = field(default_factory=list)  # set for HOT_BROWSER
    suggestion_text: str = ""      # shown for SUGGESTION_ONLY items


# ---------------------------------------------------------------------------
# Pattern sets for process classification
# ---------------------------------------------------------------------------

# --- AUTO_UPDATER patterns (fnmatch style) ---
_UPDATER_PATTERNS = [
    "*Update*", "*Updater*", "*update*",
    "SoftwareUpdateNotificationManager",
    "com.apple.MobileAsset*",
    "com.apple.softwareupdated",
    "SoftwareUpdate",
]

# --- ANALYTICS_DAEMON exact names ---
_ANALYTICS_NAMES = frozenset({
    "DiagnosticReporter",
    "ReportCrash",
    "com.apple.UsageTrackingAgent",
    "CrashReporter",
    "SubmitDiagInfo",
    "osinstallersetupd",
})

# --- BACKGROUND_FETCH exact names ---
_BACKGROUND_FETCH_NAMES = frozenset({
    "nsurlsessiond",
    "CloudPhotoLibraryAgent",
    "photoanalysisd",
    "photolibraryd",
    "mediaanalysisd",
    "com.apple.photoanalysisd",
    "mobileassetd",
    "AssetCacheLocatorService",
})

# --- INDEXING_DAEMON prefixes / exact names ---
_INDEXING_NAMES = frozenset({
    "mds",
    "mds_stores",
})
_INDEXING_PREFIXES = ("mdworker",)

# --- CLOUD_SYNC patterns ---
_CLOUD_SYNC_PATTERNS = [
    "Dropbox*", "OneDrive*", "GoogleDrive*", "Google Drive*",
    "Backup and Sync*", "bird", "cloudd", "com.apple.iCloudDrive*",
    "GARCON",  # Google Drive file stream
    "FinderSyncExtension",  # iCloud Drive sync in Finder
]

# --- HOT_BROWSER renderer process name fragments ---
_RENDERER_FRAGMENTS = [
    "(Renderer)",
    "Web Content",
    "WebKit.WebContent",
]

# CPU% above which a user-owned app is considered "high CPU"
_HIGH_CPU_THRESHOLD = 20.0

# Mac app bundle names that map from process name
# (used to build the osascript quit call)
_WELL_KNOWN_APPS: dict[str, str] = {
    "Xcode": "Xcode",
    "Simulator": "Simulator",
    "Instruments": "Instruments",
    "Finder": "Finder",
    "Mail": "Mail",
    "Calendar": "Calendar",
    "Messages": "Messages",
    "FaceTime": "FaceTime",
    "Photos": "Photos",
    "Music": "Music",
    "Slack": "Slack",
    "Zoom": "zoom.us",
    "zoom.us": "zoom.us",
    "Teams": "Microsoft Teams",
    "Notion": "Notion",
    "Figma": "Figma",
    "Sketch": "Sketch",
    "Terminal": "Terminal",
    "iTerm2": "iTerm2",
    "Spotify": "Spotify",
    "Activity Monitor": "Activity Monitor",
    "Preview": "Preview",
}


# ---------------------------------------------------------------------------
# ThermalOptimizer
# ---------------------------------------------------------------------------

class ThermalOptimizer:
    """Identifies non-essential/unused processes and provides safe close actions."""

    def __init__(self) -> None:
        self._browser_service = BrowserTabService()
        self._current_user = self._get_current_user()

    # -- Public API ---------------------------------------------------------

    def scan_optimizations(
        self,
        thermal_processes: list[ThermalProcess],
        include_browser_tabs: bool = True,
    ) -> list[OptimizationTarget]:
        """Scan the process list and return a prioritized list of optimization targets.

        Targets are sorted by estimated impact (cpu_percent descending).
        SUGGESTION_ONLY targets always appear at the end regardless of CPU%.
        """
        actionable: list[OptimizationTarget] = []
        suggestions: list[OptimizationTarget] = []
        seen_pids: set[int] = set()

        # Collect renderer process names for browser tab lookup
        renderer_names: list[str] = []

        for proc in thermal_processes:
            if proc.pid in seen_pids:
                continue
            seen_pids.add(proc.pid)

            target = self._classify(proc)
            if target is None:
                continue

            if target.action == OptimizationAction.SUGGESTION_ONLY:
                suggestions.append(target)
            elif target.action == OptimizationAction.CLOSE_TAB:
                renderer_names.append(proc.name)
                actionable.append(target)
            else:
                actionable.append(target)

        # Enrich HOT_BROWSER targets with actual tab lists
        if include_browser_tabs and renderer_names:
            browser_tabs = self._browser_service.get_hot_browser_tabs(renderer_names)
            hot_browser_target = self._make_hot_browser_target(
                thermal_processes, browser_tabs
            )
            if hot_browser_target is not None:
                # Remove individual renderer entries and replace with one merged entry
                actionable = [t for t in actionable if t.action != OptimizationAction.CLOSE_TAB]
                actionable.append(hot_browser_target)

        actionable.sort(key=lambda t: t.cpu_percent, reverse=True)
        suggestions.sort(key=lambda t: t.cpu_percent, reverse=True)
        return actionable + suggestions

    def quit_app_gracefully(self, app_name: str) -> bool:
        """Send a graceful quit to a macOS application via osascript.

        Falls back to sending SIGTERM to processes with that name.
        """
        if platform.system() != "Darwin":
            return self._sigterm_by_name(app_name)

        try:
            result = subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to quit'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            pass
        # Fallback: SIGTERM any processes with this name
        return self._sigterm_by_name(app_name)

    def terminate_process(self, pid: int, force: bool = False) -> bool:
        """Send SIGTERM to a process. If force=True and it survives 3s, send SIGKILL."""
        try:
            proc = psutil.Process(pid)
            proc.send_signal(signal.SIGTERM)
            if force:
                time.sleep(3)
                try:
                    if proc.is_running():
                        proc.send_signal(signal.SIGKILL)
                except psutil.NoSuchProcess:
                    pass
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, OSError):
            return False

    # -- Classification helpers --------------------------------------------

    def _classify(self, proc: ThermalProcess) -> OptimizationTarget | None:
        """Map a ThermalProcess to an OptimizationTarget, or None if not categorized."""
        name = proc.name

        # Never suggest touching UNSAFE processes
        if proc.kill_safety == KillSafety.UNSAFE:
            return None

        # INDEXING_DAEMON
        if name in _INDEXING_NAMES or any(name.startswith(p) for p in _INDEXING_PREFIXES):
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.INDEXING_DAEMON,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.SUGGESTION_ONLY,
                reason="Spotlight indexing daemon",
                pid=proc.pid,
                suggestion_text=(
                    "Run `sudo mdutil -a -i off` to pause Spotlight indexing "
                    "(re-enable with `sudo mdutil -a -i on`)."
                ),
            )

        # CLOUD_SYNC
        if self._matches_any(name, _CLOUD_SYNC_PATTERNS):
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.CLOUD_SYNC,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.SUGGESTION_ONLY,
                reason="Cloud sync daemon — pausing may risk data loss",
                pid=proc.pid,
                suggestion_text=(
                    f"Pause '{name}' manually via its menu bar icon or "
                    "System Settings to avoid data loss."
                ),
            )

        # HOT_BROWSER renderer
        if any(frag in name for frag in _RENDERER_FRAGMENTS):
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.HOT_BROWSER,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.CLOSE_TAB,
                reason="Browser renderer process",
                pid=proc.pid,
            )

        # ANALYTICS_DAEMON
        if name in _ANALYTICS_NAMES:
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.ANALYTICS_DAEMON,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Crash reporter / analytics daemon",
                pid=proc.pid,
            )

        # BACKGROUND_FETCH
        if name in _BACKGROUND_FETCH_NAMES:
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.BACKGROUND_FETCH,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Background indexing / fetch daemon",
                pid=proc.pid,
            )

        # AUTO_UPDATER
        if self._matches_any(name, _UPDATER_PATTERNS):
            return OptimizationTarget(
                display_name=name,
                category=OptimizationCategory.AUTO_UPDATER,
                cpu_percent=proc.cpu_percent,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Background software updater",
                pid=proc.pid,
            )

        # HIGH_CPU_USER_APP (user-owned, high CPU, known/unknown GUI app)
        if (
            proc.kill_safety == KillSafety.SAFE
            and proc.cpu_percent >= _HIGH_CPU_THRESHOLD
        ):
            app_name = _WELL_KNOWN_APPS.get(name)
            action = (
                OptimizationAction.QUIT_APP if app_name else OptimizationAction.SIGTERM_PROCESS
            )
            return OptimizationTarget(
                display_name=app_name or name,
                category=OptimizationCategory.HIGH_CPU_USER_APP,
                cpu_percent=proc.cpu_percent,
                action=action,
                reason=f"High CPU user application ({proc.cpu_percent:.0f}%)",
                pid=proc.pid,
                app_name=app_name,
            )

        return None

    def _make_hot_browser_target(
        self,
        thermal_processes: list[ThermalProcess],
        browser_tabs: dict[str, list[BrowserTab]],
    ) -> OptimizationTarget | None:
        """Merge all hot renderer processes into one HOT_BROWSER target with tabs."""
        if not browser_tabs:
            return None

        total_cpu = sum(
            p.cpu_percent
            for p in thermal_processes
            if any(frag in p.name for frag in _RENDERER_FRAGMENTS)
        )
        all_tabs: list[BrowserTab] = []
        browsers = list(browser_tabs.keys())
        for tabs in browser_tabs.values():
            all_tabs.extend(tabs)

        browser_label = ", ".join(browsers)
        return OptimizationTarget(
            display_name=f"{browser_label} (renderers)",
            category=OptimizationCategory.HOT_BROWSER,
            cpu_percent=total_cpu,
            action=OptimizationAction.CLOSE_TAB,
            reason=f"Browser renderer processes in {browser_label}",
            browser_tabs=all_tabs,
        )

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _matches_any(name: str, patterns: list[str]) -> bool:
        return any(fnmatch(name, p) for p in patterns)

    @staticmethod
    def _get_current_user() -> str:
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return ""

    def _sigterm_by_name(self, name: str) -> bool:
        """SIGTERM all processes whose name matches (fallback for non-macOS)."""
        killed = False
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info["name"] == name:
                    proc.send_signal(signal.SIGTERM)
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return killed
