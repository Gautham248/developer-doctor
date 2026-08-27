"""Tests for the Network plugin and service."""

from unittest.mock import MagicMock, patch

import pytest

from doctor.models import Status
from doctor.plugins.network import NetworkPlugin, _looks_like_vpn
from doctor.services.network_service import (
    ConnectivityResult,
    InterfaceInfo,
    NetworkService,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_conn(
    interfaces: list[InterfaceInfo] | None = None,
    dns_ok: bool = True,
    internet_ok: bool = True,
    captive_portal: bool = False,
    reachable_host: str | None = "8.8.8.8",
    dns_latency_ms: float | None = 12.3,
) -> ConnectivityResult:
    if interfaces is None:
        interfaces = [
            InterfaceInfo(name="en0", is_up=True, addresses=["192.168.1.5"], is_wireless=True)
        ]
    return ConnectivityResult(
        interfaces=interfaces,
        dns_ok=dns_ok,
        internet_ok=internet_ok,
        captive_portal_detected=captive_portal,
        reachable_host=reachable_host,
        dns_latency_ms=dns_latency_ms,
    )


# ── Plugin happy-path ─────────────────────────────────────────────────────────


def test_network_plugin_passes_when_fully_connected():
    plugin = NetworkPlugin()
    with patch.object(NetworkService, "get_connectivity", return_value=_make_conn()):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0
    summaries = [f.summary for f in result.findings]
    assert any("WiFi" in s for s in summaries)
    assert any("Internet" in s for s in summaries)
    assert any("DNS" in s for s in summaries)


# ── No active interfaces ──────────────────────────────────────────────────────


def test_network_plugin_fails_with_no_active_interfaces():
    plugin = NetworkPlugin()
    conn = _make_conn(
        interfaces=[InterfaceInfo(name="en0", is_up=False, addresses=[], is_wireless=True)],
        internet_ok=False,
        dns_ok=False,
        reachable_host=None,
        dns_latency_ms=None,
    )
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15
    summaries = [f.summary for f in result.findings]
    assert any("No active" in s for s in summaries)


# ── No internet ───────────────────────────────────────────────────────────────


def test_network_plugin_fails_when_no_internet():
    plugin = NetworkPlugin()
    conn = _make_conn(internet_ok=False, reachable_host=None)
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15
    assert any("unreachable" in f.summary for f in result.findings)
    assert result.recommendations


# ── DNS broken ────────────────────────────────────────────────────────────────


def test_network_plugin_warns_when_dns_broken():
    plugin = NetworkPlugin()
    conn = _make_conn(dns_ok=False, dns_latency_ms=None)
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5
    assert any("DNS" in f.summary and "failed" in f.summary for f in result.findings)
    assert result.recommendations


# ── Captive portal ────────────────────────────────────────────────────────────


def test_network_plugin_warns_on_captive_portal():
    plugin = NetworkPlugin()
    conn = _make_conn(captive_portal=True)
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta >= 5
    assert any("captive" in f.summary.lower() for f in result.findings)
    assert result.recommendations


# ── Multiple interface types ──────────────────────────────────────────────────


def test_network_plugin_shows_wired_interface():
    plugin = NetworkPlugin()
    ifaces = [
        InterfaceInfo(name="eth0", is_up=True, addresses=["10.0.0.5"], is_wireless=False)
    ]
    conn = _make_conn(interfaces=ifaces)
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.PASS
    assert any("Ethernet" in f.summary for f in result.findings)


def test_network_plugin_shows_vpn_interface():
    plugin = NetworkPlugin()
    ifaces = [
        InterfaceInfo(name="utun3", is_up=True, addresses=["10.8.0.2"], is_wireless=False)
    ]
    conn = _make_conn(interfaces=ifaces)
    with patch.object(NetworkService, "get_connectivity", return_value=conn):
        result = plugin.run()

    assert result.status == Status.PASS
    assert any("VPN" in f.summary for f in result.findings)


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_network_plugin_metadata_contains_expected_keys():
    plugin = NetworkPlugin()
    with patch.object(NetworkService, "get_connectivity", return_value=_make_conn()):
        result = plugin.run()

    assert "internet_ok" in result.metadata
    assert "dns_ok" in result.metadata
    assert "dns_latency_ms" in result.metadata
    assert "captive_portal" in result.metadata
    assert "interfaces" in result.metadata


# ── Never raises ─────────────────────────────────────────────────────────────


def test_network_plugin_never_raises_on_service_failure():
    plugin = NetworkPlugin()
    with patch.object(NetworkService, "get_connectivity", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not check network connectivity" in result.findings[0].summary


# ── VPN heuristic ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("utun0", True),
        ("tun1", True),
        ("tap0", True),
        ("ppp0", True),
        ("vpn0", True),
        ("en0", False),
        ("eth0", False),
        ("wlan0", False),
    ],
)
def test_looks_like_vpn(name: str, expected: bool):
    assert _looks_like_vpn(name) == expected


# ── NetworkService unit tests ─────────────────────────────────────────────────


def test_network_service_check_internet_success():
    svc = NetworkService()
    import socket
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("socket.create_connection", return_value=mock_conn):
        ok, host = svc.check_internet(probe_hosts=[("8.8.8.8", 53)])
    assert ok is True
    assert host == "8.8.8.8"


def test_network_service_check_internet_failure():
    svc = NetworkService()
    with patch("socket.create_connection", side_effect=OSError("timeout")):
        ok, host = svc.check_internet(probe_hosts=[("8.8.8.8", 53)])
    assert ok is False
    assert host is None


def test_network_service_dns_success():
    svc = NetworkService()
    with patch("socket.getaddrinfo", return_value=[("AF_INET", None, None, None, ("8.8.8.8", 0))]):
        ok, latency = svc.check_dns("dns.google")
    assert ok is True
    assert latency is not None and latency >= 0


def test_network_service_dns_failure():
    svc = NetworkService()
    with patch("socket.getaddrinfo", side_effect=OSError("nxdomain")):
        ok, latency = svc.check_dns("dns.google")
    assert ok is False
    assert latency is None


def test_network_service_captive_portal_detected():
    svc = NetworkService()
    mock_resp = MagicMock()
    mock_resp.status = 302
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert svc.check_captive_portal() is True


def test_network_service_captive_portal_clear():
    svc = NetworkService()
    mock_resp = MagicMock()
    mock_resp.status = 204
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert svc.check_captive_portal() is False


def test_network_service_captive_portal_returns_false_on_exception():
    svc = NetworkService()
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        assert svc.check_captive_portal() is False
