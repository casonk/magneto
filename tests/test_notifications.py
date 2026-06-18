from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dyno_lab.proc import SubprocessPatch

from magneto.notifications import (
    NotificationConfig,
    NotificationRoute,
    ShockRelayNotifier,
    TorrentNotificationMonitor,
)


@dataclass
class FakeTorrentClient:
    torrents: list[dict]

    def list_torrents(self):
        return self.torrents


def _shock_root(tmp_path: Path, service: str = "signal-cli", script: str = "send_message.py"):
    root = tmp_path / "shock-relay"
    script_path = root / "services" / service / script
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return root


def _config(tmp_path: Path, *, service: str = "signal") -> NotificationConfig:
    return NotificationConfig(
        enabled=True,
        shock_relay_root=_shock_root(tmp_path),
        service=service,
        target="+15551234567",
        config_path=str(tmp_path / "config.local.yaml"),
        state_file=tmp_path / "notifications.json",
    )


def test_shock_relay_notifier_sends_signal_message(dyno_proc, tmp_path):
    config = NotificationConfig(
        enabled=True,
        shock_relay_root=_shock_root(tmp_path),
        service="signal",
        target="+15551234567",
        config_path=str(tmp_path / "config.local.yaml"),
        state_file=tmp_path / "notifications.json",
        tag="magneto/notify",
    )
    recorder = dyno_proc()

    with SubprocessPatch(recorder, target="magneto.notifications.subprocess.run"):
        assert ShockRelayNotifier(config).send("Subject", "Body") is True

    assert recorder.call_count == 1
    command = recorder.commands()[0]
    assert command[:3] == [
        sys.executable,
        str(config.shock_relay_root / "services/signal-cli/send_message.py"),
        "+15551234567",
    ]
    assert command[3] == "Subject\nBody"
    assert command[-4:] == [
        "--config",
        str(tmp_path / "config.local.yaml"),
        "--meta",
        "cc-tag: magneto/notify",
    ]


def test_shock_relay_notifier_sends_gmail_subject_and_body(dyno_proc, tmp_path):
    root = _shock_root(tmp_path, service="gmail-imap", script="send_email.py")
    config = NotificationConfig(
        enabled=True,
        shock_relay_root=root,
        service="gmail",
        target="user@example.com",
        config_path=None,
        state_file=tmp_path / "notifications.json",
        tag="magneto/notify",
    )
    recorder = dyno_proc()

    with SubprocessPatch(recorder, target="magneto.notifications.subprocess.run"):
        ShockRelayNotifier(config).send("Subject", "Body")

    assert recorder.commands()[0] == [
        sys.executable,
        str(root / "services/gmail-imap/send_email.py"),
        "user@example.com",
        "Subject",
        "Body",
        "--header",
        "X-Magneto-Tag: magneto/notify",
    ]


def test_shock_relay_notifier_sends_to_all_configured_routes(dyno_proc, tmp_path):
    root = _shock_root(tmp_path)
    gmail_script = root / "services/gmail-imap/send_email.py"
    gmail_script.parent.mkdir(parents=True, exist_ok=True)
    gmail_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    config = NotificationConfig(
        enabled=True,
        shock_relay_root=root,
        service="signal",
        target=None,
        config_path=None,
        state_file=tmp_path / "notifications.json",
        routes=(
            NotificationRoute("signal", "+15551234567", "signal.yaml"),
            NotificationRoute("gmail-imap", "user@example.com", "gmail.yaml"),
        ),
        tag="magneto/notify",
    )
    recorder = dyno_proc()

    with SubprocessPatch(recorder, target="magneto.notifications.subprocess.run"):
        count = ShockRelayNotifier(config).send_all("Subject", "Body")

    assert count == 2
    assert recorder.call_count == 2
    assert recorder.commands()[0][2] == "+15551234567"
    assert recorder.commands()[1][2] == "user@example.com"


def test_monitor_sends_completion_once_and_records_state(dyno_proc, tmp_path):
    torrent = {
        "id": 7,
        "hashString": "abc123",
        "name": "example.iso",
        "isFinished": True,
        "percentDone": 1.0,
        "doneDate": 123,
        "totalSizeText": "1.0 GB",
        "downloadedText": "1.0 GB",
        "uploadedText": "0 B",
        "uploadRatio": 0,
    }
    config = _config(tmp_path)
    monitor = TorrentNotificationMonitor(
        client=FakeTorrentClient([torrent]),
        notifier=ShockRelayNotifier(config),
        state_file=config.state_file,
    )
    recorder = dyno_proc()

    with SubprocessPatch(recorder, target="magneto.notifications.subprocess.run"):
        first = monitor.run_once()
        second = monitor.run_once()

    assert first.sent == 1
    assert second.sent == 0
    assert recorder.call_count == 1
    state = json.loads(config.state_file.read_text(encoding="utf-8"))
    assert state["torrents"]["abc123"]["complete"] == "123"


def test_monitor_sends_error_when_error_message_changes(dyno_proc, tmp_path):
    torrent = {
        "id": 7,
        "hashString": "abc123",
        "name": "example.iso",
        "error": 3,
        "errorString": "tracker failed",
        "statusLabel": "Error",
        "trackerStatus": "tracker.example: failed",
    }
    config = _config(tmp_path)
    monitor = TorrentNotificationMonitor(
        client=FakeTorrentClient([torrent]),
        notifier=ShockRelayNotifier(config),
        state_file=config.state_file,
    )
    recorder = dyno_proc()

    with SubprocessPatch(recorder, target="magneto.notifications.subprocess.run"):
        result = monitor.run_once()

    assert result.sent == 1
    assert "Magneto error: example.iso" in recorder.commands()[0][3]


def test_monitor_disabled_without_target(tmp_path):
    config = NotificationConfig(
        enabled=True,
        shock_relay_root=_shock_root(tmp_path),
        service="signal",
        target=None,
        config_path=None,
        state_file=tmp_path / "notifications.json",
    )
    monitor = TorrentNotificationMonitor(
        client=FakeTorrentClient([]),
        notifier=ShockRelayNotifier(config),
        state_file=config.state_file,
    )

    result = monitor.run_once()

    assert result.disabled is True
    assert not config.state_file.exists()
