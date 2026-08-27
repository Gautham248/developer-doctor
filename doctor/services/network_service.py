"""Shared, testable interface to network connectivity data.

Keeps all raw system calls (psutil, socket, urllib) in one place so
the plugin itself stays free of side-effects and easy to unit-test.
"""

from __future__ import annotations

import platform
import socket
import subprocess
import urllib.request
from dataclasses import dataclass, field

import psutil

from doctor.capabilities import Capability
from doctor.services.base import BaseService

# Hosts probed when checking general internet reachability.
PROBE_HOSTS: list[tuple[str, int]] = [
    ("8.8.8.8", 53),       # Google Public DNS
    ("1.1.1.1", 53),       # Cloudflare DNS
    ("208.67.222.222", 53), # OpenDNS
]

# Hostname used to verify that DNS resolution itself is working.
DNS_PROBE_HOST = "dns.google"

# HTTP URL used as a last-resort connectivity probe (captive-portal check).
HTTP_PROBE_URL = "http://connectivitycheck.gstatic.com/generate_204"
HTTP_PROBE_TIMEOUT = 5


@dataclass
class InterfaceInfo:
    """Summary of a single network interface."""

    name: str
    is_up: bool
    addresses: list[str] = field(default_factory=list)
    is_wireless: bool = False


@dataclass
class ConnectivityResult:
    """Aggregated result of all connectivity probes."""

    interfaces: list[InterfaceInfo]
    dns_ok: bool
    internet_ok: bool
    captive_portal_detected: bool
    reachable_host: str | None  # which PROBE_HOST succeeded first, or None
    dns_latency_ms: float | None  # rough socket-connect time in ms, or None


class NetworkService(BaseService):
    """Shared, testable interface to network interface and connectivity data."""

    required_capability = Capability.NETWORK_SOCKETS

    # ------------------------------------------------------------------
    # Interface enumeration
    # ------------------------------------------------------------------

    def get_interfaces(self) -> list[InterfaceInfo]:
        """Return info for every non-loopback interface psutil can see."""
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except Exception:
            return []

        infos: list[InterfaceInfo] = []
        for name, stat in stats.items():
            if name.startswith("lo"):  # skip loopback
                continue
            ips = [
                a.address
                for a in addrs.get(name, [])
                if a.family in (socket.AF_INET, socket.AF_INET6)
                and not a.address.startswith("fe80")  # skip link-local IPv6
            ]
            infos.append(
                InterfaceInfo(
                    name=name,
                    is_up=stat.isup,
                    addresses=ips,
                    is_wireless=self._is_wireless(name),
                )
            )
        return infos

    def _is_wireless(self, iface_name: str) -> bool:
        """Best-effort wireless detection; never raises."""
        try:
            system = platform.system()
            if system == "Darwin":
                result = subprocess.run(
                    ["networksetup", "-getinfo", iface_name],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                # 'Wi-Fi' appears in the human-readable name returned by networksetup
                return "wi-fi" in result.stdout.lower() or iface_name.lower().startswith("en0")
            elif system == "Linux":
                import os
                return os.path.exists(f"/sys/class/net/{iface_name}/wireless")
        except Exception:
            pass
        # Fallback: common interface name patterns
        lower = iface_name.lower()
        return lower.startswith(("wlan", "wlp", "wifi", "en0"))

    # ------------------------------------------------------------------
    # DNS resolution
    # ------------------------------------------------------------------

    def check_dns(self, hostname: str = DNS_PROBE_HOST) -> tuple[bool, float | None]:
        """Try to resolve *hostname* and return (success, latency_ms).

        Latency is the wall-clock time for a raw socket connect to port 53
        on the resolved address — a rough but dependency-free proxy for
        'how snappy is DNS right now?'
        """
        import time

        try:
            start = time.monotonic()
            socket.getaddrinfo(hostname, None, socket.AF_INET)
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            return True, latency_ms
        except OSError:
            return False, None

    # ------------------------------------------------------------------
    # Internet reachability
    # ------------------------------------------------------------------

    def check_internet(
        self,
        probe_hosts: list[tuple[str, int]] = PROBE_HOSTS,
        timeout: float = 3.0,
    ) -> tuple[bool, str | None]:
        """Attempt a TCP connect to each probe host; return (success, first_host_that_worked).

        Uses raw socket connects rather than ICMP so no special privileges
        are needed and the check works through most corporate firewalls.
        """
        for host, port in probe_hosts:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True, host
            except OSError:
                continue
        return False, None

    # ------------------------------------------------------------------
    # Captive portal detection
    # ------------------------------------------------------------------

    def check_captive_portal(
        self,
        url: str = HTTP_PROBE_URL,
        timeout: float = HTTP_PROBE_TIMEOUT,
    ) -> bool:
        """Return True if we suspect a captive portal is intercepting traffic.

        The probe URL is designed to return HTTP 204 (no content) when the
        device has genuine internet access. Any other response — especially a
        redirect to a login page — indicates a captive portal.
        """
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                return resp.status != 204
        except Exception:
            # Couldn't reach it at all — might be offline, not necessarily a portal.
            return False

    # ------------------------------------------------------------------
    # Convenience aggregate
    # ------------------------------------------------------------------

    def get_connectivity(self) -> ConnectivityResult:
        """Run all checks and return a single aggregated result."""
        interfaces = self.get_interfaces()
        dns_ok, dns_latency = self.check_dns()
        internet_ok, reachable_host = self.check_internet()
        captive_portal = (
            self.check_captive_portal() if internet_ok else False
        )
        return ConnectivityResult(
            interfaces=interfaces,
            dns_ok=dns_ok,
            internet_ok=internet_ok,
            captive_portal_detected=captive_portal,
            reachable_host=reachable_host,
            dns_latency_ms=dns_latency,
        )
