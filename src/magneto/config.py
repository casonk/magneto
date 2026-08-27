"""Runtime configuration for magneto."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from magneto.autopass import AutoPassCredentialError, resolve_auto_pass_credentials


class ConfigurationError(RuntimeError):
    """Raised when magneto runtime configuration is invalid."""


@dataclass(frozen=True)
class TorrentHost:
    """One approved Magneto endpoint, rendered from the private site registry."""

    id: str
    label: str
    url: str
    current: bool = False


@dataclass(frozen=True)
class AppConfig:
    transmission_url: str
    download_dir: str
    secret_key: str
    public_origin: str | None = None
    allowed_origins: tuple[str, ...] = ()
    username: str | None = None
    password: str | None = None
    request_timeout: float = 10.0
    max_torrent_upload_bytes: int = 4 * 1024 * 1024
    notify_enabled: bool = False
    notify_state_file: str | None = None
    notify_shock_relay_root: str | None = None
    notify_service: str = "signal"
    notify_target: str | None = None
    notify_config_path: str | None = None
    notify_routes: tuple[tuple[str, str, str | None], ...] = ()
    notify_tag: str | None = None
    no_seed_by_default: bool = False
    torrent_hosts: tuple[TorrentHost, ...] = ()

    @classmethod
    def from_env(cls) -> AppConfig:
        username = os.environ.get("MAGNETO_TRANSMISSION_USERNAME") or None
        password = os.environ.get("MAGNETO_TRANSMISSION_PASSWORD") or None
        keepass_entry = os.environ.get("MAGNETO_TRANSMISSION_KEEPASS_ENTRY") or None
        if keepass_entry and (not username or password is None):
            try:
                keepass_username, keepass_password = resolve_auto_pass_credentials(
                    keepass_entry,
                    profile=os.environ.get("MAGNETO_TRANSMISSION_KEEPASS_PROFILE") or None,
                    root=os.environ.get("MAGNETO_AUTO_PASS_ROOT") or None,
                    env_file=os.environ.get("MAGNETO_AUTO_PASS_ENV_FILE") or None,
                    username_field=os.environ.get(
                        "MAGNETO_TRANSMISSION_KEEPASS_USERNAME_FIELD",
                        "username",
                    ),
                    password_field=os.environ.get(
                        "MAGNETO_TRANSMISSION_KEEPASS_PASSWORD_FIELD",
                        "password",
                    ),
                )
            except AutoPassCredentialError as exc:
                raise ConfigurationError(str(exc)) from exc
            username = username or keepass_username
            password = password if password is not None else keepass_password
        if keepass_entry and password and not username:
            raise ConfigurationError(
                "Transmission password was resolved from auto-pass, but no username was set. "
                "Set MAGNETO_TRANSMISSION_USERNAME or the KeePassXC UserName field."
            )
        notify_routes = _notify_routes_from_env()
        notify_target = os.environ.get("MAGNETO_NOTIFY_TARGET") or None
        return cls(
            transmission_url=os.environ.get(
                "MAGNETO_TRANSMISSION_URL",
                "http://127.0.0.1:9091/transmission/rpc",
            ),
            username=username,
            password=password,
            download_dir=os.environ.get(
                "MAGNETO_DOWNLOAD_DIR",
                "/srv/snowbridge/share/torrents",
            ),
            secret_key=os.environ.get("MAGNETO_SECRET_KEY") or secrets.token_hex(32),
            public_origin=os.environ.get("MAGNETO_PUBLIC_ORIGIN") or None,
            allowed_origins=_split_csv(os.environ.get("MAGNETO_ALLOWED_ORIGINS", "")),
            request_timeout=float(os.environ.get("MAGNETO_REQUEST_TIMEOUT", "10")),
            max_torrent_upload_bytes=int(
                os.environ.get("MAGNETO_MAX_TORRENT_UPLOAD_BYTES", str(4 * 1024 * 1024))
            ),
            notify_enabled=_truthy(os.environ.get("MAGNETO_NOTIFY_ENABLED"))
            or bool(notify_target)
            or bool(notify_routes),
            notify_state_file=os.environ.get("MAGNETO_NOTIFY_STATE_FILE") or None,
            notify_shock_relay_root=os.environ.get("MAGNETO_SHOCK_RELAY_ROOT") or None,
            notify_service=os.environ.get("MAGNETO_NOTIFY_SERVICE", "signal"),
            notify_target=notify_target,
            notify_config_path=os.environ.get("MAGNETO_NOTIFY_CONFIG") or None,
            notify_routes=notify_routes,
            notify_tag=os.environ.get("MAGNETO_NOTIFY_TAG") or None,
            no_seed_by_default=_truthy(os.environ.get("MAGNETO_NO_SEED_BY_DEFAULT")),
            torrent_hosts=_torrent_hosts_from_env(),
        )

    @property
    def download_path(self) -> Path:
        return Path(self.download_dir).expanduser()


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _torrent_hosts_from_env() -> tuple[TorrentHost, ...]:
    raw_path = os.environ.get("MAGNETO_TORRENT_HOSTS_FILE", "").strip()
    if not raw_path:
        return ()
    path = Path(raw_path).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Cannot read MAGNETO_TORRENT_HOSTS_FILE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"MAGNETO_TORRENT_HOSTS_FILE is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("hosts"), list):
        raise ConfigurationError("MAGNETO_TORRENT_HOSTS_FILE must contain a hosts array.")

    hosts: list[TorrentHost] = []
    ids: set[str] = set()
    current_count = 0
    for entry in raw["hosts"]:
        if not isinstance(entry, dict):
            raise ConfigurationError("Every torrent host entry must be an object.")
        host_id = entry.get("id")
        label = entry.get("label")
        url = entry.get("url")
        current = entry.get("current", False)
        if not isinstance(host_id, str) or not host_id or len(host_id) > 64:
            raise ConfigurationError(
                "Torrent host id must be a non-empty string up to 64 characters."
            )
        if host_id in ids:
            raise ConfigurationError(f"Duplicate torrent host id: {host_id!r}")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ConfigurationError(f"Torrent host {host_id!r} has an invalid label.")
        if not isinstance(url, str) or not _valid_torrent_host_url(url):
            raise ConfigurationError(f"Torrent host {host_id!r} has an invalid URL.")
        if not isinstance(current, bool):
            raise ConfigurationError(f"Torrent host {host_id!r} has an invalid current flag.")
        ids.add(host_id)
        current_count += int(current)
        hosts.append(
            TorrentHost(id=host_id, label=label.strip(), url=url.rstrip("/") + "/", current=current)
        )
    if current_count > 1:
        raise ConfigurationError("MAGNETO_TORRENT_HOSTS_FILE may mark only one host as current.")
    return tuple(hosts)


def _valid_torrent_host_url(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _notify_routes_from_env() -> tuple[tuple[str, str, str | None], ...]:
    routes: list[tuple[str, str, str | None]] = []
    for service, target_var, config_var in (
        ("signal", "MAGNETO_NOTIFY_SIGNAL_TARGET", "MAGNETO_NOTIFY_SIGNAL_CONFIG"),
        ("telegram", "MAGNETO_NOTIFY_TELEGRAM_TARGET", "MAGNETO_NOTIFY_TELEGRAM_CONFIG"),
        ("twilio", "MAGNETO_NOTIFY_TWILIO_TARGET", "MAGNETO_NOTIFY_TWILIO_CONFIG"),
        ("whatsapp", "MAGNETO_NOTIFY_WHATSAPP_TARGET", "MAGNETO_NOTIFY_WHATSAPP_CONFIG"),
    ):
        target = os.environ.get(target_var) or None
        if target:
            routes.append((service, target, os.environ.get(config_var) or None))

    email_target = (
        os.environ.get("MAGNETO_NOTIFY_EMAIL_TARGET")
        or os.environ.get("MAGNETO_NOTIFY_GMAIL_TARGET")
        or None
    )
    if email_target:
        routes.append(
            (
                "gmail-imap",
                email_target,
                os.environ.get("MAGNETO_NOTIFY_EMAIL_CONFIG")
                or os.environ.get("MAGNETO_NOTIFY_GMAIL_CONFIG")
                or None,
            )
        )

    return tuple(routes)
