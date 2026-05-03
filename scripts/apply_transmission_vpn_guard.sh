#!/usr/bin/env bash
# Reapply the Magneto Transmission VPN guard and restart the backend in one step.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/apply_transmission_vpn_guard.sh [options]

Options:
  --transmission-user USER      Transmission daemon user. Default: transmission
  --transmission-service UNIT   Transmission systemd unit. Default: transmission-daemon.service
  --vpn-interface IFACE         VPN provider interface. Default: nordlynx
  --rpc-port PORT               Local Transmission RPC port. Default: 9091
  --table NAME                  nftables table name. Default: magneto_transmission_vpn_guard
  --no-status                   Do not print systemd/nft status after restart
  -h, --help                    Show this help

This is the one-line fast path for the normal host:
  install/restart guard -> restart Transmission -> show active guard table
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

transmission_user="transmission"
transmission_service="transmission-daemon.service"
vpn_interface="nordlynx"
rpc_port="9091"
nft_table="magneto_transmission_vpn_guard"
show_status=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --transmission-user)
      transmission_user="${2:?--transmission-user requires a value}"
      shift 2
      ;;
    --transmission-service)
      transmission_service="${2:?--transmission-service requires a value}"
      shift 2
      ;;
    --vpn-interface)
      vpn_interface="${2:?--vpn-interface requires a value}"
      shift 2
      ;;
    --rpc-port)
      rpc_port="${2:?--rpc-port requires a value}"
      shift 2
      ;;
    --table)
      nft_table="${2:?--table requires a value}"
      shift 2
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

section() {
  echo
  echo "==> $*"
}

as_root() {
  sudo "$@"
}

section "Applying Transmission VPN guard"
"${repo_dir}/scripts/install_transmission_vpn_guard.sh" \
  --transmission-user "$transmission_user" \
  --transmission-service "$transmission_service" \
  --vpn-interface "$vpn_interface" \
  --rpc-port "$rpc_port" \
  --table "$nft_table"

section "Restarting ${transmission_service}"
as_root systemctl restart "$transmission_service"

if [[ "$show_status" -eq 1 ]]; then
  section "Transmission status"
  as_root systemctl status "$transmission_service" --no-pager

  section "Active guard table"
  as_root nft list table inet "$nft_table"
fi

echo
echo "Transmission VPN guard applied."
