# magneto

Private iPhone-friendly torrent control for a Snowbridge share.

`magneto` is a small Flask app that talks to Transmission RPC. It can add a
magnet link or uploaded `.torrent` file, then pause, resume, restart, remove, or
cancel torrents from a touch-friendly web UI.

Downloads always go to the configured Snowbridge directory. The browser cannot
override the destination path.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
cp config/magneto.env.example config/magneto.env.local
```

Edit `config/magneto.env.local` for your Snowbridge download directory. The
default Transmission RPC endpoint is loopback-only
`http://127.0.0.1:9091/transmission/rpc`; Transmission can keep its RPC allowlist
to `127.0.0.1` and `::1`.

By default, Magneto resolves Transmission RPC auth through the sibling
`auto-pass` repo using the `infra` profile and KeePassXC entry
`magneto@transmission`. Leave `MAGNETO_TRANSMISSION_USERNAME` and
`MAGNETO_TRANSMISSION_PASSWORD` blank unless you need to override the KeePassXC
fields.

Make sure the Transmission daemon user can write to `MAGNETO_DOWNLOAD_DIR`.
`magneto` passes that directory to Transmission for every add request; it does
not move files after the fact.

## Run

```bash
magneto web
```

Defaults:

- local URL: `http://127.0.0.1:5400`
- private URL: `https://torrents.snowbridge.internal`
- public origin for form safety: `https://torrents.snowbridge.internal`
- Transmission RPC: `http://127.0.0.1:9091/transmission/rpc`
- Transmission auth: `auto-pass` profile `infra`, entry `magneto@transmission`
- download directory: `/srv/snowbridge/share/torrents`

## Notifications

Magneto can poll Transmission and send one-shot torrent completion/error
notifications through the sibling `shock-relay` repo. Configure these in
`config/magneto.env.local`:

```bash
MAGNETO_NOTIFY_ENABLED=1
MAGNETO_SHOCK_RELAY_ROOT=/mnt/4tb-m2/git/util-repos/shock-relay
MAGNETO_NOTIFY_TAG=magneto/notify
MAGNETO_NOTIFY_SIGNAL_TARGET=+15551234567
MAGNETO_NOTIFY_SIGNAL_CONFIG=/mnt/4tb-m2/git/util-repos/shock-relay/services/signal-cli/config.local.yaml
MAGNETO_NOTIFY_EMAIL_TARGET=you@example.com
MAGNETO_NOTIFY_EMAIL_CONFIG=/mnt/4tb-m2/git/util-repos/shock-relay/services/gmail-imap/config.local.yaml
```

Supported services are `signal`, `telegram`, `twilio`, `whatsapp`, `gmail`, and
`gmail-imap`. Signal notifications receive a `tag` metadata line, Gmail
notifications receive an `X-Magneto-Tag` header, and other services include the
tag in the message body. Prime the state file once if you do not want alerts for
already completed torrents:

```bash
magneto notify --prime
```

Run a manual poll with:

```bash
magneto notify
```

The Clockwork manifest in `../clockwork/examples/magneto/web-service.local.toml`
includes a `magneto-notify.timer` that runs the poller every five minutes.

## User Service

For the normal full host refresh, use the meta-script:

```bash
./scripts/apply_magneto_stack.sh
```

Add wiring-harness/Caddy/DNS refresh when site registry or cert SANs changed:

```bash
./scripts/apply_magneto_stack.sh --with-wiring-harness
```

On first notification setup, prime existing torrent states so old completed
torrents do not alert:

```bash
./scripts/apply_magneto_stack.sh --prime-notifications
```

```bash
./scripts/install_web_service.sh
systemctl --user status magneto-web.service --no-pager
```

The lower-level app-only setup script remains available for focused web changes:

```bash
./scripts/apply_host_setup.sh
```

## Transmission VPN Guard

For safer torrent egress, run Transmission as a dedicated daemon user and
install the nftables guard so that user can only send network traffic through
NordVPN's `nordlynx` interface. NordLynx then encapsulates those accepted tunnel
packets as marked UDP traffic to the VPN server over the physical interface; the
guard allows only that marked transport path by default
(`meta mark 0xe1f1`, UDP port `51820`). The default keeps local loopback open
only for systemd-resolved DNS requests and Transmission RPC responses on port
`9091`; if NordVPN drops, torrent traffic is rejected instead of falling back to
the normal gateway.

Do not target the Flatpak/GTK Transmission app when it runs as your normal login
user. A UID-based guard on your login user would affect the whole desktop
session, not just Transmission.

To move Magneto from Transmission GTK to a dedicated daemon backend and install
the guard in one pass:

```bash
./scripts/install_transmission_daemon_backend.sh --stop-gtk
```

To reapply the guard after script changes, restart Transmission, and print the
active nftables table:

```bash
./scripts/apply_transmission_vpn_guard.sh
```

```bash
./scripts/install_transmission_vpn_guard.sh \
  --transmission-user transmission \
  --vpn-interface nordlynx \
  --rpc-port 9091
```

If your Transmission systemd unit is not auto-detected, pass it explicitly:

```bash
./scripts/install_transmission_vpn_guard.sh --transmission-service transmission-daemon.service
```

Keep `--allow-local-dns` off unless tracker DNS resolution fails and the host's
local resolver is already forced through the VPN.

If a tracker fails while NordVPN is connected, capture guard counters and reject
logs with:

```bash
./scripts/diagnose_transmission_vpn.sh --seconds 30
```

The diagnostic temporarily enables kernel logging for rejected Transmission
packets, restarts the daemon, requests a tracker reannounce, prints the torrent
tracker state and nft counters, then restores the guard without reject logging.

## wiring-harness

The local private-site registry should contain:

```toml
[[services]]
name        = "magneto-web"
description = "Magneto torrent control"
owner_repo  = "./util-repos/magneto"
hostname    = "torrents.snowbridge.internal"
access_mode = "shared-mtls"
ingress     = "wiring-harness-caddy"
port        = 5400
```

After changing the registry, refresh the shared cert SANs and Caddy config:

```bash
cd ../wiring-harness
WH_WG_IP=10.99.0.1 bash scripts/setup-mtls.sh --refresh-server
sudo python3 scripts/setup_caddy.py --provision
```

## Development

```bash
ruff check .
ruff format --check .
pytest -q
```

Magneto uses the shared `dyno-lab` pytest fixtures for CLI and subprocess
integration tests. The dev extra includes the portfolio Dyno-lab package.

Tachometer profiling is available through the repo-local wrapper:

```bash
./scripts/run_tachometer_profile.sh snapshot
./scripts/run_tachometer_profile.sh run -- python -m pytest -q
```
