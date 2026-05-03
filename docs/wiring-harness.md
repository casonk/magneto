# wiring-harness access

`magneto` is designed to run as a localhost service and rely on
`wiring-harness` for private HTTPS, DNS, and mTLS client authentication.

Suggested registry entry:

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

Provisioning sequence:

```bash
cd ../wiring-harness
WH_WG_IP=10.99.0.1 bash scripts/setup-mtls.sh --refresh-server
sudo python3 scripts/setup_caddy.py --provision
python3 scripts/render_private_site_inventory.py
```

The iPhone must have the `wiring-harness` mTLS profile installed and must reach
the host through the private WireGuard path that resolves
`torrents.snowbridge.internal`.
