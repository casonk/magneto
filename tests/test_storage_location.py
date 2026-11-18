"""Where Magneto downloads: the configured directory is honoured, torrents elsewhere are not filed, and (on a machine
with a local settings file) the download and library directories sit on a spinning disk, not SSD or NVMe.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from magneto.config import AppConfig
from magneto.library import is_ready_to_file

LOCAL_ENV = Path(__file__).resolve().parent.parent / "config" / "magneto.env.local"


def _complete(download_dir: str) -> dict:
    return {
        "downloadDir": download_dir,
        "percentDone": 1.0,
        "leftUntilDone": 0,
        "error": 0,
        "status": 6,
    }


def test_download_dir_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAGNETO_DOWNLOAD_DIR", "/mnt/example-hdd/torrents")
    monkeypatch.setenv("MAGNETO_TRANSMISSION_PASSWORD", "x")
    assert AppConfig.from_env().download_dir == "/mnt/example-hdd/torrents"


def test_only_torrents_in_the_configured_dir_are_filed():
    """After the download dir moves, a torrent still recorded under the old one is skipped: relocate it first."""
    new, old = "/mnt/example-hdd/torrents", "/srv/example/old"
    assert is_ready_to_file(_complete(new), new)
    assert is_ready_to_file(_complete(new + "/"), new)
    assert not is_ready_to_file(_complete(old), new)


def _env_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def _disk_kind(path: str) -> str:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    src = subprocess.run(
        ["findmnt", "-no", "SOURCE", "-T", str(p)], capture_output=True, text=True
    ).stdout.strip()
    src = src.split("[", 1)[0]
    if not src.startswith("/dev/"):
        return "unknown"
    out = subprocess.run(
        ["lsblk", "-s", "-n", "-o", "TYPE,ROTA", src], capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "disk":
            return {"1": "hdd", "0": "flash"}.get(parts[1], "unknown")
    return "unknown"


@pytest.mark.skipif(
    not LOCAL_ENV.is_file() or not (shutil.which("findmnt") and shutil.which("lsblk")),
    reason="needs this machine's ignored config/magneto.env.local and findmnt/lsblk",
)
@pytest.mark.parametrize("key", ["MAGNETO_DOWNLOAD_DIR", "MAGNETO_LIBRARY_DIR"])
def test_local_bulk_dirs_are_on_a_spinning_disk(key):
    value = _env_values(LOCAL_ENV).get(key)
    if not value:
        pytest.skip(f"{key} is not set locally")
    kind = _disk_kind(value)
    message = f"{key}={value} is on {kind} storage; bulk data belongs on a spinning disk"
    assert kind == "hdd", message
