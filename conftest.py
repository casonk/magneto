"""pytest configuration — activate dyno-lab shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

DYNO_LAB_SRC = Path(__file__).resolve().parent.parent / "dyno-lab" / "src"
if DYNO_LAB_SRC.exists():
    sys.path.insert(0, str(DYNO_LAB_SRC))

pytest_plugins = ["dyno_lab.fixtures"]
