"""Recover Transmission after tracker failures and VPN reconnects."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

DOWNLOADING = 4
DEFAULT_MIN_BACKOFF_SECONDS = 300
DEFAULT_RESTART_COOLDOWN_SECONDS = 900
DEFAULT_RPC_WAIT_SECONDS = 20


class RecoveryClient(Protocol):
    def list_torrents(self) -> list[dict[str, Any]]: ...

    def reannounce(self, torrent_id: int) -> None: ...


@dataclass(frozen=True)
class RecoveryResult:
    vpn_up: bool
    reannounced: tuple[str, ...] = ()
    restarted: bool = False
    would_restart: bool = False


@dataclass(frozen=True)
class RecoveryState:
    vpn_up: bool = True
    interface_identity: str | None = None
    stalled_ids: tuple[int, ...] = ()
    reannounced_at: float | None = None
    restarted_at: float | None = None
    last_restart_at: float | None = None


def vpn_interface_identity(
    interface: str, sys_class_net: Path = Path("/sys/class/net")
) -> str | None:
    """Identify one lifetime of a VPN interface using its kernel index."""
    if not interface:
        return "unrestricted"
    path = sys_class_net / interface
    if not path.exists():
        return None
    try:
        return (path / "ifindex").read_text(encoding="utf-8").strip() or "present"
    except OSError:
        return "present"


def vpn_interface_up(interface: str, sys_class_net: Path = Path("/sys/class/net")) -> bool:
    """Return True when no interface is required or the named one exists."""
    return vpn_interface_identity(interface, sys_class_net) is not None


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


def _load_state(path: Path | None) -> RecoveryState | None:
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return RecoveryState(
            vpn_up=bool(raw.get("vpn_up", True)),
            interface_identity=raw.get("interface_identity"),
            stalled_ids=tuple(int(value) for value in raw.get("stalled_ids", ())),
            reannounced_at=raw.get("reannounced_at"),
            restarted_at=raw.get("restarted_at"),
            last_restart_at=raw.get("last_restart_at"),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _save_state(path: Path | None, state: RecoveryState) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def _wait_for_rpc(
    client_factory: Callable[[], RecoveryClient],
    *,
    deadline: float,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> RecoveryClient:
    last_error: Exception | None = None
    while monotonic() < deadline:
        client = client_factory()
        try:
            client.list_torrents()
            return client
        except Exception as exc:  # RPC transports expose several exception types.
            last_error = exc
            sleeper(0.5)
    if last_error is not None:
        raise last_error
    raise TimeoutError("Transmission RPC did not return after restart")


def reannounce_stalled(
    client: RecoveryClient,
    *,
    vpn_interface: str,
    min_backoff: int = DEFAULT_MIN_BACKOFF_SECONDS,
    dry_run: bool = False,
    clock: Callable[[], float] = time.time,
    interface_identity: Callable[[str], str | None] = vpn_interface_identity,
    state_file: Path | None = None,
    restart_service: Callable[[], None] | None = None,
    client_factory: Callable[[], RecoveryClient] | None = None,
    restart_cooldown: int = DEFAULT_RESTART_COOLDOWN_SECONDS,
    rpc_wait_seconds: int = DEFAULT_RPC_WAIT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    interface_up: Callable[[str], bool] | None = None,
) -> RecoveryResult:
    """Reannounce stalled torrents and replace stale daemon sockets once.

    A first stalled observation requests a reannounce. If the same torrents
    remain stalled on the next run, or the VPN interface was down/recreated,
    restart Transmission once, wait for fresh RPC health, then reannounce with
    a new client. Persistent incident state and a cooldown prevent loops.
    """
    identity = (
        ("present" if interface_up(vpn_interface) else None)
        if interface_up is not None
        else interface_identity(vpn_interface)
    )
    previous = _load_state(state_file)
    if identity is None:
        if not dry_run:
            _save_state(
                state_file,
                RecoveryState(
                    vpn_up=False,
                    interface_identity=previous.interface_identity if previous else None,
                    last_restart_at=previous.last_restart_at if previous else None,
                ),
            )
        return RecoveryResult(vpn_up=False)

    now = clock()
    stalled = [t for t in client.list_torrents() if is_stalled(t, now, min_backoff)]
    stalled_ids = tuple(sorted(int(t["id"]) for t in stalled))
    names = tuple(str(t.get("name")) for t in stalled)
    if not stalled:
        if not dry_run:
            _save_state(
                state_file,
                RecoveryState(
                    vpn_up=True,
                    interface_identity=identity,
                    last_restart_at=previous.last_restart_at if previous else None,
                ),
            )
        return RecoveryResult(vpn_up=True)

    vpn_reconnected = bool(
        previous and (not previous.vpn_up or previous.interface_identity != identity)
    )
    prior_reannounce_failed = bool(
        previous
        and previous.vpn_up
        and previous.interface_identity == identity
        and previous.stalled_ids == stalled_ids
        and previous.reannounced_at is not None
        and previous.restarted_at is None
    )
    last_restart = previous.last_restart_at if previous else None
    cooldown_elapsed = last_restart is None or now - last_restart >= restart_cooldown
    should_restart = bool(
        state_file
        and restart_service
        and client_factory
        and cooldown_elapsed
        and (vpn_reconnected or prior_reannounce_failed)
    )

    if dry_run:
        return RecoveryResult(vpn_up=True, reannounced=names, would_restart=should_restart)

    restarted_at = previous.restarted_at if previous else None
    if should_restart:
        restart_service()
        restarted_at = now
        _save_state(
            state_file,
            RecoveryState(
                vpn_up=True,
                interface_identity=identity,
                stalled_ids=stalled_ids,
                reannounced_at=now,
                restarted_at=now,
                last_restart_at=now,
            ),
        )
        # The privileged restart is deliberately non-blocking. Give systemd a
        # chance to replace the process before accepting an RPC response.
        sleeper(1.0)
        client = _wait_for_rpc(
            client_factory,
            deadline=monotonic() + rpc_wait_seconds,
            monotonic=monotonic,
            sleeper=sleeper,
        )

    for torrent_id in stalled_ids:
        client.reannounce(torrent_id)
    _save_state(
        state_file,
        RecoveryState(
            vpn_up=True,
            interface_identity=identity,
            stalled_ids=stalled_ids,
            reannounced_at=now,
            restarted_at=restarted_at,
            last_restart_at=now if should_restart else last_restart,
        ),
    )
    return RecoveryResult(vpn_up=True, reannounced=names, restarted=should_restart)
