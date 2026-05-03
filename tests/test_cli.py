from __future__ import annotations

import os
from dataclasses import dataclass

from magneto.cli import main
from magneto.notifications import NotificationResult


@dataclass
class FakeMonitor:
    dry_run: bool | None = None
    prime: bool | None = None

    def run_once(self, *, dry_run=False, prime=False):
        self.dry_run = dry_run
        self.prime = prime
        return NotificationResult(sent=0, skipped=1)


def test_notify_cli_uses_monitor(dyno_cli, monkeypatch):
    monitor = FakeMonitor()
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", lambda: object())
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
        return object()

    monkeypatch.setenv("MAGNETO_ENV_FILE", str(env_file))
    monkeypatch.delenv("MAGNETO_NOTIFY_SIGNAL_TARGET", raising=False)
    monkeypatch.delenv("MAGNETO_NOTIFY_TAG", raising=False)
    monkeypatch.setattr("magneto.cli.AppConfig.from_env", fake_from_env)
    monkeypatch.setattr("magneto.cli.build_monitor", lambda _config: monitor)

    result = dyno_cli(main, ["notify", "--dry-run"])

    assert result.exit_code == 0
    assert "notifications sent=0 skipped=1" in result.stdout
