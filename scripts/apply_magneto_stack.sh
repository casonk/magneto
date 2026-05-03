#!/usr/bin/env bash
# Apply the normal Magneto host stack in one command.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/apply_magneto_stack.sh [options]

Default behavior:
  - update the Magneto venv/config and restart magneto-web.service
  - verify Transmission RPC auth
  - refresh the Transmission VPN guard and restart transmission-daemon.service
  - install Clockwork user units for magneto-web.service and magneto-notify.timer
  - enable/restart the web service and enable/start the notify timer
  - verify local web health, notification poll, and user service status

Options:
  --with-wiring-harness       Also refresh wiring-harness DNS, mTLS SANs, and Caddy
  --wg-ip IP                  WireGuard server IP for wiring-harness (default: 10.99.0.1)
  --skip-vpn-guard            Do not refresh the Transmission VPN guard
  --skip-clockwork            Do not install Clockwork units
  --skip-notify-check         Do not run a one-shot notification poll
  --prime-notifications       Mark current torrent states as seen without sending alerts
  --no-status                 Skip final status output
  -h, --help                  Show this help

The defaults match the local desk host:
  transmission user: transmission
  transmission service: transmission-daemon.service
  VPN interface: nordlynx
  RPC port: 9091
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parent_dir="$(dirname "$repo_dir")"
clockwork_dir="${parent_dir}/clockwork"
clockwork_manifest="${clockwork_dir}/examples/magneto/web-service.local.toml"

with_wiring_harness=0
skip_vpn_guard=0
skip_clockwork=0
skip_notify_check=0
prime_notifications=0
show_status=1
wg_ip="${WH_WG_IP:-10.99.0.1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-wiring-harness)
      with_wiring_harness=1
      shift
      ;;
    --wg-ip)
      wg_ip="${2:?--wg-ip requires a value}"
      shift 2
      ;;
    --skip-vpn-guard)
      skip_vpn_guard=1
      shift
      ;;
    --skip-clockwork)
      skip_clockwork=1
      shift
      ;;
    --skip-notify-check)
      skip_notify_check=1
      shift
      ;;
    --prime-notifications)
      prime_notifications=1
      shift
      ;;
    --no-status)
      show_status=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -eq 0 ]]; then
  echo "error: run this as your normal user; the script uses sudo only where needed." >&2
  exit 1
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

section() {
  echo
  echo "==> $*"
}

apply_host_setup() {
  local -a args=()
  if [[ "$with_wiring_harness" -eq 1 ]]; then
    args+=(--with-wiring-harness --wg-ip "$wg_ip")
  fi
  "${repo_dir}/scripts/apply_host_setup.sh" "${args[@]}"
}

apply_vpn_guard() {
  "${repo_dir}/scripts/apply_transmission_vpn_guard.sh" --no-status
}

install_clockwork_units() {
  if [[ ! -f "$clockwork_manifest" ]]; then
    echo "error: Clockwork manifest not found: $clockwork_manifest" >&2
    exit 1
  fi
  (
    cd "$clockwork_dir"
    python -m clockwork install --manifest "$clockwork_manifest" --target systemd-user
  )
  systemctl --user daemon-reload
  systemctl --user enable --now magneto-web.service magneto-notify.timer
  systemctl --user restart magneto-web.service
}

run_notify_check() {
  if [[ "$prime_notifications" -eq 1 ]]; then
    "${repo_dir}/.venv/bin/magneto" notify --prime
  else
    "${repo_dir}/.venv/bin/magneto" notify --dry-run
  fi
}

verify_health() {
  local host port
  host="127.0.0.1"
  port="5400"
  if [[ -f "${repo_dir}/config/magneto.env.local" ]]; then
    # shellcheck source=/dev/null
    source "${repo_dir}/config/magneto.env.local"
    host="${MAGNETO_HOST:-127.0.0.1}"
    port="${MAGNETO_PORT:-5400}"
  fi
  curl -fsS "http://${host}:${port}/healthz" >/dev/null
  echo "ok: Magneto health endpoint is up at http://${host}:${port}/healthz"
}

print_status() {
  systemctl --user status magneto-web.service magneto-notify.timer magneto-notify.service --no-pager || true
  if [[ "$skip_vpn_guard" -eq 0 ]]; then
    sudo nft list table inet magneto_transmission_vpn_guard || true
  fi
}

require_cmd python
require_cmd systemctl
require_cmd curl
if [[ "$skip_vpn_guard" -eq 0 ]]; then
  require_cmd sudo
fi

section "Applying Magneto app setup"
apply_host_setup

if [[ "$skip_vpn_guard" -eq 0 ]]; then
  section "Applying Transmission VPN guard"
  apply_vpn_guard
else
  section "Skipping Transmission VPN guard"
fi

if [[ "$skip_clockwork" -eq 0 ]]; then
  section "Installing Clockwork units"
  install_clockwork_units
else
  section "Skipping Clockwork unit install"
fi

section "Verifying Magneto health"
verify_health

if [[ "$skip_notify_check" -eq 0 ]]; then
  section "Checking notification poller"
  run_notify_check
else
  section "Skipping notification poller check"
fi

if [[ "$show_status" -eq 1 ]]; then
  section "Status"
  print_status
fi

echo
echo "Magneto stack apply complete."
