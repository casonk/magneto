"""The torrent list's auto-refresh must not discard a half-made choice."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "magneto" / "static" / "app.js"
HARNESS = ROOT / "tests" / "js" / "refresh_guard.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(scenario: str) -> dict:
    out = subprocess.run(
        ["node", str(HARNESS), str(APP_JS), scenario],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    return json.loads(out)


@pytest.mark.parametrize("scenario", ["typed", "select", "focused"])
def test_refresh_is_held_while_a_control_is_being_edited(scenario):
    result = run(scenario)
    assert result["fetches"] == 0
    assert result["editing"] is True
    assert result["html"] == ""


@pytest.mark.parametrize("scenario", ["untouched", "idle"])
def test_refresh_runs_when_nothing_is_being_edited(scenario):
    result = run(scenario)
    assert result["fetches"] == 1
    assert result["html"] == "<p>new</p>"
    assert result["editing"] is False
