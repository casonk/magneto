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

For a multi-host Magneto setup, give each host a stable ID and human label.
The selector opens the selected host's own Magneto page before an add is made;
it never forwards a Transmission RPC request or a host-specific download path.

```toml
[[services]]
name          = "magneto-air"
description   = "Magneto on MacBook Air"
owner_repo    = "./util-repos/magneto"
hostname      = "torrents.air.internal"
access_mode   = "shared-mtls"
ingress       = "wiring-harness-caddy"
port          = 5400
torrent_host  = "air"
torrent_label = "MacBook Air"

[[services]]
name          = "magneto-home"
description   = "Magneto on the home server"
owner_repo    = "./util-repos/magneto"
hostname      = "torrents.home.internal"
access_mode   = "shared-mtls"
ingress       = "wiring-harness-caddy"
port          = 5400
torrent_host  = "home"
torrent_label = "Home server"
```

On each host, render its non-secret selector file after its local registry is
in place, then set the resulting path in `MAGNETO_TORRENT_HOSTS_FILE`:

```bash
python3 scripts/render_torrent_hosts.py \
  --services ../wiring-harness/services.toml \
  --current-id air \
  --current-url https://torrents.air.internal/ \
  --output config/torrent-hosts.json
```

For an Air endpoint exposed with a `macos_edge_role = "magneto"`, omit the
normal hostname URL only if the registry also declares its edge listener; the
renderer then uses the WireGuard IP and that listener port.

Clockwork's future To Watch torrent action can use the same rendered file via
`CLOCKWORK_MAGNETO_HOSTS_FILE`. Its current host remains
`CLOCKWORK_MAGNETO_URL` on loopback; remote selections require all three
owner-only values `CLOCKWORK_MAGNETO_MTLS_CA_FILE`,
`CLOCKWORK_MAGNETO_MTLS_CLIENT_CERT`, and `CLOCKWORK_MAGNETO_MTLS_CLIENT_KEY`.
That makes a missing mTLS identity an error instead of a fallback to an
unencrypted or unauthenticated remote request.

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
