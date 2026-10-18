"""Command line entry points for magneto."""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from pathlib import Path

from magneto.config import AppConfig, ConfigurationError
from magneto.library import file_completed
from magneto.notifications import NotificationError, build_monitor
from magneto.recovery import reannounce_stalled
from magneto.transmission import TransmissionClient, TransmissionError
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


def _transmission_client(app_config: AppConfig) -> TransmissionClient:
    return TransmissionClient(
        app_config.transmission_url,
        username=app_config.username,
        password=app_config.password,
        timeout=app_config.request_timeout,
    )


def _recover_stalled(app_config: AppConfig, *, dry_run: bool) -> None:
    """Reannounce torrents stuck in tracker backoff; never block notifications."""
    client = _transmission_client(app_config)
    try:
        result = reannounce_stalled(client, vpn_interface=app_config.vpn_interface, dry_run=dry_run)
    except TransmissionError as exc:
        print(f"stalled torrent recovery failed: {exc}", file=sys.stderr)
        return
    if not result.vpn_up:
        print(f"stalled torrent recovery skipped: {app_config.vpn_interface} is down")
    elif result.reannounced:
        verb = "would reannounce" if dry_run else "reannounced"
        print(f"{verb} {len(result.reannounced)} stalled: {', '.join(result.reannounced)}")


def _file_completed(app_config: AppConfig, library_dir: str, *, dry_run: bool) -> None:
    """Move finished downloads into the library; never fail the notify run."""
    try:
        result = file_completed(
            _transmission_client(app_config),
            download_dir=app_config.download_dir,
            library_dir=library_dir,
            dry_run=dry_run,
        )
    except TransmissionError as exc:
        print(f"library filing failed: {exc}", file=sys.stderr)
        return
    if result.moved:
        verb = "would move" if dry_run else "moved"
        print(f"{verb} {len(result.moved)} to {library_dir}: {', '.join(result.moved)}")
    if result.skipped:
        print(f"already in {library_dir}, left in place: {', '.join(result.skipped)}")


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
        except ConfigurationError as exc:
            raise SystemExit(str(exc)) from exc
        if app_config.reannounce_stalled:
            _recover_stalled(app_config, dry_run=getattr(args, "dry_run", False))
        try:
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
        # File after notifying so completion messages go out before the move.
        if app_config.library_dir:
            _file_completed(
                app_config, app_config.library_dir, dry_run=getattr(args, "dry_run", False)
            )
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
