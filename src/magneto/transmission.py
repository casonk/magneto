"""Transmission RPC client and display helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import requests

SESSION_HEADER = "X-Transmission-Session-Id"

TORRENT_FIELDS = [
    "id",
    "hashString",
    "name",
    "status",
    "percentDone",
    "metadataPercentComplete",
    "eta",
    "rateDownload",
    "rateUpload",
    "totalSize",
    "downloadedEver",
    "uploadedEver",
    "uploadRatio",
    "uploadLimited",
    "uploadLimit",
    "seedRatioLimit",
    "seedRatioMode",
    "error",
    "errorString",
    "downloadDir",
    "addedDate",
    "doneDate",
    "isFinished",
    "leftUntilDone",
    "peersConnected",
    "peersSendingToUs",
    "trackerStats",
]

STATUS_LABELS = {
    0: "Paused",
    1: "Queued check",
    2: "Checking",
    3: "Queued",
    4: "Downloading",
    5: "Queued seed",
    6: "Seeding",
}


class TransmissionError(RuntimeError):
    """Raised when Transmission rejects or cannot complete an RPC call."""


class ResponseLike(Protocol):
    status_code: int
    headers: dict[str, str]
    text: str

    def json(self) -> dict[str, Any]: ...

    def raise_for_status(self) -> None: ...


class Transport(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        timeout: float | None = None,
    ) -> ResponseLike: ...


@dataclass
class TransmissionClient:
    url: str
    username: str | None = None
    password: str | None = None
    timeout: float = 10.0
    transport: Transport = requests
    session_id: str | None = None

    @property
    def auth(self) -> tuple[str, str] | None:
        if self.username:
            return (self.username, self.password or "")
        return None

    def call(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"method": method, "arguments": arguments or {}}
        response = self._post(payload)
        if response.status_code == 409:
            self.session_id = response.headers.get(SESSION_HEADER)
            if not self.session_id:
                raise TransmissionError(
                    "Transmission requested a session id but did not return one."
                )
            response = self._post(payload)

        try:
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - convert transport/json errors for UI display.
            raise TransmissionError(f"Transmission RPC request failed: {exc}") from exc

        result = data.get("result")
        if result != "success":
            raise TransmissionError(str(result or "Transmission RPC returned an error."))
        return dict(data.get("arguments") or {})

    def _post(self, payload: dict[str, Any]) -> ResponseLike:
        headers = {SESSION_HEADER: self.session_id} if self.session_id else None
        try:
            return self.transport.post(
                self.url,
                json=payload,
                headers=headers,
                auth=self.auth,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TransmissionError(f"Transmission RPC request failed: {exc}") from exc

    def list_torrents(self) -> list[dict[str, Any]]:
        args = self.call("torrent-get", {"fields": TORRENT_FIELDS})
        torrents = args.get("torrents") or []
        return [normalize_torrent(torrent) for torrent in torrents]

    def add_magnet(self, magnet: str, download_dir: str) -> dict[str, Any]:
        return self.call(
            "torrent-add",
            {"filename": magnet.strip(), "download-dir": download_dir},
        )

    def add_torrent_file(self, content: bytes, download_dir: str) -> dict[str, Any]:
        return self.call(
            "torrent-add",
            {
                "metainfo": base64.b64encode(content).decode("ascii"),
                "download-dir": download_dir,
            },
        )

    def pause(self, torrent_id: int) -> None:
        self.call("torrent-stop", {"ids": [torrent_id]})

    def resume(self, torrent_id: int) -> None:
        self.call("torrent-start", {"ids": [torrent_id]})

    def reannounce(self, torrent_id: int) -> None:
        self.call("torrent-reannounce", {"ids": [torrent_id]})

    def restart(self, torrent_id: int) -> None:
        self.call("torrent-stop", {"ids": [torrent_id]})
        self.call("torrent-start", {"ids": [torrent_id]})

    def set_upload_limit(self, torrent_id: int, *, enabled: bool, kbps: int) -> None:
        self.call(
            "torrent-set",
            {
                "ids": [torrent_id],
                "uploadLimited": enabled,
                "uploadLimit": max(kbps, 0),
            },
        )

    def set_seed_ratio(self, torrent_id: int, *, enabled: bool, ratio: float = 0.0) -> None:
        self.call(
            "torrent-set",
            {
                "ids": [torrent_id],
                "seedRatioLimit": max(ratio, 0.0),
                "seedRatioMode": 1 if enabled else 0,
            },
        )

    def remove(self, torrent_id: int, *, delete_local_data: bool) -> None:
        self.call(
            "torrent-remove",
            {"ids": [torrent_id], "delete-local-data": delete_local_data},
        )


def normalize_torrent(torrent: dict[str, Any]) -> dict[str, Any]:
    percent_done = float(torrent.get("percentDone") or 0.0)
    metadata_percent = float(torrent.get("metadataPercentComplete") or 0.0)
    total_size = int(torrent.get("totalSize") or 0)
    downloaded = int(torrent.get("downloadedEver") or 0)
    left = int(torrent.get("leftUntilDone") or 0)
    eta = int(torrent.get("eta") or -1)
    status = int(torrent.get("status") or 0)
    error = int(torrent.get("error") or 0)
    upload_limited = bool(torrent.get("uploadLimited") or False)
    upload_limit = int(torrent.get("uploadLimit") or 0)
    seed_ratio_mode = int(torrent.get("seedRatioMode") or 0)
    seed_ratio_limit = float(torrent.get("seedRatioLimit") or 0.0)

    label = STATUS_LABELS.get(status, f"Status {status}")
    if error:
        label = "Error"
    elif status == 4 and metadata_percent < 1 and total_size == 0:
        label = "Fetching metadata"

    return {
        **torrent,
        "statusLabel": label,
        "statusClass": _status_class(status, error),
        "percentText": f"{percent_done * 100:.1f}%",
        "percentValue": round(percent_done * 100, 1),
        "metadataText": f"{metadata_percent * 100:.1f}%",
        "totalSizeText": format_bytes(total_size),
        "downloadedText": format_bytes(downloaded),
        "uploadedText": format_bytes(int(torrent.get("uploadedEver") or 0)),
        "leftText": format_bytes(left),
        "etaText": format_eta(eta),
        "rateDownloadText": f"{format_bytes(int(torrent.get('rateDownload') or 0))}/s",
        "rateUploadText": f"{format_bytes(int(torrent.get('rateUpload') or 0))}/s",
        "uploadLimited": upload_limited,
        "uploadLimitKbps": upload_limit,
        "uploadLimitText": f"{upload_limit} KB/s" if upload_limited else "Unlimited",
        "seedRatioMode": seed_ratio_mode,
        "seedRatioLimit": seed_ratio_limit,
        "seedLimitEnabled": seed_ratio_mode == 1,
        "seedLimitText": f"{seed_ratio_limit:g}" if seed_ratio_mode == 1 else "Global",
        "addedText": format_timestamp(int(torrent.get("addedDate") or 0)),
        "doneText": format_timestamp(int(torrent.get("doneDate") or 0)),
        "trackerStatus": tracker_status(torrent.get("trackerStats") or []),
    }


def _status_class(status: int, error: int) -> str:
    if error:
        return "error"
    if status == 0:
        return "paused"
    if status in {4, 6}:
        return "active"
    return "queued"


def format_bytes(size: int) -> str:
    value = float(max(size, 0))
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def format_eta(seconds: int) -> str:
    if seconds < 0:
        return "-"
    if seconds == 0:
        return "now"
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    days, hour = divmod(hours, 24)
    if days:
        return f"{days}d {hour}h"
    if hours:
        return f"{hours}h {minute}m"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def format_timestamp(value: int) -> str:
    if not value:
        return "-"
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def tracker_status(tracker_stats: list[dict[str, Any]]) -> str:
    for tracker in tracker_stats:
        announce_result = str(tracker.get("lastAnnounceResult") or "").strip()
        scrape_result = str(tracker.get("lastScrapeResult") or "").strip()
        if tracker.get("lastAnnounceSucceeded"):
            host = str(tracker.get("host") or "tracker").strip()
            peers = int(tracker.get("lastAnnouncePeerCount") or 0)
            return f"{host}: {peers} peer(s) announced"
        for result in (announce_result, scrape_result):
            if result:
                host = str(tracker.get("host") or "tracker").strip()
                return f"{host}: {result}"
    return ""
