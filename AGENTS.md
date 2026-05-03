# AGENTS.md - magneto

## Purpose

`magneto` provides a small private web UI for adding magnet links or torrent
files to Transmission and forcing downloads into the configured Snowbridge
share directory.

The app is intended to bind to localhost and be exposed to trusted devices
through `wiring-harness` Caddy/mTLS.

## Setup and Commands

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest -q
```

Run the web UI locally:

```bash
MAGNETO_DOWNLOAD_DIR=/srv/snowbridge/share/torrents magneto web
```

Install the user service:

```bash
./scripts/install_web_service.sh
```

## Operating Rules

1. Keep Transmission credentials and host-local paths in `config/magneto.env.local`.
2. Do not allow users to choose arbitrary download directories from the web UI.
3. Keep the app bound to `127.0.0.1` unless it is explicitly being tested with
   `MAGNETO_ALLOW_REMOTE=1`.
4. `wiring-harness/services.local.toml` owns the private hostname and Caddy
   proxy entry.
5. Use `scripts/install_transmission_vpn_guard.sh` to constrain Transmission
   egress to the VPN provider interface instead of relying on web UI behavior
   for network safety.
