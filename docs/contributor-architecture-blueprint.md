# Contributor Architecture Blueprint

## Purpose

`magneto` is a small private Flask web app that wraps the Transmission RPC API.
It lets a phone or desktop browser add magnet links or `.torrent` files and
control (pause, resume, remove) active downloads — all forced into a fixed
Snowbridge share directory.

## Main Flow

1. A browser request arrives at the Flask app (bound to `127.0.0.1`, exposed
   via `wiring-harness` Caddy/mTLS for trusted LAN/VPN devices).
2. The `magneto.web` blueprint routes the request to the appropriate handler:
   - `POST /add` — accepts a magnet URI or uploaded `.torrent` file
   - `POST /pause`, `POST /resume`, `POST /remove` — control an active torrent
   - `GET /` — renders the torrent list
3. Each handler calls `magneto.transmission.TransmissionClient`, which makes an
   authenticated JSON-RPC call to the local Transmission daemon.
4. Transmission places downloads in the fixed `MAGNETO_DOWNLOAD_DIR` path
   (configured via `config/magneto.env.local`), which is the Snowbridge share.
5. The Flask response renders the updated torrent list back to the browser.

## Design Boundaries

- The download destination is fixed server-side; the web UI cannot override it.
- Transmission credentials stay in `config/magneto.env.local` (gitignored).
- The app binds to `127.0.0.1` by default; `MAGNETO_ALLOW_REMOTE=1` widens
  this for testing only.
- `wiring-harness` owns the Caddy proxy entry and the private hostname.

## Validation

- `pytest -q` runs unit tests for routing, RPC client behavior, and error paths.
- `pre-commit run --all-files` for lint, formatting, and secret-scan checks.
- CI runs lint, format, and pytest on every push.
