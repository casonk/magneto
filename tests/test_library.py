from __future__ import annotations

from dataclasses import dataclass, field

from magneto.library import file_completed, is_ready_to_file

DOWNLOADS = "/srv/snowbridge/share/torrents"
LIBRARY = "/srv/media/library"


def _torrent(torrent_id=1, **overrides):
    torrent = {
        "id": torrent_id,
        "name": f"torrent-{torrent_id}",
        "status": 0,
        "percentDone": 1.0,
        "leftUntilDone": 0,
        "error": 0,
        "downloadDir": DOWNLOADS,
    }
    torrent.update(overrides)
    return torrent


@dataclass
class FakeClient:
    torrents: list[dict]
    moves: list[tuple[int, str, bool]] = field(default_factory=list)

    def list_torrents(self):
        return self.torrents

    def set_location(self, torrent_id, location, *, move):
        self.moves.append((torrent_id, location, move))


def test_complete_torrent_in_download_dir_is_ready():
    assert is_ready_to_file(_torrent(), DOWNLOADS)
    assert is_ready_to_file(_torrent(status=6, downloadDir=DOWNLOADS + "/"), DOWNLOADS)


def test_incomplete_errored_checking_or_already_moved_torrent_is_not_ready():
    assert not is_ready_to_file(_torrent(percentDone=0.5, leftUntilDone=10), DOWNLOADS)
    assert not is_ready_to_file(_torrent(error=3), DOWNLOADS)
    assert not is_ready_to_file(_torrent(status=2), DOWNLOADS)
    assert not is_ready_to_file(_torrent(downloadDir=LIBRARY), DOWNLOADS)


def test_file_completed_moves_ready_torrents_into_library():
    client = FakeClient([_torrent(1), _torrent(2, percentDone=0.2, leftUntilDone=5)])

    result = file_completed(
        client, download_dir=DOWNLOADS, library_dir=LIBRARY, exists=lambda _path: False
    )

    assert client.moves == [(1, LIBRARY, True)]
    assert result.moved == ("torrent-1",)
    assert result.skipped == ()


def test_file_completed_leaves_name_collisions_in_place():
    client = FakeClient([_torrent(1), _torrent(2)])

    result = file_completed(
        client,
        download_dir=DOWNLOADS,
        library_dir=LIBRARY,
        exists=lambda path: path == f"{LIBRARY}/torrent-1",
    )

    assert client.moves == [(2, LIBRARY, True)]
    assert result.skipped == ("torrent-1",)


def test_file_completed_dry_run_reports_without_moving():
    client = FakeClient([_torrent(1)])

    result = file_completed(
        client,
        download_dir=DOWNLOADS,
        library_dir=LIBRARY,
        dry_run=True,
        exists=lambda _path: False,
    )

    assert client.moves == []
    assert result.moved == ("torrent-1",)
