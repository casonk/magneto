"""Defaults for newly added torrents, editable from the web page.

The environment (``MAGNETO_DEFAULT_*`` and ``MAGNETO_NO_SEED_BY_DEFAULT``) sets
the starting values. Whatever is saved from the page overrides them, so the
service never needs an environment change and restart to adjust a default. The
saved file holds only these four values.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from magneto.config import AppConfig


@dataclass(frozen=True)
class Defaults:
    download_kbps: int = 0
    upload_kbps: int = 0
    seed_ratio: float | None = None
    no_seed: bool = False


def from_config(config: AppConfig) -> Defaults:
    return Defaults(
        download_kbps=config.default_download_limit_kbps,
        upload_kbps=config.default_upload_limit_kbps,
        seed_ratio=config.default_seed_ratio,
        no_seed=config.no_seed_by_default,
    )


def load(config: AppConfig) -> Defaults:
    """The environment's defaults with any saved values laid over them."""
    base = from_config(config)
    if not config.settings_file:
        return base
    saved: dict = {}
    with contextlib.suppress(OSError, ValueError):
        loaded = json.loads(Path(config.settings_file).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            saved = loaded
    values = asdict(base)
    for key in values:
        if key in saved:
            values[key] = saved[key]
    with contextlib.suppress(TypeError, ValueError):
        return Defaults(
            download_kbps=int(values["download_kbps"] or 0),
            upload_kbps=int(values["upload_kbps"] or 0),
            seed_ratio=float(values["seed_ratio"]) if values["seed_ratio"] else None,
            no_seed=bool(values["no_seed"]),
        )
    return base


def save(config: AppConfig, defaults: Defaults) -> None:
    if not config.settings_file:
        raise OSError("no settings file is configured")
    path = Path(config.settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(defaults), sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
