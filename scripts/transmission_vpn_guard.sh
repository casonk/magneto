#!/usr/bin/env bash
# Manage nftables rules that restrict Transmission to a VPN interface.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  transmission_vpn_guard.sh COMMAND [options]

Commands:
  apply     Install or replace the nftables guard table
  remove    Delete the nftables guard table
  status    Show the active guard table
  render    Print the nftables rules without applying them

Options:
  --transmission-user USER  Transmission daemon user. Default: TRANSMISSION_USER or transmission
  --uid UID                 Numeric UID override
  --vpn-interface IFACE     VPN provider interface. Default: VPN_INTERFACE or nordlynx
  --rpc-port PORT           Local Transmission RPC port. Default: RPC_PORT or 9091
  --table NAME              nftables table name. Default: NFT_TABLE or magneto_transmission_vpn_guard
  --allow-vpn-transport     Allow marked WireGuard/NordLynx transport packets. Default.
  --no-vpn-transport        Block marked WireGuard/NordLynx transport packets too
  --vpn-transport-fwmark M  Firewall mark for VPN transport packets. Default: 0xe1f1
  --vpn-transport-port P    UDP port for VPN transport packets. Default: 51820
  --allow-loopback-dns      Allow Transmission to query the local DNS stub on loopback
  --allow-local-dns         Allow all loopback traffic for Transmission
  --log-rejects             Log rejected Transmission packets to the kernel log
  -h, --help                Show this help

The default allows Transmission traffic through --vpn-interface, marked
WireGuard/NordLynx transport packets required to carry that traffic, loopback DNS
to the local system resolver, and loopback RPC responses on --rpc-port. That
avoids normal-gateway leaks if the VPN drops.
USAGE
}

command="${1:-}"
if [[ -z "$command" || "$command" == "-h" || "$command" == "--help" ]]; then
  usage
  exit 0
fi
shift

transmission_user="${TRANSMISSION_USER:-transmission}"
uid_override="${TRANSMISSION_UID:-}"
vpn_interface="${VPN_INTERFACE:-nordlynx}"
rpc_port="${RPC_PORT:-9091}"
nft_table="${NFT_TABLE:-magneto_transmission_vpn_guard}"
allow_local_dns="${ALLOW_LOCAL_DNS:-0}"
allow_loopback_dns="${ALLOW_LOOPBACK_DNS:-1}"
log_rejects="${LOG_REJECTS:-0}"
allow_vpn_transport="${ALLOW_VPN_TRANSPORT:-1}"
vpn_transport_fwmark="${VPN_TRANSPORT_FWMARK:-0xe1f1}"
vpn_transport_port="${VPN_TRANSPORT_PORT:-51820}"

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
    --allow-local-dns)
      allow_local_dns=1
      shift
      ;;
    --allow-loopback-dns)
      allow_loopback_dns=1
      shift
      ;;
    --log-rejects)
      log_rejects=1
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

validate_identifier() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "error: invalid ${label}: ${value}" >&2
    exit 2
  fi
}

validate_interface() {
  if [[ ! "$vpn_interface" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    echo "error: invalid VPN interface name: ${vpn_interface}" >&2
    exit 2
  fi
}

validate_port() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( 10#$value < 1 || 10#$value > 65535 )); then
    echo "error: invalid ${label}: ${value}" >&2
    exit 2
  fi
}

validate_mark() {
  if [[ ! "$vpn_transport_fwmark" =~ ^(0x[0-9A-Fa-f]+|[0-9]+)$ ]]; then
    echo "error: invalid VPN transport firewall mark: ${vpn_transport_fwmark}" >&2
    exit 2
  fi
}

truthy() {
  [[ "${1:-}" =~ ^(1|true|yes|on)$ ]]
}

resolve_uid() {
  if [[ -n "$uid_override" ]]; then
    if [[ ! "$uid_override" =~ ^[0-9]+$ ]]; then
      echo "error: invalid UID: ${uid_override}" >&2
      exit 2
    fi
    printf '%s\n' "$uid_override"
    return
  fi
  if ! id -u "$transmission_user" >/dev/null 2>&1; then
    echo "error: user not found: ${transmission_user}" >&2
    exit 1
  fi
  id -u "$transmission_user"
}

render_rules() {
  local uid="$1"
  local loopback_rules
  local reject_rule
  local vpn_transport_rules
  if truthy "$allow_local_dns"; then
    loopback_rules="    meta skuid ${uid} oifname \"lo\" counter accept"
  else
    loopback_rules=""
    if truthy "$allow_loopback_dns"; then
      loopback_rules+="    meta skuid ${uid} oifname \"lo\" ip daddr 127.0.0.53 udp dport 53 counter accept"$'\n'
      loopback_rules+="    meta skuid ${uid} oifname \"lo\" ip daddr 127.0.0.53 tcp dport 53 counter accept"$'\n'
    fi
    loopback_rules+="    meta skuid ${uid} oifname \"lo\" tcp sport ${rpc_port} counter accept"
  fi
  if truthy "$allow_vpn_transport"; then
    vpn_transport_rules="    meta skuid ${uid} meta mark ${vpn_transport_fwmark} udp dport ${vpn_transport_port} counter accept"
  else
    vpn_transport_rules=""
  fi
  if truthy "$log_rejects"; then
    reject_rule="    meta skuid ${uid} counter log prefix \"magneto-transmission-reject \" flags all reject with icmpx type admin-prohibited"
  else
    reject_rule="    meta skuid ${uid} counter reject with icmpx type admin-prohibited"
  fi

  cat <<EOF
table inet ${nft_table} {
  chain output {
    type filter hook output priority 0; policy accept;
    meta skuid ${uid} oifname "${vpn_interface}" counter accept
${vpn_transport_rules}
${loopback_rules}
${reject_rule}
  }
}
EOF
}

validate_identifier "nftables table name" "$nft_table"
validate_interface
validate_port "RPC port" "$rpc_port"
if truthy "$allow_vpn_transport"; then
  validate_port "VPN transport port" "$vpn_transport_port"
  validate_mark
fi
if ! resolved_uid="$(resolve_uid)"; then
  exit 1
fi
if [[ -z "$resolved_uid" ]]; then
  echo "error: could not resolve Transmission UID" >&2
  exit 1
fi

case "$command" in
  render)
    render_rules "$resolved_uid"
    ;;
  apply)
    if ! command -v nft >/dev/null 2>&1; then
      echo "error: nft command not found" >&2
      exit 1
    fi
    tmp="$(mktemp)"
    render_rules "$resolved_uid" > "$tmp"
    nft delete table inet "$nft_table" >/dev/null 2>&1 || true
    nft -f "$tmp"
    rm -f "$tmp"
    nft list table inet "$nft_table"
    ;;
  remove)
    if ! command -v nft >/dev/null 2>&1; then
      echo "error: nft command not found" >&2
      exit 1
    fi
    nft delete table inet "$nft_table" >/dev/null 2>&1 || true
    ;;
  status)
    if ! command -v nft >/dev/null 2>&1; then
      echo "error: nft command not found" >&2
      exit 1
    fi
    nft list table inet "$nft_table"
    ;;
  *)
    echo "error: unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
