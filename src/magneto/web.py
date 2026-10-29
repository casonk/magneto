"""Flask web UI for magneto."""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Callable
from http import HTTPStatus
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from magneto import settings as defaults_store
from magneto.config import AppConfig
from magneto.service import ServiceRestartError, restart_transmission_service
from magneto.transmission import TransmissionClient, TransmissionError


def create_app(
    config: AppConfig | None = None,
    client: TransmissionClient | None = None,
    restart_service: Callable[[], None] = restart_transmission_service,
) -> Flask:
    app_config = config or AppConfig.from_env()
    app = Flask(__name__)
    app.secret_key = app_config.secret_key
    app.config["MAX_CONTENT_LENGTH"] = app_config.max_torrent_upload_bytes
    app.config["MAGNETO_CONFIG"] = app_config
    app.config["MAGNETO_CLIENT"] = client or TransmissionClient(
        app_config.transmission_url,
        username=app_config.username,
        password=app_config.password,
        timeout=app_config.request_timeout,
    )
    app.config["MAGNETO_RESTART_SERVICE"] = restart_service

    @app.before_request
    def _protect_state_changing_requests() -> None:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        source = _request_source(request)
        if source and not _same_origin(source, app_config, request):
            abort(HTTPStatus.FORBIDDEN, description="Cross-origin request blocked.")
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("csrf_token"):
            abort(HTTPStatus.FORBIDDEN, description="Missing or invalid CSRF token.")

    @app.get("/")
    def index():
        token = _csrf_token()
        torrents: list[dict] = []
        status_error = ""
        try:
            torrents = _client().list_torrents()
        except TransmissionError as exc:
            status_error = str(exc)
        return render_template(
            "index.html",
            torrents=torrents,
            status_error=status_error,
            download_dir=app_config.download_dir,
            csrf_token=token,
            torrent_hosts=app_config.torrent_hosts,
            defaults=defaults_store.load(app_config),
            defaults_editable=bool(app_config.settings_file),
        )

    @app.post("/settings/defaults")
    def save_defaults():
        if not app_config.settings_file:
            abort(HTTPStatus.NOT_FOUND)
        try:
            chosen = defaults_store.Defaults(
                download_kbps=_parse_download_limit(request.form.get("download_kbps", "")),
                upload_kbps=_parse_upload_limit(request.form.get("upload_kbps", "")),
                seed_ratio=_parse_seed_ratio(request.form.get("seed_ratio", "")),
                no_seed=request.form.get("no_seed") == "on",
            )
            defaults_store.save(app_config, chosen)
            flash("Defaults for new torrents saved.", "success")
        except (TransmissionError, OSError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.get("/api/torrents")
    def api_torrents():
        try:
            return jsonify({"ok": True, "torrents": _client().list_torrents()})
        except TransmissionError as exc:
            return jsonify({"ok": False, "error": str(exc)}), HTTPStatus.BAD_GATEWAY

    @app.get("/torrents/fragment")
    def torrent_list_fragment():
        token = _csrf_token()
        try:
            response = app.response_class(
                render_template(
                    "_torrent_list.html",
                    torrents=_client().list_torrents(),
                    csrf_token=token,
                ),
                mimetype="text/html",
            )
        except TransmissionError as exc:
            response = app.response_class(
                render_template(
                    "_torrent_list.html", torrents=[], status_error=str(exc), csrf_token=token
                ),
                status=HTTPStatus.BAD_GATEWAY,
                mimetype="text/html",
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/healthz/transmission")
    def transmission_healthz():
        try:
            _client().call("session-get")
        except TransmissionError as exc:
            return jsonify({"ok": False, "error": str(exc)}), HTTPStatus.SERVICE_UNAVAILABLE
        return jsonify({"ok": True})

    @app.post("/transmission/restart")
    def restart_transmission():
        try:
            app.config["MAGNETO_RESTART_SERVICE"]()
            flash("Transmission restart requested. Refresh in a few seconds.", "success")
        except ServiceRestartError as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.post("/torrents")
    def add_torrent():
        magnet = request.form.get("magnet", "").strip()
        upload = request.files.get("torrent_file")

        try:
            if magnet:
                _validate_magnet(magnet)
                result = _client().add_magnet(
                    magnet, app_config.download_dir, no_seed=defaults_store.load(app_config).no_seed
                )
                flash("Torrent added.", "success")
                _apply_defaults(result)
            elif upload and upload.filename:
                if not upload.filename.lower().endswith(".torrent"):
                    raise ValueError("Uploaded file must use a .torrent extension.")
                content = upload.read()
                if not content:
                    raise ValueError("Uploaded torrent file was empty.")
                result = _client().add_torrent_file(
                    content,
                    app_config.download_dir,
                    no_seed=defaults_store.load(app_config).no_seed,
                )
                flash("Torrent file added.", "success")
                _apply_defaults(result)
            else:
                raise ValueError("Paste a magnet link or choose a .torrent file.")
        except (TransmissionError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.post("/torrents/<int:torrent_id>/<action>")
    def torrent_action(torrent_id: int, action: str):
        try:
            if action == "pause":
                _client().pause(torrent_id)
                flash("Torrent paused.", "success")
            elif action == "resume":
                _client().resume(torrent_id)
                flash("Torrent resumed.", "success")
            elif action == "reannounce":
                _client().reannounce(torrent_id)
                flash("Tracker reannounce requested.", "success")
            elif action == "no-seed":
                _client().set_seed_ratio(torrent_id, enabled=True, ratio=0.0)
                _client().set_upload_limit(torrent_id, enabled=True, kbps=0)
                flash("Seeding disabled for this torrent.", "success")
            elif action == "allow-seed":
                _client().set_seed_ratio(torrent_id, enabled=False)
                _client().set_upload_limit(torrent_id, enabled=False, kbps=0)
                flash("Seeding restored to the global Transmission defaults.", "success")
            elif action == "seed-ratio":
                ratio = _parse_seed_ratio(request.form.get("seed_ratio", ""))
                if ratio is None:
                    _client().set_seed_ratio(torrent_id, enabled=False)
                    flash("Seed ratio set to the global Transmission default.", "success")
                else:
                    _client().set_seed_ratio(torrent_id, enabled=True, ratio=ratio)
                    flash(f"Seeding stops at ratio {ratio:g}.", "success")
            elif action == "throttle-upload":
                kbps = _parse_upload_limit(request.form.get("upload_limit_kbps", ""))
                _client().set_upload_limit(torrent_id, enabled=kbps > 0, kbps=kbps)
                if kbps > 0:
                    flash(f"Upload limited to {kbps} KB/s.", "success")
                else:
                    flash("Upload limit disabled.", "success")
            elif action == "throttle-download":
                kbps = _parse_download_limit(request.form.get("download_limit_kbps", ""))
                _client().set_download_limit(torrent_id, enabled=kbps > 0, kbps=kbps)
                if kbps > 0:
                    flash(f"Download limited to {kbps} KB/s.", "success")
                else:
                    flash("Download limit disabled.", "success")
            elif action == "restart":
                _client().restart(torrent_id)
                flash("Torrent restarted.", "success")
            elif action == "remove":
                _client().remove(torrent_id, delete_local_data=False)
                flash("Torrent removed from Transmission.", "success")
            elif action == "cancel":
                _client().remove(torrent_id, delete_local_data=True)
                flash("Torrent cancelled and local data deleted.", "success")
            else:
                abort(HTTPStatus.NOT_FOUND)
        except TransmissionError as exc:
            flash(str(exc), "error")
        return redirect(url_for("index"))

    def _client() -> TransmissionClient:
        return app.config["MAGNETO_CLIENT"]

    def _apply_defaults(result: object) -> None:
        """Give a newly added torrent the configured default rates and seed ratio.

        A failure here never fails the add: the torrent is already in Transmission.
        """
        added = result.get("torrent-added") if isinstance(result, dict) else None
        torrent_id = added.get("id") if isinstance(added, dict) else None
        if not isinstance(torrent_id, int):
            return
        chosen = defaults_store.load(app_config)
        try:
            if chosen.download_kbps:
                _client().set_download_limit(torrent_id, enabled=True, kbps=chosen.download_kbps)
            if chosen.upload_kbps and not chosen.no_seed:
                _client().set_upload_limit(torrent_id, enabled=True, kbps=chosen.upload_kbps)
            if chosen.seed_ratio and not chosen.no_seed:
                _client().set_seed_ratio(torrent_id, enabled=True, ratio=chosen.seed_ratio)
        except TransmissionError as exc:
            flash(f"Torrent added, but its default limits were not applied: {exc}", "error")

    return app


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


def _same_origin(origin_or_referrer: str, config: AppConfig, flask_request) -> bool:
    source = _normalize_origin(origin_or_referrer)
    if not source:
        return False

    allowed = {
        origin
        for origin in (
            _normalize_origin(flask_request.host_url),
            _normalize_origin(config.public_origin or ""),
            *(_normalize_origin(value) for value in config.allowed_origins),
        )
        if origin
    }

    forwarded_host = flask_request.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
    forwarded_proto = flask_request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    if forwarded_host:
        forwarded_scheme = forwarded_proto or flask_request.scheme
        allowed.add(_normalize_origin(f"{forwarded_scheme}://{forwarded_host}"))

    allowed.update(_loopback_alias_origins(flask_request))
    return source in allowed


def _request_source(flask_request) -> str:
    origin = str(flask_request.headers.get("Origin") or "").strip()
    if origin and origin.lower() != "null":
        return origin
    return str(flask_request.headers.get("Referer") or "").strip()


def _loopback_alias_origins(flask_request) -> set[str]:
    parsed = urlparse(flask_request.host_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port
    if not _is_loopback_host(host):
        return set()
    suffix = f":{port}" if port else ""
    return {
        _normalize_origin(f"{scheme}://127.0.0.1{suffix}"),
        _normalize_origin(f"{scheme}://localhost{suffix}"),
        _normalize_origin(f"{scheme}://[::1]{suffix}"),
    }


def _is_loopback_host(host: str) -> bool:
    candidate = host.strip().strip("[]")
    if candidate.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""
    port = parsed.port
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    if port and port != default_port:
        return f"{scheme}://{hostname}:{port}"
    return f"{scheme}://{hostname}"


def _validate_magnet(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "magnet":
        raise ValueError("Magnet link must start with magnet:.")
    lowered = value.lower()
    if "xt=urn:btih:" not in lowered and "xt=urn:btmh:" not in lowered:
        raise ValueError("Magnet link must include a BitTorrent info hash.")


def _parse_upload_limit(value: str) -> int:
    return _parse_rate_limit(value, "Upload")


def _parse_seed_ratio(value: str) -> float | None:
    """A target ratio above zero, or None for the global Transmission default.

    Zero is deliberately rejected: "stop seeding now" is the No seed action.
    """
    stripped = value.strip().lower()
    if stripped in {"", "global", "default"}:
        return None
    try:
        ratio = float(stripped)
    except ValueError as exc:
        raise TransmissionError("Seed ratio must be a number, or Global.") from exc
    if not 0 < ratio <= 1000:
        raise TransmissionError(
            "Seed ratio must be greater than 0 and at most 1000; use No seed to stop seeding."
        )
    return ratio


def _parse_download_limit(value: str) -> int:
    return _parse_rate_limit(value, "Download")


def _parse_rate_limit(value: str, direction: str) -> int:
    stripped = value.strip()
    if not stripped:
        return 0
    try:
        kbps = int(stripped)
    except ValueError as exc:
        raise TransmissionError(f"{direction} limit must be a whole number of KB/s.") from exc
    if kbps < 0 or kbps > 10_000_000:
        raise TransmissionError(f"{direction} limit must be between 0 and 10000000 KB/s.")
    return kbps
