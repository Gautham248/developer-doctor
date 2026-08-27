"""Network connectivity plugin.

Checks:
  - Active network interfaces (WiFi, Ethernet, VPN, etc.)
  - DNS resolution health and latency
  - Raw internet reachability (TCP probes)
  - Captive portal detection (HTTP 204 probe)

Scoring:
  - No internet at all           → FAIL  (-15)
  - DNS broken but IP reachable  → WARN  (-5)
  - Captive portal detected      → WARN  (-5)
  - No active interfaces         → FAIL  (-15)
  - Everything fine              → PASS  (0)
"""

from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.network_service import NetworkService

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class NetworkPlugin(DoctorPlugin):
    name = "network"
    description = (
        "Checks internet connectivity: interfaces (WiFi/Ethernet/VPN), "
        "DNS resolution, and reachability."
    )
    capabilities = [Capability.NETWORK_SOCKETS]

    def run(self) -> PluginResult:
        try:
            svc = self.use_service(NetworkService)
            conn = svc.get_connectivity()

            findings: list[Finding] = []
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            # ── Interfaces ──────────────────────────────────────────────
            active = [i for i in conn.interfaces if i.is_up and i.addresses]
            wireless = [i for i in active if i.is_wireless]
            wired = [i for i in active if not i.is_wireless]

            if not active:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
                findings.append(Finding(summary="No active network interfaces detected"))
                recommendations.append(
                    "No network interfaces are up with an IP address. "
                    "Check cable connections, WiFi association, or VPN status."
                )
            else:
                for iface in wireless:
                    addr_str = ", ".join(iface.addresses[:2])
                    findings.append(
                        Finding(summary=f"WiFi: {iface.name} — {addr_str}")
                    )
                for iface in wired:
                    addr_str = ", ".join(iface.addresses[:2])
                    label = "VPN" if _looks_like_vpn(iface.name) else "Ethernet"
                    findings.append(
                        Finding(summary=f"{label}: {iface.name} — {addr_str}")
                    )

            # ── Internet reachability ────────────────────────────────────
            if conn.internet_ok:
                findings.append(
                    Finding(
                        summary=f"Internet: reachable (via {conn.reachable_host})"
                    )
                )
            else:
                if status != Status.FAIL:
                    status = Status.FAIL
                    score_delta = FAIL_SCORE_DELTA
                findings.append(Finding(summary="Internet: unreachable"))
                recommendations.append(
                    "Could not reach any external hosts. "
                    "Check your network connection or firewall settings."
                )

            # ── DNS ──────────────────────────────────────────────────────
            if conn.dns_ok:
                latency_str = (
                    f" ({conn.dns_latency_ms:.0f} ms)"
                    if conn.dns_latency_ms is not None
                    else ""
                )
                findings.append(Finding(summary=f"DNS: resolving{latency_str}"))
            else:
                if status == Status.PASS:
                    status = Status.WARN
                    score_delta = WARN_SCORE_DELTA
                findings.append(Finding(summary="DNS: resolution failed"))
                recommendations.append(
                    "DNS resolution failed. Devices can still reach IPs directly, "
                    "but most developer tools (git, npm, pip, Docker pulls) will break. "
                    "Try flushing the DNS cache or switching to a public resolver like 8.8.8.8."
                )

            # ── Captive portal ───────────────────────────────────────────
            if conn.captive_portal_detected:
                if status == Status.PASS:
                    status = Status.WARN
                    score_delta = max(score_delta, WARN_SCORE_DELTA)
                findings.append(
                    Finding(
                        summary="Captive portal detected",
                        detail="The connectivity probe did not receive the expected HTTP 204 "
                        "response — a login/redirect page is likely intercepting traffic.",
                    )
                )
                recommendations.append(
                    "A captive portal appears to be active (e.g. hotel/airport/corporate WiFi). "
                    "Open a browser and complete the login before running builds or pulling packages."
                )

            # ── Metadata ─────────────────────────────────────────────────
            metadata = {
                "interfaces": [
                    {
                        "name": i.name,
                        "is_up": i.is_up,
                        "is_wireless": i.is_wireless,
                        "addresses": i.addresses,
                    }
                    for i in conn.interfaces
                ],
                "internet_ok": conn.internet_ok,
                "dns_ok": conn.dns_ok,
                "dns_latency_ms": conn.dns_latency_ms,
                "captive_portal": conn.captive_portal_detected,
            }

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata=metadata,
            )

        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not check network connectivity", detail=str(e))],
            )


def _looks_like_vpn(iface_name: str) -> bool:
    """Heuristic: interface names that typically indicate a VPN tunnel."""
    lower = iface_name.lower()
    return any(lower.startswith(prefix) for prefix in ("utun", "tun", "tap", "ppp", "vpn"))
