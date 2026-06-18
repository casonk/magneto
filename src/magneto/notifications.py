"""Torrent event notifications through shock-relay."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from magneto.config import AppConfig
from magneto.transmission import TransmissionClient

SERVICE_SCRIPTS = {
    "signal": "services/signal-cli/send_message.py",
    "telegram": "services/telegram/send_message.py",
    "twilio": "services/twilio/send_sms.py",
    "whatsapp": "services/whatsapp/send_message.py",
    "gmail": "services/gmail-imap/send_email.py",
    "gmail-imap": "services/gmail-imap/send_email.py",
}


class NotificationError(RuntimeError):
    """Raised when a configured notification cannot be sent."""


class TorrentClient(Protocol):
    def list_torrents(self) -> list[dict]: ...


@dataclass(frozen=True)
class NotificationRoute:
    service: str
    target: str
    config_path: str | None = None


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool
    shock_relay_root: Path
    service: str
    target: str | None
    config_path: str | None
    state_file: Path
    routes: tuple[NotificationRoute, ...] = ()
    tag: str | None = None

    @classmethod
    def from_app_config(cls, config: AppConfig) -> NotificationConfig:
        return cls(
            enabled=config.notify_enabled,
            shock_relay_root=_shock_relay_root(config.notify_shock_relay_root),
            service=config.notify_service,
            target=config.notify_target,
            config_path=config.notify_config_path,
            state_file=_state_file(config.notify_state_file),
            routes=tuple(NotificationRoute(*route) for route in config.notify_routes),
            tag=config.notify_tag,
        )

    def resolved_routes(self) -> tuple[NotificationRoute, ...]:
        if self.routes:
            return self.routes
        if self.target:
            return (NotificationRoute(self.service, self.target, self.config_path),)
        return ()


@dataclass
class NotificationResult:
    sent: int = 0
    skipped: int = 0
    disabled: bool = False


@dataclass
class ShockRelayNotifier:
    config: NotificationConfig

    def available(self) -> bool:
        return any(self._script_path(route).exists() for route in self.config.resolved_routes())

    def send(self, subject: str, body: str) -> bool:
        routes = self.config.resolved_routes()
        if not routes:
            raise NotificationError("MAGNETO_NOTIFY_TARGET is not configured.")
        self._send_to_route(routes[0], subject, body)
        return True

    def send_all(self, subject: str, body: str) -> int:
        routes = self.config.resolved_routes()
        if not routes:
            raise NotificationError("MAGNETO_NOTIFY_TARGET is not configured.")
        for route in routes:
            self._send_to_route(route, subject, body)
        return len(routes)

    def _send_to_route(self, route: NotificationRoute, subject: str, body: str) -> None:
        script = self._script_path(route)
        if not script.exists():
            raise NotificationError(f"shock-relay script not found: {script}")

        cmd = self._command(script, route, subject, body)
        env = {**os.environ, "PYTHONPATH": str(script.parent)}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise NotificationError(detail or f"shock-relay exited {result.returncode}")

    def _script_path(self, route: NotificationRoute) -> Path:
        try:
            script_rel = SERVICE_SCRIPTS[route.service]
        except KeyError as exc:
            raise NotificationError(f"unsupported shock-relay service: {route.service}") from exc
        return self.config.shock_relay_root / script_rel

    def _command(
        self,
        script: Path,
        route: NotificationRoute,
        subject: str,
        body: str,
    ) -> list[str]:
        body = self._tagged_body(route.service, body)
        if route.service in {"gmail", "gmail-imap"}:
            cmd = [sys.executable, str(script), route.target, subject, body]
        else:
            cmd = [sys.executable, str(script), route.target, f"{subject}\n{body}"]
        if route.config_path:
            cmd.extend(["--config", route.config_path])
        if self.config.tag and route.service == "signal":
            cmd.extend(["--meta", f"cc-tag: {self.config.tag}"])
        if self.config.tag and route.service in {"gmail", "gmail-imap"}:
            cmd.extend(["--header", f"X-Magneto-Tag: {self.config.tag}"])
        return cmd

    def _tagged_body(self, service: str, body: str) -> str:
        if not self.config.tag or service in {"signal", "gmail", "gmail-imap"}:
            return body
        return f"Tag: {self.config.tag}\n{body}"


@dataclass
class TorrentNotificationMonitor:
    client: TorrentClient
    notifier: ShockRelayNotifier
    state_file: Path

    def run_once(self, *, dry_run: bool = False, prime: bool = False) -> NotificationResult:
        if not self.notifier.config.enabled:
            return NotificationResult(disabled=True)
        if not self.notifier.config.resolved_routes():
            return NotificationResult(disabled=True)

        state = _load_state(self.state_file)
        sent = 0
        skipped = 0
        changed = False

        for torrent in self.client.list_torrents():
            key = _torrent_key(torrent)
            torrent_state = state.setdefault("torrents", {}).setdefault(key, {})
            events = _events_for_torrent(torrent, torrent_state)
            if not events:
                continue
            for event in events:
                if dry_run:
                    print(f"would notify: {event['subject']}")
                    skipped += 1
                    continue
                _mark_event(torrent_state, event)
                changed = True
                if prime:
                    skipped += 1
                    continue
                sent += self.notifier.send_all(event["subject"], event["body"])

        if changed:
            _save_state(self.state_file, state)
        return NotificationResult(sent=sent, skipped=skipped)


def build_monitor(config: AppConfig | None = None) -> TorrentNotificationMonitor:
    app_config = config or AppConfig.from_env()
    client = TransmissionClient(
        app_config.transmission_url,
        username=app_config.username,
        password=app_config.password,
        timeout=app_config.request_timeout,
    )
    notify_config = NotificationConfig.from_app_config(app_config)
    return TorrentNotificationMonitor(
        client=client,
        notifier=ShockRelayNotifier(notify_config),
        state_file=notify_config.state_file,
    )


def _events_for_torrent(torrent: dict, torrent_state: dict) -> list[dict[str, str]]:
    events = []
    done_marker = _completion_marker(torrent)
    if done_marker and torrent_state.get("complete") != done_marker:
        events.append(
            {
                "kind": "complete",
                "marker": done_marker,
                "subject": f"Magneto complete: {_torrent_name(torrent)}",
                "body": _completion_body(torrent),
            }
        )

    error_marker = _error_marker(torrent)
    if error_marker and torrent_state.get("error") != error_marker:
        events.append(
            {
                "kind": "error",
                "marker": error_marker,
                "subject": f"Magneto error: {_torrent_name(torrent)}",
                "body": _error_body(torrent),
            }
        )
    return events


def _mark_event(torrent_state: dict, event: dict[str, str]) -> None:
    torrent_state[event["kind"]] = event["marker"]


def _completion_marker(torrent: dict) -> str:
    if not torrent.get("isFinished") and float(torrent.get("percentDone") or 0.0) < 1.0:
        return ""
    done_date = int(torrent.get("doneDate") or 0)
    if done_date > 0:
        return str(done_date)
    return "complete"


def _error_marker(torrent: dict) -> str:
    if not int(torrent.get("error") or 0):
        return ""
    return str(torrent.get("errorString") or "Transmission reported an error.")


def _completion_body(torrent: dict) -> str:
    return "\n".join(
        [
            f"Name: {_torrent_name(torrent)}",
            f"Size: {torrent.get('totalSizeText', 'unknown')}",
            f"Downloaded: {torrent.get('downloadedText', 'unknown')}",
            f"Uploaded: {torrent.get('uploadedText', 'unknown')}",
            f"Ratio: {torrent.get('uploadRatio', 'n/a')}",
        ]
    )


def _error_body(torrent: dict) -> str:
    return "\n".join(
        [
            f"Name: {_torrent_name(torrent)}",
            f"Status: {torrent.get('statusLabel', 'Error')}",
            f"Error: {torrent.get('errorString') or 'Transmission reported an error.'}",
            f"Tracker: {torrent.get('trackerStatus') or 'n/a'}",
        ]
    )


def _torrent_key(torrent: dict) -> str:
    return str(torrent.get("hashString") or torrent.get("id") or torrent.get("name"))


def _torrent_name(torrent: dict) -> str:
    return str(torrent.get("name") or "<unnamed>")[:120]


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "torrents": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "torrents": {}}
    if not isinstance(data, dict):
        return {"version": 1, "torrents": {}}
    data.setdefault("version", 1)
    data.setdefault("torrents", {})
    return data


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _state_file(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "magneto" / "notifications.json"


def _shock_relay_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    for candidate in _shock_relay_candidates():
        if candidate.exists():
            return candidate
    return Path("../shock-relay").resolve()


def _shock_relay_candidates() -> list[Path]:
    candidates = [Path.cwd().parent / "shock-relay"]
    source_path = Path(__file__).resolve()
    if len(source_path.parents) > 3:
        candidates.append(source_path.parents[3] / "shock-relay")
    return candidates
