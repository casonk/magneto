# Deployment modes: magneto

magneto runs three ways. You choose with one setting, and **only the `k3s` mode needs a cluster**. If you just
want to run it, you need Python and nothing else.

| Mode | What it is | Needs |
|---|---|---|
| `dev` (default) | the service in the foreground on 127.0.0.1, no systemd, no cluster | the language runtime |
| `host` | the systemd user service on 127.0.0.1 | systemd |
| `k3s` | a pod in K3s behind a loopback forwarder, so the front end keeps its address | K3s, podman, kubectl, the in-cluster registry |

The application code is the same in all three: nothing under `src/` knows which mode it is in.

## Choose a mode

```bash
deploy/deploy.sh mode                  # print the mode in effect and where it came from
deploy/deploy.sh up                    # run it in that mode
deploy/deploy.sh status | verify | down
```

The mode is read from, first match wins:

1. `--mode dev|host|k3s` on the command line
2. `MAGNETO_DEPLOY_MODE` in the environment
3. `MAGNETO_DEPLOY_MODE` in `config/deploy.local.env` (copy `config/deploy.example.env`; it is gitignored)
4. `dev`

An unknown value, or a config file that cannot be read, is an error, never a silent fallback.

## What each mode does

### dev
`up` runs the service in the foreground on `127.0.0.1`. `status` and `verify` call its health endpoint.

### host
`up` enables the systemd user service. If the K3s bridge was on, it takes the bridge down and starts the service again.

### k3s
`up` refuses to start, and changes nothing, unless kubectl, podman and the in-cluster registry are present. Then it
builds (refusing uncommitted source), applies, verifies, and only then runs `bridge.sh on`, which stops and disables
the host service and forwards `127.0.0.1` to the pod, so the front end is unchanged. If the bridge cannot come up
the host service is put back.

## Switching

| From | To | Command |
|---|---|---|
| dev | host | stop the foreground process, then `deploy/deploy.sh --mode host up` |
| host | k3s | `deploy/deploy.sh --mode k3s up` (verifies first, then brings the bridge up) |
| k3s | host | `deploy/deploy.sh --mode host up` (takes the bridge down, starts the host service) |

`--mode k3s down` is the same as `--mode host up`. A marker in `~/.local/state/magneto/` records which mode last
held the work, so `host up` knows what to stop first.

## For contributors without K3s

- `pytest` needs no cluster: the deployment tests parse manifests and run the scripts against stub commands.
- Nothing under `deploy/k3s/` runs unless you select the `k3s` mode.
- This file, the scripts and their tests started from traction-control's `scripts/scaffold_deployment_modes.py`;
  the contract is in its `docs/deployment-modes.md`. Run `scripts/check_deployment_modes.py --repo .` to check.

## magneto specifics (k3s)

Only the **web UI** moves into the pod. Transmission itself, its VPN guard, the restart permission and the notify
timer (recovery, library moves, Signal and email) stay on the host: they need the host's network interface, `sudo`
and the Snowbridge share.

- **How the pod reaches Transmission.** Transmission listens on `127.0.0.1:9091` and only accepts RPC from loopback.
  `deploy/k3s/rpc-proxy.sh on` starts a user socket on the node's pod-network address (`cilium_host`) that forwards
  `:9091` to loopback, so nothing new listens on the LAN. Cilium lets the pod reach that single host port; the host's
  other ports, the internet, the Kubernetes API and other pods are denied, and `verify.sh` probes each.
- **Credentials.** The Transmission username and password are resolved from your vault on the host (with magneto's
  own loader) when `apply.sh` runs, and reach the cluster only as the `magneto-env` Secret. The vault entry name,
  notification targets and library settings are not copied.
- **No restart button.** The button runs `sudo systemctl` on the host, which a pod can neither do nor be given.
  K3s mode sets `MAGNETO_RESTART_ENABLED=0`: the button is hidden and a request says to restart it on the host.
  Everything else (add magnets and files, pause, resume, remove, limits) works.
- **Address.** The pod is `10.43.0.62:5400`; the host forwarder keeps `127.0.0.1:5400`, so Caddy and its mTLS entry
  are unchanged.
- **If K3s is reinstalled** the node may get another pod-network address: re-run `deploy/deploy.sh --mode k3s up`,
  which restarts the forwarder on the new address and re-renders the Secret.
