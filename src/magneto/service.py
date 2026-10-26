"""Narrow local control for the Transmission system service."""

from __future__ import annotations

import subprocess


class ServiceRestartError(RuntimeError):
    """Raised when the fixed Transmission restart request fails."""


def restart_transmission_service() -> None:
    try:
        subprocess.run(
            [
                "sudo",
                "-n",
                "/usr/bin/systemctl",
                "--no-block",
                "restart",
                "transmission-daemon.service",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ServiceRestartError(
            "Transmission restart could not be requested. Check the service permission and journal."
        ) from exc
