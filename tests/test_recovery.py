from __future__ import annotations

from dataclasses import dataclass, field

from magneto.recovery import is_stalled, reannounce_stalled, vpn_interface_up

NOW = 1_000_000


def _tracker(*, succeeded=False, announced=True, next_in=6000):
    return {
        "hasAnnounced": announced,
        "lastAnnounceSucceeded": succeeded,
        "nextAnnounceTime": NOW + next_in,
    }


def _torrent(torrent_id=1, **overrides):
    torrent = {
        "id": torrent_id,
        "name": f"torrent-{torrent_id}",
        "status": 4,
        "percentDone": 0.0,
        "peersConnected": 0,
        "trackerStats": [_tracker(), _tracker(next_in=6200)],
    }
    torrent.update(overrides)
    return torrent


@dataclass
class FakeClient:
    torrents: list[dict]
    reannounced: list[int] = field(default_factory=list)

    def list_torrents(self):
        return self.torrents

    def reannounce(self, torrent_id):
        self.reannounced.append(torrent_id)


def test_backed_off_torrent_with_only_failed_trackers_is_stalled():
    assert is_stalled(_torrent(), NOW, 300)


def test_torrent_with_peers_or_successful_tracker_is_not_stalled():
    assert not is_stalled(_torrent(peersConnected=2), NOW, 300)
    assert not is_stalled(_torrent(trackerStats=[_tracker(), _tracker(succeeded=True)]), NOW, 300)


def test_torrent_retrying_soon_or_not_downloading_is_not_stalled():
    assert not is_stalled(_torrent(trackerStats=[_tracker(next_in=60)]), NOW, 300)
    assert not is_stalled(_torrent(status=0), NOW, 300)
    assert not is_stalled(_torrent(percentDone=1.0), NOW, 300)


def test_torrent_whose_trackers_never_announced_is_not_stalled():
    assert not is_stalled(_torrent(trackerStats=[_tracker(announced=False)]), NOW, 300)
    assert not is_stalled(_torrent(trackerStats=[]), NOW, 300)


def test_reannounce_stalled_only_touches_stalled_torrents():
    client = FakeClient([_torrent(1), _torrent(2, peersConnected=5), _torrent(3)])

    result = reannounce_stalled(
        client, vpn_interface="nordlynx", clock=lambda: NOW, interface_up=lambda _i: True
    )

    assert result.vpn_up
    assert result.reannounced == ("torrent-1", "torrent-3")
    assert client.reannounced == [1, 3]


def test_reannounce_stalled_waits_for_vpn_interface():
    client = FakeClient([_torrent(1)])

    result = reannounce_stalled(
        client, vpn_interface="nordlynx", clock=lambda: NOW, interface_up=lambda _i: False
    )

    assert not result.vpn_up
    assert client.reannounced == []


def test_reannounce_stalled_dry_run_reports_without_reannouncing():
    client = FakeClient([_torrent(1)])

    result = reannounce_stalled(
        client,
        vpn_interface="nordlynx",
        dry_run=True,
        clock=lambda: NOW,
        interface_up=lambda _i: True,
    )

    assert result.reannounced == ("torrent-1",)
    assert client.reannounced == []


def test_vpn_interface_up_checks_sysfs(tmp_path):
    (tmp_path / "nordlynx").mkdir()

    assert vpn_interface_up("nordlynx", tmp_path)
    assert not vpn_interface_up("wg9", tmp_path)
    assert vpn_interface_up("", tmp_path)
