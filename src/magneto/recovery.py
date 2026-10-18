"""Recover torrents left in tracker backoff after a VPN outage."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DOWNLOADING = 4

# Transmission retries on its own soon enough below this; only step in when
# the next scheduled announce is further out than one poll interval.
DEFAULT_MIN_BACKOFF_SECONDS = 300


class RecoveryClient(Protocol):
    def list_torrents(self) -> list[dict[str, Any]]: ...

    def reannounce(self, torrent_id: int) -> None: ...


@dataclass(frozen=True)
class RecoveryResult:
    vpn_up: bool
    reannounced: tuple[str, ...] = ()


def vpn_interface_up(interface: str, sys_class_net: Path = Path("/sys/class/net")) -> bool:
    """Return True when no interface is required or the named one exists."""
    if not interface:
        return True
    return (sys_class_net / interface).exists()


def is_stalled(torrent: dict[str, Any], now: float, min_backoff: int) -> bool:
    """A downloading torrent with no peers whose trackers have all failed and backed off."""
    if int(torrent.get("status") or 0) != DOWNLOADING:
        return False
    if float(torrent.get("percentDone") or 0.0) >= 1:
        return False
    if int(torrent.get("peersConnected") or 0) > 0:
        return False
    announced = [s for s in torrent.get("trackerStats") or [] if s.get("hasAnnounced")]
    if not announced or any(s.get("lastAnnounceSucceeded") for s in announced):
        return False
    next_announce = min(int(s.get("nextAnnounceTime") or 0) for s in announced)
    return next_announce - now > min_backoff


def reannounce_stalled(
    client: RecoveryClient,
    *,
    vpn_interface: str,
    min_backoff: int = DEFAULT_MIN_BACKOFF_SECONDS,
    dry_run: bool = False,
    clock: Callable[[], float] = time.time,
    interface_up: Callable[[str], bool] = vpn_interface_up,
) -> RecoveryResult:
    """Reannounce stalled torrents once the VPN interface is back.

    While the VPN guard blocks egress every announce fails and Transmission
    backs off for up to two hours, so torrents stay idle long after the tunnel
    reconnects. Skip entirely while the interface is down: announcing then
    would only fail again and extend the backoff.
    """
    if not interface_up(vpn_interface):
        return RecoveryResult(vpn_up=False)
    now = clock()
    stalled = [t for t in client.list_torrents() if is_stalled(t, now, min_backoff)]
    if not dry_run:
        for torrent in stalled:
            client.reannounce(int(torrent["id"]))
    return RecoveryResult(vpn_up=True, reannounced=tuple(str(t.get("name")) for t in stalled))
