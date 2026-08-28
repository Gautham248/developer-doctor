"""Browser tab service — AppleScript-based tab enumeration and closing.

Supports Chrome, Brave, Arc (Chromium-based), and Safari on macOS.
On non-macOS platforms all methods return empty results gracefully.

Key design constraint (confirmed by testing):
  Renderer process PID → tab URL correlation is NOT possible without enabling
  Chrome DevTools Protocol remote debugging. Instead, we list all open tabs
  via AppleScript and let the user select which to close.

Tested and confirmed working on macOS 15 / Apple Silicon:
  - list_tabs: returns title, URL, window and tab indices
  - close_tab: closes a specific tab by window/tab index
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


# Browsers whose AppleScript dictionaries are compatible with the Chromium
# tab model (title, URL, active tab index, close tab N of window M).
CHROMIUM_BROWSERS = [
    "Brave Browser",
    "Google Chrome",
    "Arc",
    "Microsoft Edge",
    "Vivaldi",
    "Opera",
]

SAFARI_BROWSERS = ["Safari"]

ALL_SUPPORTED_BROWSERS = CHROMIUM_BROWSERS + SAFARI_BROWSERS

# Renderer process name suffixes used to detect which browser is hot
RENDERER_SUFFIXES: dict[str, str] = {
    "Brave Browser Helper (Renderer)": "Brave Browser",
    "Google Chrome Helper (Renderer)": "Google Chrome",
    "Arc Helper (Renderer)": "Arc",
    "Microsoft Edge Helper (Renderer)": "Microsoft Edge",
    "Vivaldi Helper (Renderer)": "Vivaldi",
    "com.apple.WebKit.WebContent": "Safari",
    "Safari Web Content": "Safari",
}


@dataclass
class BrowserTab:
    browser: str        # e.g. "Brave Browser"
    window_index: int   # 1-based
    tab_index: int      # 1-based
    title: str
    url: str
    is_active: bool     # True if this is the currently focused tab


class BrowserTabService:
    """AppleScript-based browser tab operations (macOS only)."""

    def is_supported(self) -> bool:
        return platform.system() == "Darwin"

    def list_tabs(self, browser: str) -> list[BrowserTab]:
        """List all open tabs in a running browser application.

        Returns an empty list (no exception) if the browser is not running
        or AppleScript fails for any reason.
        """
        if not self.is_supported():
            return []

        if browser in CHROMIUM_BROWSERS:
            return self._list_chromium_tabs(browser)
        elif browser in SAFARI_BROWSERS:
            return self._list_safari_tabs(browser)
        return []

    def close_tab(self, tab: BrowserTab) -> bool:
        """Close a specific tab by its window and tab index.

        Returns True on success, False on any failure.
        """
        if not self.is_supported():
            return False

        if tab.browser in CHROMIUM_BROWSERS:
            script = (
                f'tell application "{tab.browser}" '
                f'to close tab {tab.tab_index} of window {tab.window_index}'
            )
        elif tab.browser in SAFARI_BROWSERS:
            script = (
                f'tell application "{tab.browser}" '
                f'to close tab {tab.tab_index} of window {tab.window_index}'
            )
        else:
            return False

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            return False

    def get_hot_browser_tabs(
        self, hot_process_names: list[str]
    ) -> dict[str, list[BrowserTab]]:
        """Given a list of hot process names, return tabs from implicated browsers.

        Detects which browsers have running renderer processes in the hot list,
        then calls list_tabs() for each. Returns {browser_name: [tabs...]}.
        """
        if not self.is_supported():
            return {}

        implicated: set[str] = set()
        for proc_name in hot_process_names:
            for suffix, browser in RENDERER_SUFFIXES.items():
                if suffix in proc_name or proc_name == suffix:
                    implicated.add(browser)
                    break

        result: dict[str, list[BrowserTab]] = {}
        for browser in implicated:
            tabs = self.list_tabs(browser)
            if tabs:
                result[browser] = tabs
        return result

    # -----------------------------------------------------------------------
    # Internal AppleScript runners
    # -----------------------------------------------------------------------

    def _list_chromium_tabs(self, browser: str) -> list[BrowserTab]:
        """Enumerate tabs via Chromium's AppleScript dictionary."""
        script = f"""
tell application "{browser}"
    if not running then return ""
    set output to ""
    set winIdx to 0
    repeat with w in windows
        set winIdx to winIdx + 1
        set activeTabIdx to active tab index of w
        set tabIdx to 0
        repeat with t in tabs of w
            set tabIdx to tabIdx + 1
            set isActive to (tabIdx = activeTabIdx)
            set output to output & winIdx & "|||" & tabIdx & "|||" & (title of t) & "|||" & (URL of t) & "|||" & isActive & "\\n"
        end repeat
    end repeat
    return output
end tell
"""
        return self._parse_tab_output(script, browser)

    def _list_safari_tabs(self, browser: str) -> list[BrowserTab]:
        """Enumerate tabs via Safari's AppleScript dictionary."""
        script = f"""
tell application "{browser}"
    if not running then return ""
    set output to ""
    set winIdx to 0
    repeat with w in windows
        set winIdx to winIdx + 1
        set tabIdx to 0
        try
            set currentTab to current tab of w
        on error
            set currentTab to missing value
        end try
        repeat with t in tabs of w
            set tabIdx to tabIdx + 1
            set isActive to (t = currentTab)
            set output to output & winIdx & "|||" & tabIdx & "|||" & (name of t) & "|||" & (URL of t) & "|||" & isActive & "\\n"
        end repeat
    end repeat
    return output
end tell
"""
        return self._parse_tab_output(script, browser)

    @staticmethod
    def _parse_tab_output(script: str, browser: str) -> list[BrowserTab]:
        """Run an AppleScript and parse the pipe-delimited tab output."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []

            tabs: list[BrowserTab] = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("|||")
                if len(parts) != 5:
                    continue
                win_idx, tab_idx, title, url, is_active_raw = parts
                try:
                    tabs.append(
                        BrowserTab(
                            browser=browser,
                            window_index=int(win_idx),
                            tab_index=int(tab_idx),
                            title=title.strip(),
                            url=url.strip(),
                            is_active=is_active_raw.strip().lower() == "true",
                        )
                    )
                except ValueError:
                    continue
            return tabs
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            return []
