"""Default tests are isolated from user state and allow loopback networking only."""

import ipaddress
import os
import socket
import tempfile

import pytest

_state_dir = tempfile.TemporaryDirectory(prefix="irp-pytest-state-")
_previous_state_dir = os.environ.get("IRP_STATE_DIR")
os.environ["IRP_STATE_DIR"] = _state_dir.name


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", help="Include external-network Docker tests"
    )
    parser.addoption(
        "--compiled", action="store_true", help="Include checks of a prebuilt binary"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires external services and Docker")
    config.addinivalue_line(
        "markers", "compiled: requires a prebuilt standalone executable"
    )


def pytest_collection_modifyitems(config, items):
    selected, deselected = [], []
    for item in items:
        excluded = any(
            item.get_closest_marker(marker) and not config.getoption(f"--{marker}")
            for marker in ("live", "compiled")
        )
        (deselected if excluded else selected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


def pytest_unconfigure(config):
    if _previous_state_dir is None:
        os.environ.pop("IRP_STATE_DIR", None)
    else:
        os.environ["IRP_STATE_DIR"] = _previous_state_dir
    _state_dir.cleanup()


@pytest.fixture(autouse=True)
def no_external_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return
    connect = socket.socket.connect
    getaddrinfo = socket.getaddrinfo

    def local(host):
        if host in ("localhost", b"localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not local(address[0]):
            raise AssertionError(
                f"External network is disabled in offline tests: {address}"
            )
        return connect(sock, address)

    def guarded_lookup(host, *args, **kwargs):
        if not local(host):
            raise AssertionError(f"External DNS is disabled in offline tests: {host}")
        return getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_lookup)
