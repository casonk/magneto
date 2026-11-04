"""Magneto refuses requests whose Host is not one it is reached by (DNS rebinding)."""

from __future__ import annotations

import pytest

from magneto.config import AppConfig
from magneto.web import create_app


class FakeTransmission:
    def __init__(self):
        self.calls = []

    def list_torrents(self):
        return []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def make_client(tmp_path, **overrides):
    fake = FakeTransmission()
    config = AppConfig(
        transmission_url="http://example/rpc",
        download_dir=str(tmp_path / "downloads"),
        secret_key="test-secret",
        settings_file=str(tmp_path / "settings.json"),
        **overrides,
    )
    return create_app(config, client=fake).test_client(), fake


def token(client) -> str:
    assert client.get("/").status_code == 200
    with client.session_transaction() as session:
        return session["csrf_token"]


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)[0]


def test_a_rebinding_request_is_refused_for_every_method_even_with_a_valid_token(tmp_path):
    client, fake = make_client(tmp_path)
    csrf = token(client)
    rebind = {"Host": "evil.example", "Origin": "http://evil.example", "X-CSRF-Token": csrf}
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(
            "/torrents/1/remove", data={"csrf_token": csrf}, headers=rebind
        )
        assert response.status_code == 403, method
    assert fake.calls == []


@pytest.mark.parametrize("host", ["localhost", "localhost:5400", "127.0.0.1:5400", "[::1]:5400"])
def test_loopback_hosts_are_answered(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host", ["localhost.evil.example", "127.0.0.1.evil.example", "evil.example:5400", ""]
)
def test_lookalike_hosts_are_refused(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 403


def test_forwarded_headers_never_authorise_a_request(client):
    headers = {"Host": "evil.example", "X-Forwarded-Host": "localhost", "X-Forwarded-Proto": "http"}
    assert client.get("/", headers=headers).status_code == 403


def test_configured_public_and_allowed_origin_hosts_are_answered(tmp_path):
    client, _ = make_client(
        tmp_path,
        public_origin="https://magneto.example.test",
        allowed_origins=("https://alt.example.test:8443",),
    )
    for host in ("magneto.example.test", "alt.example.test:8443", "Magneto.Example.Test"):
        assert client.get("/", headers={"Host": host}).status_code == 200, host
    assert client.get("/", headers={"Host": "other.example.test"}).status_code == 403


def test_the_registered_hostname_is_answered(tmp_path, monkeypatch):
    entry = tmp_path / "owner__repo"
    entry.mkdir()
    (entry / "site.local.toml").write_text('[site]\nhostname = "registered.example.test"\n')
    monkeypatch.setenv("PORTFOLIO_SITE_DIR", str(entry))
    monkeypatch.setenv("PORTFOLIO_STORE", str(tmp_path))
    client, _ = make_client(tmp_path)
    assert client.get("/", headers={"Host": "registered.example.test"}).status_code == 200
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_the_refusal_does_not_echo_the_host_header(client):
    response = client.get("/", headers={"Host": "<b>x</b>.example"})
    assert response.status_code == 403 and b"<b>x</b>" not in response.data
