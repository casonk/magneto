from __future__ import annotations

import pytest
import requests

from magneto.transmission import (
    SESSION_HEADER,
    TransmissionClient,
    TransmissionError,
    normalize_torrent,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"result": "success", "arguments": {}}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 409:
            raise RuntimeError(f"status {self.status_code}")


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json, headers=None, auth=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "auth": auth,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


class RaisingTransport:
    def post(self, url, *, json, headers=None, auth=None, timeout=None):
        raise requests.ConnectionError("connection refused")


def test_call_retries_with_transmission_session_id():
    transport = FakeTransport(
        [
            FakeResponse(409, headers={SESSION_HEADER: "abc"}),
            FakeResponse(payload={"result": "success", "arguments": {"ok": True}}),
        ]
    )
    client = TransmissionClient("http://example/rpc", transport=transport)

    assert client.call("session-get") == {"ok": True}
    assert transport.calls[0]["headers"] is None
    assert transport.calls[1]["headers"] == {SESSION_HEADER: "abc"}


def test_add_magnet_forces_configured_download_directory():
    transport = FakeTransport([FakeResponse()])
    client = TransmissionClient("http://example/rpc", transport=transport)

    client.add_magnet(" magnet:?xt=urn:btih:abcd ", "/srv/snowbridge/share/torrents")

    assert transport.calls[0]["json"] == {
        "method": "torrent-add",
        "arguments": {
            "filename": "magnet:?xt=urn:btih:abcd",
            "download-dir": "/srv/snowbridge/share/torrents",
        },
    }


def test_restart_stops_then_starts_torrent():
    transport = FakeTransport([FakeResponse(), FakeResponse()])
    client = TransmissionClient("http://example/rpc", transport=transport)

    client.restart(7)

    assert [call["json"]["method"] for call in transport.calls] == [
        "torrent-stop",
        "torrent-start",
    ]


def test_reannounce_requests_tracker_retry():
    transport = FakeTransport([FakeResponse()])
    client = TransmissionClient("http://example/rpc", transport=transport)

    client.reannounce(7)

    assert transport.calls[0]["json"] == {
        "method": "torrent-reannounce",
        "arguments": {"ids": [7]},
    }


def test_set_upload_limit_updates_per_torrent_limit():
    transport = FakeTransport([FakeResponse()])
    client = TransmissionClient("http://example/rpc", transport=transport)

    client.set_upload_limit(7, enabled=True, kbps=25)

    assert transport.calls[0]["json"] == {
        "method": "torrent-set",
        "arguments": {"ids": [7], "uploadLimited": True, "uploadLimit": 25},
    }


def test_set_seed_ratio_updates_per_torrent_seed_policy():
    transport = FakeTransport([FakeResponse()])
    client = TransmissionClient("http://example/rpc", transport=transport)

    client.set_seed_ratio(7, enabled=True, ratio=0.0)

    assert transport.calls[0]["json"] == {
        "method": "torrent-set",
        "arguments": {"ids": [7], "seedRatioLimit": 0.0, "seedRatioMode": 1},
    }


def test_rpc_error_raises_transmission_error():
    transport = FakeTransport([FakeResponse(payload={"result": "duplicate torrent"})])
    client = TransmissionClient("http://example/rpc", transport=transport)

    with pytest.raises(TransmissionError, match="duplicate torrent"):
        client.call("torrent-add")


def test_connection_error_raises_transmission_error():
    client = TransmissionClient("http://example/rpc", transport=RaisingTransport())

    with pytest.raises(TransmissionError, match="connection refused"):
        client.call("torrent-get")


def test_normalize_torrent_formats_display_fields():
    torrent = normalize_torrent(
        {
            "id": 1,
            "name": "demo",
            "status": 4,
            "percentDone": 0.25,
            "metadataPercentComplete": 1.0,
            "eta": 75,
            "rateDownload": 2048,
            "rateUpload": 1024,
            "totalSize": 4096,
            "downloadedEver": 1024,
            "uploadedEver": 512,
            "leftUntilDone": 3072,
            "peersConnected": 3,
            "uploadLimited": True,
            "uploadLimit": 25,
            "seedRatioMode": 1,
            "seedRatioLimit": 0.0,
        }
    )

    assert torrent["statusLabel"] == "Downloading"
    assert torrent["percentText"] == "25.0%"
    assert torrent["etaText"] == "1m 15s"
    assert torrent["rateDownloadText"] == "2.0 KB/s"
    assert torrent["totalSizeText"] == "4.0 KB"
    assert torrent["downloadedText"] == "1.0 KB"
    assert torrent["uploadedText"] == "512 B"
    assert torrent["uploadLimitText"] == "25 KB/s"
    assert torrent["seedLimitEnabled"] is True
    assert torrent["seedLimitText"] == "0"


def test_normalize_torrent_shows_metadata_and_tracker_status():
    torrent = normalize_torrent(
        {
            "id": 1,
            "name": "demo",
            "status": 4,
            "percentDone": 0.0,
            "metadataPercentComplete": 0.0,
            "totalSize": 0,
            "trackerStats": [
                {
                    "host": "tracker.example",
                    "lastAnnounceSucceeded": False,
                    "lastAnnounceResult": "IPv4 connection failed",
                }
            ],
        }
    )

    assert torrent["statusLabel"] == "Fetching metadata"
    assert torrent["metadataText"] == "0.0%"
    assert torrent["trackerStatus"] == "tracker.example: IPv4 connection failed"
