from __future__ import annotations

import subprocess

import pytest

from magneto.service import ServiceRestartError, restart_transmission_service


def test_restart_requests_only_fixed_transmission_unit(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr("magneto.service.subprocess.run", fake_run)

    restart_transmission_service()

    assert calls[0][0] == [
        "sudo",
        "-n",
        "/usr/bin/systemctl",
        "--no-block",
        "restart",
        "transmission-daemon.service",
    ]
    assert calls[0][1]["timeout"] == 10


def test_restart_failure_is_reported_without_command_output(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="private detail")

    monkeypatch.setattr("magneto.service.subprocess.run", fake_run)

    with pytest.raises(ServiceRestartError, match="permission and journal") as exc_info:
        restart_transmission_service()

    assert "private detail" not in str(exc_info.value)
