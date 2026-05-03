"""Command line entry points for magneto."""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path

from magneto.config import AppConfig, ConfigurationError
from magneto.notifications import NotificationError, build_monitor
from magneto.web import create_app


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_host(host: str) -> bool:
    candidate = host.strip()
    if not candidate:
        return False
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if candidate.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _validate_bind(host: str) -> None:
    if _is_loopback_host(host):
        return
    if _truthy(os.environ.get("MAGNETO_ALLOW_REMOTE")):
        return
    raise SystemExit(
        "Refusing to bind magneto to a non-loopback host without MAGNETO_ALLOW_REMOTE=1."
    )


def _default_env_file() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "magneto.env.local"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _load_default_env() -> None:
    env_path = Path(os.environ.get("MAGNETO_ENV_FILE") or _default_env_file()).expanduser()
    _load_env_file(env_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="magneto")
    subparsers = parser.add_subparsers(dest="command")

    web = subparsers.add_parser("web", help="run the private web UI")
    web.add_argument("--host", default=os.environ.get("MAGNETO_HOST", "127.0.0.1"))
    web.add_argument("--port", type=int, default=int(os.environ.get("MAGNETO_PORT", "5400")))
    web.add_argument("--debug", action="store_true")

    notify = subparsers.add_parser("notify", help="send torrent completion/error notifications")
    notify.add_argument(
        "--dry-run", action="store_true", help="print notifications without sending"
    )
    notify.add_argument(
        "--prime",
        action="store_true",
        help="mark current torrent states without sending notifications",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    _load_default_env()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in {None, "web"}:
        host = getattr(args, "host", os.environ.get("MAGNETO_HOST", "127.0.0.1"))
        port = getattr(args, "port", int(os.environ.get("MAGNETO_PORT", "5400")))
        _validate_bind(host)
        try:
            app_config = AppConfig.from_env()
        except ConfigurationError as exc:
            raise SystemExit(str(exc)) from exc
        app = create_app(app_config)
        app.run(host=host, port=port, debug=getattr(args, "debug", False))
        return 0

    if args.command == "notify":
        try:
            app_config = AppConfig.from_env()
            result = build_monitor(app_config).run_once(
                dry_run=getattr(args, "dry_run", False),
                prime=getattr(args, "prime", False),
            )
        except (ConfigurationError, NotificationError) as exc:
            raise SystemExit(str(exc)) from exc
        if result.disabled:
            print("notifications disabled")
        else:
            print(f"notifications sent={result.sent} skipped={result.skipped}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
