from __future__ import annotations

from dataclasses import dataclass, field

from magneto.config import AppConfig, TorrentHost
from magneto.service import ServiceRestartError
from magneto.transmission import TransmissionError
from magneto.web import create_app


@dataclass
class FakeClient:
    calls: list[tuple] = field(default_factory=list)

    def list_torrents(self):
        return [
            {
                "id": 3,
                "name": "ubuntu.iso",
                "statusLabel": "Downloading",
                "statusClass": "active",
                "percentText": "50.0%",
                "percentValue": 50,
                "rateDownloadText": "1.0 MB/s",
                "rateUploadText": "0 B/s",
                "totalSizeText": "2.0 GB",
                "downloadedText": "1.0 GB",
                "uploadedText": "128.0 MB",
                "leftText": "1.0 GB",
                "etaText": "20m",
                "peersConnected": 4,
                "metadataText": "100.0%",
                "uploadLimited": False,
                "uploadLimitKbps": 0,
                "uploadLimitText": "Unlimited",
                "downloadLimited": False,
                "downloadLimitKbps": 0,
                "downloadLimitText": "Unlimited",
                "seedLimitEnabled": False,
                "seedRatioLimit": 0,
                "seedLimitText": "Global",
                "errorString": "",
            }
        ]

    def call(self, method):
        self.calls.append(("call", method))
        return {}

    def add_magnet(self, magnet, download_dir, *, no_seed=False):
        self.calls.append(("add_magnet", magnet, download_dir))

    def add_torrent_file(self, content, download_dir, *, no_seed=False):
        self.calls.append(("add_torrent_file", content, download_dir))

    def pause(self, torrent_id):
        self.calls.append(("pause", torrent_id))

    def resume(self, torrent_id):
        self.calls.append(("resume", torrent_id))

    def restart(self, torrent_id):
        self.calls.append(("restart", torrent_id))

    def reannounce(self, torrent_id):
        self.calls.append(("reannounce", torrent_id))

    def set_upload_limit(self, torrent_id, *, enabled, kbps):
        self.calls.append(("set_upload_limit", torrent_id, enabled, kbps))

    def set_download_limit(self, torrent_id, *, enabled, kbps):
        self.calls.append(("set_download_limit", torrent_id, enabled, kbps))

    def set_seed_ratio(self, torrent_id, *, enabled, ratio=0.0):
        self.calls.append(("set_seed_ratio", torrent_id, enabled, ratio))

    def remove(self, torrent_id, *, delete_local_data):
        self.calls.append(("remove", torrent_id, delete_local_data))


def _app(tmp_path, fake_client):
    return create_app(
        AppConfig(
            transmission_url="http://example/rpc",
            download_dir=str(tmp_path / "downloads"),
            secret_key="test-secret",
        ),
        client=fake_client,
    )


def _csrf(client, *, base_url=None):
    response = client.get("/", base_url=base_url)
    assert response.status_code == 200
    session_kwargs = {"base_url": base_url} if base_url else {}
    with client.session_transaction(**session_kwargs) as session:
        return session["csrf_token"]


def test_index_renders_mobile_controls(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)

    response = app.test_client().get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ubuntu.iso" in text
    assert "Pause" in text
    assert "Cancel" in text
    assert "Reannounce" in text
    assert "2.0 GB" in text
    assert "128.0 MB" in text
    assert "Upload KB/s" in text
    assert "Download rate" in text
    assert 'id="torrent-3"' in text
    assert "No seed" in text
    assert str(tmp_path / "downloads") in text
    assert 'data-refresh-url="/torrents/fragment"' in text


def test_index_renders_torrent_host_selector(tmp_path):
    fake_client = FakeClient()
    app = create_app(
        AppConfig(
            transmission_url="http://example/rpc",
            download_dir=str(tmp_path / "downloads"),
            secret_key="test-secret",
            torrent_hosts=(
                TorrentHost("air", "MacBook Air", "https://torrents.air.internal/", current=True),
                TorrentHost("home", "Home server", "https://torrents.home.internal/"),
            ),
        ),
        client=fake_client,
    )

    response = app.test_client().get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "data-torrent-host" in text
    assert 'value="https://torrents.air.internal/" selected' in text
    assert "Home server" in text


def test_torrent_fragment_renders_list_without_page_shell(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)

    response = app.test_client().get("/torrents/fragment")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "ubuntu.iso" in text
    assert "<main" not in text


def test_failed_refresh_shows_restart_control(tmp_path):
    class UnavailableClient(FakeClient):
        def list_torrents(self):
            raise TransmissionError("RPC timed out")

    app = _app(tmp_path, UnavailableClient())
    response = app.test_client().get("/torrents/fragment")
    text = response.get_data(as_text=True)

    assert response.status_code == 502
    assert "RPC timed out" in text
    assert 'action="/transmission/restart"' in text
    assert 'name="csrf_token"' in text


def test_transmission_health_checks_rpc(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)

    response = app.test_client().get("/healthz/transmission")

    assert response.status_code == 200
    assert fake_client.calls == [("call", "session-get")]


def test_transmission_health_reports_rpc_failure(tmp_path):
    class UnavailableClient(FakeClient):
        def call(self, method):
            raise TransmissionError("RPC timed out")

    app = _app(tmp_path, UnavailableClient())

    response = app.test_client().get("/healthz/transmission")

    assert response.status_code == 503
    assert response.json == {"ok": False, "error": "RPC timed out"}


def test_restart_service_requires_csrf_and_calls_fixed_runner(tmp_path):
    calls = []
    app = create_app(
        AppConfig("http://example/rpc", str(tmp_path / "downloads"), "test-secret"),
        client=FakeClient(),
        restart_service=lambda: calls.append("restart"),
    )
    client = app.test_client()

    denied = client.post("/transmission/restart", headers={"Origin": "http://localhost"})
    token = _csrf(client)
    accepted = client.post(
        "/transmission/restart",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert denied.status_code == 403
    assert accepted.status_code == 302
    assert calls == ["restart"]


def test_restart_service_error_is_shown(tmp_path):
    def reject():
        raise ServiceRestartError("Restart permission missing")

    app = create_app(
        AppConfig("http://example/rpc", str(tmp_path / "downloads"), "test-secret"),
        client=FakeClient(),
        restart_service=reject,
    )
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/transmission/restart",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Restart permission missing" in response.get_data(as_text=True)


def test_add_magnet_uses_configured_download_dir(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents",
        data={"csrf_token": token, "magnet": "magnet:?xt=urn:btih:abcd"},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [
        ("add_magnet", "magnet:?xt=urn:btih:abcd", str(tmp_path / "downloads"))
    ]


def test_add_magnet_does_not_require_web_user_download_dir_access(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        fake_client = FakeClient()
        app = create_app(
            AppConfig(
                transmission_url="http://example/rpc",
                download_dir=str(locked / "downloads"),
                secret_key="test-secret",
            ),
            client=fake_client,
        )
        client = app.test_client()
        token = _csrf(client)

        response = client.post(
            "/torrents",
            data={"csrf_token": token, "magnet": "magnet:?xt=urn:btih:abcd"},
            headers={"Origin": "http://localhost"},
        )
    finally:
        locked.chmod(0o700)

    assert response.status_code == 302
    assert fake_client.calls == [
        ("add_magnet", "magnet:?xt=urn:btih:abcd", str(locked / "downloads"))
    ]


def test_cancel_deletes_local_data(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/cancel",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [("remove", 3, True)]


def test_remove_keeps_local_data(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/remove",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [("remove", 3, False)]


def test_reannounce_action_requests_tracker_retry(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/reannounce",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [("reannounce", 3)]


def test_no_seed_action_disables_upload_and_sets_zero_seed_ratio(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/no-seed",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [
        ("set_seed_ratio", 3, True, 0.0),
        ("set_upload_limit", 3, True, 0),
    ]


def test_allow_seed_action_restores_global_seed_policy(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/allow-seed",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [
        ("set_seed_ratio", 3, False, 0.0),
        ("set_upload_limit", 3, False, 0),
    ]


def test_throttle_upload_action_sets_limit(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/throttle-upload",
        data={"csrf_token": token, "upload_limit_kbps": "42"},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [("set_upload_limit", 3, True, 42)]


def test_throttle_download_action_sets_limit_or_unlimited(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    limited = client.post(
        "/torrents/3/throttle-download",
        data={"csrf_token": token, "download_limit_kbps": "512"},
        headers={"Origin": "http://localhost"},
    )
    unlimited = client.post(
        "/torrents/3/throttle-download",
        data={"csrf_token": token, "download_limit_kbps": "0"},
        headers={"Origin": "http://localhost"},
    )

    assert limited.status_code == unlimited.status_code == 302
    assert fake_client.calls == [
        ("set_download_limit", 3, True, 512),
        ("set_download_limit", 3, False, 0),
    ]


def test_throttle_download_action_rejects_invalid_limit(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/throttle-download",
        data={"csrf_token": token, "download_limit_kbps": "-1"},
        headers={"Origin": "http://localhost"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Download limit must be between" in response.get_data(as_text=True)
    assert fake_client.calls == []


def test_seed_ratio_action_sets_a_target_or_the_global_default(tmp_path):
    fake_client = FakeClient()
    client = _app(tmp_path, fake_client).test_client()
    token = _csrf(client)

    for value in ("2", "0.5", "global"):
        response = client.post(
            "/torrents/3/seed-ratio",
            data={"csrf_token": token, "seed_ratio": value},
            headers={"Origin": "http://localhost"},
        )
        assert response.status_code == 302

    assert fake_client.calls == [
        ("set_seed_ratio", 3, True, 2.0),
        ("set_seed_ratio", 3, True, 0.5),
        ("set_seed_ratio", 3, False, 0.0),
    ]


def test_seed_ratio_action_rejects_zero_and_junk(tmp_path):
    fake_client = FakeClient()
    client = _app(tmp_path, fake_client).test_client()
    token = _csrf(client)

    for value, message in (
        ("0", "use No seed"),
        ("-1", "greater than 0"),
        ("abc", "must be a number"),
    ):
        response = client.post(
            "/torrents/3/seed-ratio",
            data={"csrf_token": token, "seed_ratio": value},
            headers={"Origin": "http://localhost"},
            follow_redirects=True,
        )
        assert message in response.get_data(as_text=True)

    assert fake_client.calls == []


def test_index_offers_a_target_seed_ratio_control(tmp_path):
    html = _app(tmp_path, FakeClient()).test_client().get("/").get_data(as_text=True)

    assert 'name="seed_ratio"' in html and "Target seed ratio" in html
    assert '<option value="global" selected>Global default</option>' in html


class AddingClient(FakeClient):
    def __init__(self, result, fail_on=None):
        super().__init__()
        self.result = result
        self.fail_on = fail_on

    def add_magnet(self, magnet, download_dir, *, no_seed=False):
        self.calls.append(("add_magnet", magnet))
        return self.result

    def set_download_limit(self, torrent_id, *, enabled, kbps):
        if self.fail_on == "download":
            raise TransmissionError("rpc down")
        super().set_download_limit(torrent_id, enabled=enabled, kbps=kbps)


def _defaults_app(tmp_path, client, **overrides):
    config = AppConfig(
        transmission_url="http://example/rpc",
        download_dir=str(tmp_path / "downloads"),
        secret_key="test-secret",
        default_download_limit_kbps=512,
        default_upload_limit_kbps=64,
        default_seed_ratio=2.0,
        **overrides,
    )
    return create_app(config, client=client).test_client()


MAGNET = "magnet:?xt=urn:btih:" + "a" * 40


def _add(client, follow=False):
    token = _csrf(client)
    return client.post(
        "/torrents",
        data={"csrf_token": token, "magnet": MAGNET},
        headers={"Origin": "http://localhost"},
        follow_redirects=follow,
    )


def test_new_torrents_get_the_configured_defaults(tmp_path):
    fake = AddingClient({"torrent-added": {"id": 9}})
    _add(_defaults_app(tmp_path, fake))

    assert fake.calls == [
        ("add_magnet", MAGNET),
        ("set_download_limit", 9, True, 512),
        ("set_upload_limit", 9, True, 64),
        ("set_seed_ratio", 9, True, 2.0),
    ]


def test_defaults_are_not_applied_to_a_duplicate_or_an_unknown_result(tmp_path):
    for result in ({"torrent-duplicate": {"id": 4}}, {}, None):
        fake = AddingClient(result)
        _add(_defaults_app(tmp_path, fake))
        assert fake.calls == [("add_magnet", MAGNET)]


def test_no_seed_by_default_wins_over_the_upload_and_ratio_defaults(tmp_path):
    fake = AddingClient({"torrent-added": {"id": 9}})
    _add(_defaults_app(tmp_path, fake, no_seed_by_default=True))

    assert fake.calls == [("add_magnet", MAGNET), ("set_download_limit", 9, True, 512)]


def test_a_failed_default_does_not_fail_the_add(tmp_path):
    fake = AddingClient({"torrent-added": {"id": 9}}, fail_on="download")
    response = _add(_defaults_app(tmp_path, fake), follow=True)

    text = response.get_data(as_text=True)
    assert "Torrent added." in text and "default limits were not applied" in text


def test_state_change_requires_csrf(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)

    response = app.test_client().post(
        "/torrents/3/pause",
        data={},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 403
    assert fake_client.calls == []


def test_state_change_allows_configured_public_origin(tmp_path):
    fake_client = FakeClient()
    app = create_app(
        AppConfig(
            transmission_url="http://example/rpc",
            download_dir=str(tmp_path / "downloads"),
            secret_key="test-secret",
            public_origin="https://torrents.snowbridge.internal",
        ),
        client=fake_client,
    )
    client = app.test_client()
    token = _csrf(client, base_url="http://127.0.0.1:5400")

    response = client.post(
        "/torrents",
        data={"csrf_token": token, "magnet": "magnet:?xt=urn:btih:abcd"},
        headers={"Origin": "https://torrents.snowbridge.internal"},
        base_url="http://127.0.0.1:5400",
    )

    assert response.status_code == 302
    assert fake_client.calls == [
        ("add_magnet", "magnet:?xt=urn:btih:abcd", str(tmp_path / "downloads"))
    ]


def test_state_change_allows_forwarded_public_origin(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client, base_url="http://127.0.0.1:5400")

    response = client.post(
        "/torrents/3/pause",
        data={"csrf_token": token},
        headers={
            "Origin": "https://torrents.snowbridge.internal",
            "X-Forwarded-Host": "torrents.snowbridge.internal",
            "X-Forwarded-Proto": "https",
        },
        base_url="http://127.0.0.1:5400",
    )

    assert response.status_code == 302
    assert fake_client.calls == [("pause", 3)]


def test_state_change_allows_null_origin_with_valid_csrf(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client)

    response = client.post(
        "/torrents/3/pause",
        data={"csrf_token": token},
        headers={"Origin": "null"},
    )

    assert response.status_code == 302
    assert fake_client.calls == [("pause", 3)]


def test_state_change_allows_loopback_hostname_alias(tmp_path):
    fake_client = FakeClient()
    app = _app(tmp_path, fake_client)
    client = app.test_client()
    token = _csrf(client, base_url="http://127.0.0.1:5400")

    response = client.post(
        "/torrents/3/pause",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost:5400"},
        base_url="http://127.0.0.1:5400",
    )

    assert response.status_code == 302
    assert fake_client.calls == [("pause", 3)]
