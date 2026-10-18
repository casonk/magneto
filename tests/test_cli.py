from __future__ import annotations

import os
from dataclasses import dataclass

from magneto.cli import main
from magneto.config import AppConfig
from magneto.library import FilingResult
from magneto.notifications import NotificationResult
from magneto.recovery import RecoveryResult


@dataclass
class FakeMonitor:
    dry_run: bool | None = None
    prime: bool | None = None

    def run_once(self, *, dry_run=False, prime=False):
        self.dry_run = dry_run
        self.prime = prime
        return NotificationResult(sent=0, skipped=1)


def _config(**overrides) -> AppConfig:
    values = {
        "transmission_url": "http://127.0.0.1:9091/transmission/rpc",
        "download_dir": "/tmp/torrents",
        "secret_key": "test",
        "reannounce_stalled": False,
    }
    values.update(overrides)
    return AppConfig(**values)


def test_notify_cli_uses_monitor(dyno_cli, monkeypatch):
    monitor = FakeMonitor()
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", lambda: _config())
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: monitor)

    result = dyno_cli(main, ["notify", "--dry-run", "--prime"])

    assert result.exit_code == 0
    assert monitor.dry_run is True
    assert monitor.prime is True
    assert "notifications sent=0 skipped=1" in result.stdout


def test_cli_loads_env_file_before_building_config(dyno_cli, monkeypatch, tmp_path):
    env_file = tmp_path / "magneto.env.local"
    env_file.write_text(
        "MAGNETO_NOTIFY_ENABLED=1\n"
        "MAGNETO_NOTIFY_SIGNAL_TARGET=+15551234567\n"
        "MAGNETO_NOTIFY_TAG=magneto/notify\n",
        encoding="utf-8",
    )
    monitor = FakeMonitor()

    def fake_from_env():
        assert os.environ["MAGNETO_NOTIFY_SIGNAL_TARGET"] == "+15551234567"
        assert os.environ["MAGNETO_NOTIFY_TAG"] == "magneto/notify"
        return _config()

    monkeypatch.setenv("MAGNETO_ENV_FILE", str(env_file))
    monkeypatch.delenv("MAGNETO_NOTIFY_SIGNAL_TARGET", raising=False)
    monkeypatch.delenv("MAGNETO_NOTIFY_TAG", raising=False)
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", fake_from_env)
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: monitor)

    result = dyno_cli(main, ["notify", "--dry-run"])

    assert result.exit_code == 0
    assert "notifications sent=0 skipped=1" in result.stdout


def test_notify_cli_reannounces_stalled_before_notifying(dyno_cli, monkeypatch):
    calls = []

    def fake_reannounce(client, *, vpn_interface, dry_run):
        calls.append((vpn_interface, dry_run))
        return RecoveryResult(vpn_up=True, reannounced=("Napoleon Dynamite",))

    monkeypatch.setattr("magneto.cli.AppConfig.from_env", lambda: _config(reannounce_stalled=True))
    monkeypatch.setattr("magneto.cli.reannounce_stalled", fake_reannounce)
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: FakeMonitor())

    result = dyno_cli(main, ["notify", "--dry-run"])

    assert result.exit_code == 0
    assert calls == [("nordlynx", True)]
    assert "would reannounce 1 stalled: Napoleon Dynamite" in result.stdout
    assert "notifications sent=0 skipped=1" in result.stdout


def test_notify_cli_reports_recovery_skip_when_vpn_down(dyno_cli, monkeypatch):
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", lambda: _config(reannounce_stalled=True))
    monkeypatch.setattr(
        "magneto.cli.reannounce_stalled", lambda *_a, **_k: RecoveryResult(vpn_up=False)
    )
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: FakeMonitor())

    result = dyno_cli(main, ["notify"])

    assert result.exit_code == 0
    assert "stalled torrent recovery skipped: nordlynx is down" in result.stdout


def test_notify_cli_files_completed_downloads_after_notifying(dyno_cli, monkeypatch):
    calls = []

    def fake_file_completed(client, *, download_dir, library_dir, dry_run):
        calls.append((download_dir, library_dir, dry_run))
        return FilingResult(moved=("Napoleon Dynamite (2004) [1080p]",), skipped=("Old",))

    monkeypatch.setattr(
        "magneto.cli.AppConfig.from_env", lambda: _config(library_dir="/srv/media/library")
    )
    monkeypatch.setattr("magneto.cli.file_completed", fake_file_completed)
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: FakeMonitor())

    result = dyno_cli(main, ["notify", "--dry-run"])

    assert result.exit_code == 0
    assert calls == [("/tmp/torrents", "/srv/media/library", True)]
    lines = result.stdout.splitlines()
    assert lines.index("notifications sent=0 skipped=1") < lines.index(
        "would move 1 to /srv/media/library: Napoleon Dynamite (2004) [1080p]"
    )
    assert "already in /srv/media/library, left in place: Old" in result.stdout


def test_notify_cli_skips_filing_without_library_dir(dyno_cli, monkeypatch):
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", lambda: _config())
    monkeypatch.setattr(
        "magneto.cli.file_completed",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not file")),
    )
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: FakeMonitor())

    result = dyno_cli(main, ["notify"])

    assert result.exit_code == 0
