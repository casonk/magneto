"""Move finished downloads out of the download dir into the media library."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

# Transmission is verifying or about to verify local data; moving now would race it.
CHECKING_STATUSES = {1, 2}


class LibraryClient(Protocol):
    def list_torrents(self) -> list[dict[str, Any]]: ...

    def set_location(self, torrent_id: int, location: str, *, move: bool) -> None: ...


@dataclass(frozen=True)
class FilingResult:
    moved: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def _same_dir(left: str, right: str) -> bool:
    return os.path.normpath(left) == os.path.normpath(right)


def is_ready_to_file(torrent: dict[str, Any], download_dir: str) -> bool:
    """A complete, error-free torrent still sitting in the download dir."""
    if not _same_dir(str(torrent.get("downloadDir") or ""), download_dir):
        return False
    if float(torrent.get("percentDone") or 0.0) < 1 or int(torrent.get("leftUntilDone") or 0):
        return False
    if int(torrent.get("error") or 0):
        return False
    return int(torrent.get("status") or 0) not in CHECKING_STATUSES


def file_completed(
    client: LibraryClient,
    *,
    download_dir: str,
    library_dir: str,
    dry_run: bool = False,
    exists: Callable[[str], bool] = os.path.lexists,
) -> FilingResult:
    """Ask Transmission to move finished torrents into the library dir.

    Transmission moves the data itself (copying across filesystems) and keeps
    tracking the torrent at its new location, so seeding still works. A torrent
    whose name already exists in the library is left alone rather than merged
    into or over the existing entry.
    """
    moved: list[str] = []
    skipped: list[str] = []
    for torrent in client.list_torrents():
        if not is_ready_to_file(torrent, download_dir):
            continue
        name = str(torrent.get("name") or "")
        if not name or exists(os.path.join(library_dir, name)):
            skipped.append(name)
            continue
        if not dry_run:
            client.set_location(int(torrent["id"]), library_dir, move=True)
        moved.append(name)
    return FilingResult(moved=tuple(moved), skipped=tuple(skipped))
