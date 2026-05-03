#!/usr/bin/env bash
# Install the Transmission VPN guard as a systemd-managed nftables rule set.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/install_transmission_vpn_guard.sh [options]

Options:
  --transmission-user USER      Transmission daemon user. Default: transmission
  --uid UID                     Numeric UID override for Transmission
  --vpn-interface IFACE         VPN provider interface. Default: nordlynx
  --rpc-port PORT               Local Transmission RPC port to allow on loopback. Default: 9091
  --table NAME                  nftables table name. Default: magneto_transmission_vpn_guard
  --allow-vpn-transport         Allow marked WireGuard/NordLynx transport packets. Default.
  --no-vpn-transport            Block marked WireGuard/NordLynx transport packets too
  --vpn-transport-fwmark MARK   Firewall mark for VPN transport packets. Default: 0xe1f1
  --vpn-transport-port PORT     UDP port for VPN transport packets. Default: 51820
  --transmission-service UNIT   Transmission systemd unit for dependency drop-in.
                                Default: auto-detect transmission-daemon.service or transmission.service
  --no-drop-in                  Do not create a Transmission service dependency drop-in
  --allow-loopback-dns          Allow Transmission to query the local DNS stub on loopback. Default.
  --no-loopback-dns             Block loopback DNS too
  --allow-local-dns             Allow all loopback traffic for Transmission
  --log-rejects                 Log rejected Transmission packets to the kernel log
  --allow-shared-user           Permit guarding your current login UID. Usually unsafe.
  --no-start                    Install files but do not enable/start the guard service
  -h, --help                    Show this help

The default policy blocks Transmission-owned network traffic unless it leaves
through the VPN interface or is a marked WireGuard/NordLynx transport packet
carrying VPN traffic. Loopback is limited to DNS requests to the local resolver
and RPC responses on --rpc-port.
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_script="${repo_dir}/scripts/transmission_vpn_guard.sh"

transmission_user="transmission"
uid_override=""
vpn_interface="nordlynx"
rpc_port="9091"
nft_table="magneto_transmission_vpn_guard"
allow_vpn_transport=1
vpn_transport_fwmark="0xe1f1"
vpn_transport_port="51820"
transmission_service="auto"
write_drop_in=1
allow_local_dns=0
allow_loopback_dns=1
log_rejects=0
allow_shared_user=0
start_service=1

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
    --transmission-service)
      transmission_service="${2:?--transmission-service requires a value}"
      shift 2
      ;;
    --no-drop-in)
      write_drop_in=0
      shift
      ;;
    --allow-local-dns)
      allow_local_dns=1
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
    --log-rejects)
      log_rejects=1
      shift
      ;;
    --allow-shared-user)
      allow_shared_user=1
      shift
      ;;
    --no-start)
      start_service=0
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

if [[ ! -f "$runtime_script" ]]; then
  echo "error: runtime script not found: $runtime_script" >&2
  exit 1
fi

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

detect_transmission_service() {
  if [[ "$transmission_service" != "auto" ]]; then
    printf '%s\n' "$transmission_service"
    return
  fi
  for candidate in transmission-daemon.service transmission.service; do
    if systemctl list-unit-files "$candidate" --no-legend 2>/dev/null | grep -q "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '%s\n' ""
}

service_unit="$(detect_transmission_service)"

if [[ -z "$uid_override" && "$transmission_user" == "transmission" && -n "$service_unit" ]]; then
  unit_user="$(systemctl show "$service_unit" -p User --value 2>/dev/null || true)"
  if [[ -n "$unit_user" ]]; then
    transmission_user="$unit_user"
  fi
fi

unit_exists() {
  local unit="$1"
  systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "$unit"
}

resolve_guard_uid() {
  if [[ -n "$uid_override" ]]; then
    if [[ ! "$uid_override" =~ ^[0-9]+$ ]]; then
      echo "error: invalid UID: $uid_override" >&2
      exit 2
    fi
    printf '%s\n' "$uid_override"
    return
  fi
  if ! id -u "$transmission_user" >/dev/null 2>&1; then
    echo "error: Transmission user does not exist: $transmission_user" >&2
    echo "  This guard must target a dedicated daemon user, not the Flatpak/GTK app running as your login user." >&2
    echo "  Install/configure transmission-daemon first, then rerun with that daemon user." >&2
    exit 1
  fi
  id -u "$transmission_user"
}

guard_uid="$(resolve_guard_uid)"
login_uid="${SUDO_UID:-$(id -u)}"
if [[ "$guard_uid" == "$login_uid" && "$allow_shared_user" -ne 1 ]]; then
  echo "error: refusing to guard your current login UID ($guard_uid)." >&2
  echo "  That would block non-VPN network traffic for your whole desktop session." >&2
  echo "  Use a dedicated Transmission daemon user, or pass --allow-shared-user if you intentionally accept that." >&2
  exit 1
fi

if [[ "$write_drop_in" -eq 1 && "$transmission_service" != "auto" && -n "$service_unit" ]]; then
  if ! unit_exists "$service_unit"; then
    echo "error: requested Transmission unit does not exist: $service_unit" >&2
    echo "  Install/enable the daemon unit first, or omit --transmission-service for auto-detect." >&2
    exit 1
  fi
fi

echo "==> Installing runtime guard"
as_root install -D -m 0755 "$runtime_script" /usr/local/sbin/magneto-transmission-vpn-guard

echo "==> Writing /etc/magneto/transmission-vpn-guard.env"
tmp_env="$(mktemp)"
cat > "$tmp_env" <<ENV
TRANSMISSION_USER=${transmission_user}
TRANSMISSION_UID=${uid_override}
VPN_INTERFACE=${vpn_interface}
RPC_PORT=${rpc_port}
NFT_TABLE=${nft_table}
ALLOW_VPN_TRANSPORT=${allow_vpn_transport}
VPN_TRANSPORT_FWMARK=${vpn_transport_fwmark}
VPN_TRANSPORT_PORT=${vpn_transport_port}
ALLOW_LOCAL_DNS=${allow_local_dns}
ALLOW_LOOPBACK_DNS=${allow_loopback_dns}
LOG_REJECTS=${log_rejects}
ENV
as_root install -D -m 0644 "$tmp_env" /etc/magneto/transmission-vpn-guard.env
rm -f "$tmp_env"

echo "==> Writing magneto-transmission-vpn-guard.service"
tmp_unit="$(mktemp)"
cat > "$tmp_unit" <<UNIT
[Unit]
Description=Magneto Transmission VPN egress guard
Documentation=file:${repo_dir}/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/magneto/transmission-vpn-guard.env
ExecStart=/usr/local/sbin/magneto-transmission-vpn-guard apply
ExecStop=/usr/local/sbin/magneto-transmission-vpn-guard remove

[Install]
WantedBy=multi-user.target
UNIT
as_root install -D -m 0644 "$tmp_unit" /etc/systemd/system/magneto-transmission-vpn-guard.service
rm -f "$tmp_unit"

if [[ "$write_drop_in" -eq 1 ]]; then
  if [[ -n "$service_unit" ]]; then
    echo "==> Writing dependency drop-in for ${service_unit}"
    tmp_dropin="$(mktemp)"
    cat > "$tmp_dropin" <<'DROPIN'
[Unit]
Requires=magneto-transmission-vpn-guard.service
After=magneto-transmission-vpn-guard.service
DROPIN
    as_root install -D -m 0644 "$tmp_dropin" "/etc/systemd/system/${service_unit}.d/10-magneto-vpn-guard.conf"
    rm -f "$tmp_dropin"
  else
    echo "warning: no Transmission unit detected; skipping dependency drop-in." >&2
  fi
fi

as_root systemctl daemon-reload
as_root systemctl reset-failed magneto-transmission-vpn-guard.service >/dev/null 2>&1 || true

if [[ "$start_service" -eq 1 ]]; then
  echo "==> Enabling and restarting magneto-transmission-vpn-guard.service"
  as_root systemctl enable magneto-transmission-vpn-guard.service
  as_root systemctl restart magneto-transmission-vpn-guard.service
  as_root systemctl status magneto-transmission-vpn-guard.service --no-pager
else
  echo "Installed but not started. Start with:"
  echo "  sudo systemctl enable --now magneto-transmission-vpn-guard.service"
fi

if [[ -n "$service_unit" ]]; then
  echo
  echo "Transmission dependency drop-in target: ${service_unit}"
  echo "Restart Transmission after reviewing the guard status:"
  echo "  sudo systemctl restart ${service_unit}"
fi
