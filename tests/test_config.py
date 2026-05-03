from __future__ import annotations

import pytest

from magneto.config import AppConfig, ConfigurationError


def test_from_env_resolves_transmission_auth_from_auto_pass(monkeypatch, tmp_path):
    calls = []

    def fake_resolver(entry, **kwargs):
        calls.append({"entry": entry, **kwargs})
        return "rpc-user", "rpc-password"

    monkeypatch.setenv("MAGNETO_TRANSMISSION_KEEPASS_PROFILE", "infra")
    monkeypatch.setenv("MAGNETO_TRANSMISSION_KEEPASS_ENTRY", "magneto@transmission")
    monkeypatch.setenv("MAGNETO_AUTO_PASS_ROOT", str(tmp_path / "auto-pass"))
    monkeypatch.setattr("magneto.config.resolve_auto_pass_credentials", fake_resolver)

    config = AppConfig.from_env()

    assert config.username == "rpc-user"
    assert config.password == "rpc-password"
    assert calls == [
        {
            "entry": "magneto@transmission",
            "profile": "infra",
            "root": str(tmp_path / "auto-pass"),
            "env_file": None,
            "username_field": "username",
            "password_field": "password",
        }
    ]


def test_from_env_keeps_explicit_username_with_auto_pass_password(monkeypatch):
    def fake_resolver(_entry, **_kwargs):
        return "keepass-user", "rpc-password"

    monkeypatch.setenv("MAGNETO_TRANSMISSION_KEEPASS_ENTRY", "magneto@transmission")
    monkeypatch.setenv("MAGNETO_TRANSMISSION_USERNAME", "explicit-user")
    monkeypatch.setattr("magneto.config.resolve_auto_pass_credentials", fake_resolver)

    config = AppConfig.from_env()

    assert config.username == "explicit-user"
    assert config.password == "rpc-password"


def test_from_env_requires_username_when_auto_pass_returns_password_only(monkeypatch):
    def fake_resolver(_entry, **_kwargs):
        return None, "rpc-password"

    monkeypatch.setenv("MAGNETO_TRANSMISSION_KEEPASS_ENTRY", "magneto@transmission")
    monkeypatch.setattr("magneto.config.resolve_auto_pass_credentials", fake_resolver)

    with pytest.raises(ConfigurationError, match="no username"):
        AppConfig.from_env()


def test_from_env_enables_notifications_when_target_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("MAGNETO_NOTIFY_TARGET", "+15551234567")
    monkeypatch.setenv("MAGNETO_SHOCK_RELAY_ROOT", str(tmp_path / "shock-relay"))
    monkeypatch.setenv("MAGNETO_NOTIFY_SERVICE", "telegram")
    monkeypatch.setenv("MAGNETO_NOTIFY_CONFIG", str(tmp_path / "telegram.yaml"))
    monkeypatch.setenv("MAGNETO_NOTIFY_STATE_FILE", str(tmp_path / "state.json"))

    config = AppConfig.from_env()

    assert config.notify_enabled is True
    assert config.notify_target == "+15551234567"
    assert config.notify_shock_relay_root == str(tmp_path / "shock-relay")
    assert config.notify_service == "telegram"
    assert config.notify_config_path == str(tmp_path / "telegram.yaml")
    assert config.notify_state_file == str(tmp_path / "state.json")


def test_from_env_reads_multi_route_notification_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MAGNETO_NOTIFY_SIGNAL_TARGET", "+15551234567")
    monkeypatch.setenv(
        "MAGNETO_NOTIFY_SIGNAL_CONFIG",
        str(tmp_path / "shock-relay/services/signal-cli/config.local.yaml"),
    )
    monkeypatch.setenv("MAGNETO_NOTIFY_EMAIL_TARGET", "user@example.com")
    monkeypatch.setenv(
        "MAGNETO_NOTIFY_EMAIL_CONFIG",
        str(tmp_path / "shock-relay/services/gmail-imap/config.local.yaml"),
    )
    monkeypatch.setenv("MAGNETO_NOTIFY_TAG", "magneto/notify")

    config = AppConfig.from_env()

    assert config.notify_enabled is True
    assert config.notify_tag == "magneto/notify"
    assert config.notify_routes == (
        (
            "signal",
            "+15551234567",
            str(tmp_path / "shock-relay/services/signal-cli/config.local.yaml"),
        ),
        (
            "gmail-imap",
            "user@example.com",
            str(tmp_path / "shock-relay/services/gmail-imap/config.local.yaml"),
        ),
    )
