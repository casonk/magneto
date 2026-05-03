#!/usr/bin/env bash
# Temporarily enable guard reject logging and capture Transmission VPN diagnostics.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/diagnose_transmission_vpn.sh [options]

Options:
  --transmission-user USER      Transmission daemon user. Default: current guard env or transmission
  --uid UID                     Numeric UID override for Transmission
  --transmission-service UNIT   Transmission systemd unit. Default: transmission-daemon.service
  --vpn-interface IFACE         VPN provider interface. Default: current guard env or nordlynx
  --rpc-port PORT               Local Transmission RPC port. Default: current guard env or 9091
  --table NAME                  nftables table name. Default: current guard env or magneto_transmission_vpn_guard
  --allow-vpn-transport         Allow marked WireGuard/NordLynx transport packets. Default unless guard env disables it
  --no-vpn-transport            Block marked WireGuard/NordLynx transport packets too
  --vpn-transport-fwmark MARK   Firewall mark for VPN transport packets. Default: current guard env or 0xe1f1
  --vpn-transport-port PORT     UDP port for VPN transport packets. Default: current guard env or 51820
  --seconds N                   Seconds to wait after reannounce. Default: 20
  --no-reannounce               Do not request tracker reannounce through Transmission RPC
  --keep-logging                Leave kernel reject logging enabled after diagnostics
  --allow-local-dns             Preserve/install broad loopback allowance for Transmission
  --no-local-dns                Disable broad loopback allowance for Transmission
  --allow-loopback-dns          Allow systemd-resolved loopback DNS. Default unless guard env disables it
  --no-loopback-dns             Disable loopback DNS allowance
  -h, --help                    Show this help

The script temporarily reinstalls the Magneto nftables guard with reject logging,
restarts Transmission, optionally reannounces torrents, prints nft counters and
matching kernel reject lines, then restores the guard without reject logging.
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${repo_dir}/config/magneto.env.local"
guard_env="/etc/magneto/transmission-vpn-guard.env"

if [[ -r "$guard_env" ]]; then
  # shellcheck source=/dev/null
  source "$guard_env"
fi

transmission_user="${TRANSMISSION_USER:-transmission}"
uid_override="${TRANSMISSION_UID:-}"
vpn_interface="${VPN_INTERFACE:-nordlynx}"
rpc_port="${RPC_PORT:-9091}"
nft_table="${NFT_TABLE:-magneto_transmission_vpn_guard}"
allow_vpn_transport="${ALLOW_VPN_TRANSPORT:-1}"
vpn_transport_fwmark="${VPN_TRANSPORT_FWMARK:-0xe1f1}"
vpn_transport_port="${VPN_TRANSPORT_PORT:-51820}"
allow_local_dns="${ALLOW_LOCAL_DNS:-0}"
allow_loopback_dns="${ALLOW_LOOPBACK_DNS:-1}"
service_unit="transmission-daemon.service"
seconds=20
reannounce=1
restore_guard=1
logging_enabled=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --transmission-user)
      transmission_user="${2:?--transmission-user requires a value}"
      shift 2
      ;;
    --uid)
      uid_override="${2:?--uid requires a value}"
      shift 2
      ;;
    --transmission-service)
      service_unit="${2:?--transmission-service requires a value}"
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
    --allow-vpn-transport)
      allow_vpn_transport=1
      shift
      ;;
    --no-vpn-transport)
      allow_vpn_transport=0
      shift
      ;;
    --vpn-transport-fwmark)
      vpn_transport_fwmark="${2:?--vpn-transport-fwmark requires a value}"
      shift 2
      ;;
    --vpn-transport-port)
      vpn_transport_port="${2:?--vpn-transport-port requires a value}"
      shift 2
      ;;
    --seconds)
      seconds="${2:?--seconds requires a value}"
      shift 2
      ;;
    --no-reannounce)
      reannounce=0
      shift
      ;;
    --keep-logging)
      restore_guard=0
      shift
      ;;
    --allow-local-dns)
      allow_local_dns=1
      shift
      ;;
    --no-local-dns)
      allow_local_dns=0
      shift
      ;;
    --allow-loopback-dns)
      allow_loopback_dns=1
      shift
      ;;
    --no-loopback-dns)
      allow_loopback_dns=0
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

if [[ ! "$seconds" =~ ^[0-9]+$ ]] || (( seconds < 1 || seconds > 300 )); then
  echo "error: --seconds must be between 1 and 300" >&2
  exit 2
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

as_root() {
  sudo "$@"
}

section() {
  echo
  echo "==> $*"
}

truthy() {
  [[ "${1:-}" =~ ^(1|true|yes|on)$ ]]
}

guard_install_args() {
  local -a args=(
    --transmission-user "$transmission_user"
    --transmission-service "$service_unit"
    --vpn-interface "$vpn_interface"
    --rpc-port "$rpc_port"
    --table "$nft_table"
  )
  if [[ -n "$uid_override" ]]; then
    args+=(--uid "$uid_override")
  fi
  if truthy "$allow_vpn_transport"; then
    args+=(--allow-vpn-transport)
  else
    args+=(--no-vpn-transport)
  fi
  args+=(--vpn-transport-fwmark "$vpn_transport_fwmark")
  args+=(--vpn-transport-port "$vpn_transport_port")
  if truthy "$allow_local_dns"; then
    args+=(--allow-local-dns)
  fi
  if truthy "$allow_loopback_dns"; then
    args+=(--allow-loopback-dns)
  else
    args+=(--no-loopback-dns)
  fi
  printf '%s\n' "${args[@]}"
}

install_guard() {
  local log_rejects="$1"
  local -a args
  mapfile -t args < <(guard_install_args)
  if [[ "$log_rejects" -eq 1 ]]; then
    args+=(--log-rejects)
  fi
  "${repo_dir}/scripts/install_transmission_vpn_guard.sh" "${args[@]}"
}

cleanup() {
  local status=$?
  if [[ "$restore_guard" -eq 1 && "$logging_enabled" -eq 1 ]]; then
    section "Restoring guard without kernel reject logging"
    if install_guard 0; then
      logging_enabled=0
    else
      echo "warning: failed to restore guard logging state" >&2
      echo "rerun scripts/install_transmission_vpn_guard.sh without --log-rejects" >&2
    fi
  fi
  exit "$status"
}
trap cleanup EXIT

resolve_uid() {
  if [[ -n "$uid_override" ]]; then
    printf '%s\n' "$uid_override"
    return
  fi
  id -u "$transmission_user"
}

python_bin() {
  if [[ -x "${repo_dir}/.venv/bin/python" ]]; then
    printf '%s\n' "${repo_dir}/.venv/bin/python"
  else
    printf '%s\n' python3
  fi
}

inspect_torrents() {
  local should_reannounce="$1"
  (
    set -a
    if [[ -f "$env_file" ]]; then
      # shellcheck source=/dev/null
      source "$env_file"
    fi
    set +a
    MAGNETO_DIAG_REANNOUNCE="$should_reannounce" \
      PYTHONPATH="${repo_dir}/src${PYTHONPATH:+:${PYTHONPATH}}" \
      "$(python_bin)" - <<'PY'
from __future__ import annotations

import os
import sys

from magneto.config import AppConfig, ConfigurationError
from magneto.transmission import TransmissionClient, TransmissionError

fields = [
    "id",
    "name",
    "status",
    "metadataPercentComplete",
    "percentDone",
    "rateDownload",
    "rateUpload",
    "peersConnected",
    "trackerStats",
]

try:
    config = AppConfig.from_env()
    client = TransmissionClient(
        config.transmission_url,
        username=config.username,
        password=config.password,
        timeout=config.request_timeout,
    )
    torrents = client.call("torrent-get", {"fields": fields}).get("torrents", [])
except (ConfigurationError, TransmissionError) as exc:
    print(f"error: could not query Transmission RPC: {exc}", file=sys.stderr)
    raise SystemExit(1)

print(f"Transmission RPC: {len(torrents)} torrent(s) visible")
for torrent in torrents:
    torrent_id = torrent.get("id")
    name = str(torrent.get("name") or "<unnamed>")[:90]
    metadata = float(torrent.get("metadataPercentComplete") or 0.0) * 100
    done = float(torrent.get("percentDone") or 0.0) * 100
    peers = int(torrent.get("peersConnected") or 0)
    down = int(torrent.get("rateDownload") or 0)
    up = int(torrent.get("rateUpload") or 0)
    print(
        f"- #{torrent_id} {name}: metadata={metadata:.1f}% "
        f"done={done:.1f}% peers={peers} rates={down}/{up} B/s"
    )
    for tracker in (torrent.get("trackerStats") or [])[:6]:
        host = tracker.get("host") or tracker.get("announce") or "<tracker>"
        result = tracker.get("lastAnnounceResult") or tracker.get("lastScrapeResult") or ""
        succeeded = tracker.get("lastAnnounceSucceeded")
        timed_out = tracker.get("lastAnnounceTimedOut")
        suffix = f" result={result}" if result else ""
        print(f"    tracker {host}: ok={succeeded} timeout={timed_out}{suffix}")

if os.environ.get("MAGNETO_DIAG_REANNOUNCE") == "1" and torrents:
    ids = [torrent["id"] for torrent in torrents if "id" in torrent]
    client.call("torrent-reannounce", {"ids": ids})
    print(f"requested reannounce for {len(ids)} torrent(s)")
PY
  )
}

require_cmd sudo
require_cmd systemctl
require_cmd journalctl
require_cmd nft
require_cmd ss
require_cmd ip
require_cmd python3

uid="$(resolve_uid)"
since="$(date '+%Y-%m-%d %H:%M:%S')"

section "Enabling temporary guard reject logging"
install_guard 1
logging_enabled=1

section "Restarting ${service_unit}"
as_root systemctl restart "$service_unit"
as_root systemctl --no-pager --lines=30 status "$service_unit" || true

section "VPN and route state"
if command -v nordvpn >/dev/null 2>&1; then
  nordvpn status || true
fi
ip -brief link show "$vpn_interface" || true
ip route get 1.1.1.1 uid "$uid" || true
as_root ss -ltnup "( sport = :${rpc_port} or sport = :51413 )" || true

section "Torrent status before wait"
if ! inspect_torrents "$reannounce"; then
  echo "warning: torrent RPC inspection failed; continuing with guard diagnostics" >&2
fi

section "Waiting ${seconds}s for tracker attempts"
sleep "$seconds"

section "Torrent status after wait"
if ! inspect_torrents 0; then
  echo "warning: torrent RPC inspection failed after wait" >&2
fi

section "Guard counters"
as_root nft list table inet "$nft_table" || true

section "Kernel reject log lines since ${since}"
if ! as_root journalctl -k --since "$since" --no-pager | grep 'magneto-transmission-reject'; then
  echo "ok: no magneto-transmission-reject kernel log lines captured"
fi

if [[ "$restore_guard" -eq 0 ]]; then
  echo
  echo "Reject logging is still enabled because --keep-logging was set."
fi
