# wiring-harness access

`magneto` is designed to run as a localhost service and rely on
`wiring-harness` for private HTTPS, DNS, and mTLS client authentication.

Suggested registry entry (replace `torrents.example.local` with the hostname
defined in your local `wiring-harness/services.local.toml`):

```toml
[[services]]
name        = "magneto-web"
description = "Magneto torrent control"
owner_repo  = "./util-repos/magneto"
hostname    = "torrents.example.local"
access_mode = "shared-mtls"
ingress     = "wiring-harness-caddy"
port        = 5400
```

Provisioning sequence (replace `YOUR_WG_IP` with the WireGuard gateway IP
defined in your local `wiring-harness` config):

```bash
cd ../wiring-harness
WH_WG_IP=YOUR_WG_IP bash scripts/setup-mtls.sh --refresh-server
sudo python3 scripts/setup_caddy.py --provision
python3 scripts/render_private_site_inventory.py
```

The client device must have the `wiring-harness` mTLS profile installed and
must reach the host through the private WireGuard path that resolves the
configured hostname.
