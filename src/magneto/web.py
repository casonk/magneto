"""Flask web UI for magneto."""

from __future__ import annotations

import ipaddress
import secrets
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
from markupsafe import escape

from magneto.config import AppConfig
from magneto.transmission import TransmissionClient, TransmissionError


def create_app(
    config: AppConfig | None = None,
    client: TransmissionClient | None = None,
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
        )

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
                    "_torrent_list.html",
                    torrents=[],
                    csrf_token=token,
                )
                + f'<section class="message error">{escape(str(exc))}</section>',
                status=HTTPStatus.BAD_GATEWAY,
                mimetype="text/html",
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.post("/torrents")
    def add_torrent():
        magnet = request.form.get("magnet", "").strip()
        upload = request.files.get("torrent_file")

        try:
            if magnet:
                _validate_magnet(magnet)
                _client().add_magnet(magnet, app_config.download_dir)
                flash("Torrent added.", "success")
            elif upload and upload.filename:
                if not upload.filename.lower().endswith(".torrent"):
                    raise ValueError("Uploaded file must use a .torrent extension.")
                content = upload.read()
                if not content:
                    raise ValueError("Uploaded torrent file was empty.")
                _client().add_torrent_file(content, app_config.download_dir)
                flash("Torrent file added.", "success")
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
            elif action == "throttle-upload":
                kbps = _parse_upload_limit(request.form.get("upload_limit_kbps", ""))
                _client().set_upload_limit(torrent_id, enabled=kbps > 0, kbps=kbps)
                if kbps > 0:
                    flash(f"Upload limited to {kbps} KB/s.", "success")
                else:
                    flash("Upload limit disabled.", "success")
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
    stripped = value.strip()
    if not stripped:
        return 0
    try:
        kbps = int(stripped)
    except ValueError as exc:
        raise TransmissionError("Upload limit must be a whole number of KB/s.") from exc
    if kbps < 0 or kbps > 10_000_000:
        raise TransmissionError("Upload limit must be between 0 and 10000000 KB/s.")
    return kbps
