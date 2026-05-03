"""Runtime configuration for magneto."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from magneto.autopass import AutoPassCredentialError, resolve_auto_pass_credentials


class ConfigurationError(RuntimeError):
    """Raised when magneto runtime configuration is invalid."""


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
        )

    @property
    def download_path(self) -> Path:
        return Path(self.download_dir).expanduser()


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
