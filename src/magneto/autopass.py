"""Credential resolution through the local auto-pass repo."""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_AUTO_PASS_ROOT = Path(__file__).resolve().parents[3] / "auto-pass"
DEFAULT_AUTO_PASS_ENV_FILE = Path("config/auto-pass.env.local")


class AutoPassCredentialError(RuntimeError):
    """Raised when Transmission credentials cannot be resolved from auto-pass."""


def resolve_auto_pass_credentials(
    entry: str,
    *,
    profile: str | None = None,
    root: str | Path | None = None,
    env_file: str | Path | None = None,
    username_field: str = "username",
    password_field: str = "password",
) -> tuple[str | None, str]:
    """Resolve a Transmission username/password pair from auto-pass."""

    entry_name = str(entry or "").strip()
    if not entry_name:
        raise AutoPassCredentialError("MAGNETO_TRANSMISSION_KEEPASS_ENTRY is blank.")

    auto_pass_root = Path(root).expanduser() if root else DEFAULT_AUTO_PASS_ROOT
    auto_pass_src = auto_pass_root / "src"
    if auto_pass_src.is_dir():
        src_text = str(auto_pass_src)
        if src_text not in sys.path:
            sys.path.insert(0, src_text)

    try:
        from auto_pass.envfile import load_config_environment  # noqa: PLC0415
        from auto_pass.keepassxc import (  # noqa: PLC0415
            KeepassCommandError,
            resolve_keepassxc_entry,
        )
    except ImportError as exc:
        raise AutoPassCredentialError(
            f"auto-pass is not importable; expected it under {auto_pass_root}."
        ) from exc

    auto_pass_env = (
        Path(env_file).expanduser() if env_file else auto_pass_root / DEFAULT_AUTO_PASS_ENV_FILE
    )
    load_config_environment(auto_pass_env, profile=profile or None)

    try:
        result = resolve_keepassxc_entry(
            entry_name,
            attrs_map={
                "username": username_field,
                "password": password_field,
            },
        )
    except KeepassCommandError as exc:
        raise AutoPassCredentialError(
            f"could not resolve Transmission credentials from auto-pass entry {entry_name!r}: {exc}"
        ) from exc

    username = str(result.get("username", "")).strip() or None
    password = str(result.get("password", ""))
    if not password:
        raise AutoPassCredentialError(
            f"auto-pass entry {entry_name!r} did not return a Transmission password."
        )
    return username, password
