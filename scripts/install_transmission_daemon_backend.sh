#!/usr/bin/env bash
# Install/configure transmission-daemon as Magneto's VPN-guarded backend.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/install_transmission_daemon_backend.sh [options]

Options:
  --download-dir DIR         Torrent download directory (default: MAGNETO_DOWNLOAD_DIR or /srv/snowbridge/share/torrents)
  --rpc-port PORT            Transmission RPC port (default: 9091)
  --vpn-interface IFACE      VPN provider interface for the guard (default: nordlynx)
  --keepass-profile PROFILE  auto-pass profile for RPC auth (default: infra)
  --keepass-entry ENTRY      auto-pass entry for RPC auth (default: magneto@transmission)
  --auto-pass-env FILE       auto-pass env file (default: ../auto-pass/config/auto-pass.env.local)
  --no-vpn-guard             Configure/start daemon without installing the VPN guard
  --stop-gtk                 Stop a running transmission-gtk process if it owns the RPC port
  -h, --help                 Show this help

This script is intended for Fedora/dnf hosts. It keeps RPC bound to 127.0.0.1,
requires RPC authentication, and limits the daemon user's egress through the VPN
guard unless --no-vpn-guard is used.
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parent_dir="$(dirname "$repo_dir")"
env_file="${repo_dir}/config/magneto.env.local"

download_dir="${MAGNETO_DOWNLOAD_DIR:-/srv/snowbridge/share/torrents}"
rpc_port="9091"
vpn_interface="nordlynx"
keepass_profile="infra"
keepass_entry="magneto@transmission"
auto_pass_env="${parent_dir}/auto-pass/config/auto-pass.env.local"
install_vpn_guard=1
stop_gtk=0
service_unit="transmission-daemon.service"
daemon_user="transmission"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --download-dir)
      download_dir="${2:?--download-dir requires a value}"
      shift 2
      ;;
    --rpc-port)
      rpc_port="${2:?--rpc-port requires a value}"
      shift 2
      ;;
    --vpn-interface)
      vpn_interface="${2:?--vpn-interface requires a value}"
      shift 2
      ;;
    --keepass-profile)
      keepass_profile="${2:?--keepass-profile requires a value}"
      shift 2
      ;;
    --keepass-entry)
      keepass_entry="${2:?--keepass-entry requires a value}"
      shift 2
      ;;
    --auto-pass-env)
      auto_pass_env="${2:?--auto-pass-env requires a value}"
      shift 2
      ;;
    --no-vpn-guard)
      install_vpn_guard=0
      shift
      ;;
    --stop-gtk)
      stop_gtk=1
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

run_step() {
  local title="$1"
  shift
  echo
  echo "==> $title"
  "$@"
}

as_root() {
  sudo "$@"
}

auto_pass_get() {
  local field="$1"
  auto-pass --env-file "$auto_pass_env" --profile "$keepass_profile" \
    get "$keepass_entry" --field "$field"
}

install_packages() {
  as_root dnf install -y transmission-daemon transmission-cli
}

ensure_download_dir() {
  if ! getent group snowbridge >/dev/null 2>&1; then
    echo "error: snowbridge group does not exist; refusing to guess download permissions." >&2
    exit 1
  fi
  as_root usermod -aG snowbridge "$daemon_user"
  as_root install -d -o "$daemon_user" -g snowbridge -m 2770 "$download_dir"
  if command -v restorecon >/dev/null 2>&1; then
    as_root restorecon -RF "$download_dir" || true
  fi
}

settings_file_for_daemon() {
  local home_dir
  home_dir="$(getent passwd "$daemon_user" | cut -d: -f6)"
  if [[ -z "$home_dir" ]]; then
    home_dir="/var/lib/transmission"
  fi
  printf '%s\n' "${home_dir}/.config/transmission-daemon/settings.json"
}

write_daemon_settings() {
  local rpc_username rpc_password settings_file settings_dir tmp_settings password_file
  rpc_username="$(auto_pass_get username)"
  rpc_password="$(auto_pass_get password)"
  if [[ -z "$rpc_username" || -z "$rpc_password" ]]; then
    echo "error: auto-pass did not return both username and password for $keepass_entry" >&2
    exit 1
  fi

  as_root systemctl stop "$service_unit" >/dev/null 2>&1 || true

  settings_file="$(settings_file_for_daemon)"
  settings_dir="$(dirname "$settings_file")"
  as_root install -d -o "$daemon_user" -g "$daemon_user" -m 0750 "$settings_dir"

  tmp_settings="$(mktemp)"
  if as_root test -f "$settings_file"; then
    as_root cp "$settings_file" "$tmp_settings"
    as_root cp -a "$settings_file" "${settings_file}.bak.$(date +%Y%m%d%H%M%S)"
  elif sudo -u "$daemon_user" transmission-daemon --dump-settings > "$tmp_settings"; then
    true
  else
    printf '{}\n' > "$tmp_settings"
  fi

  password_file="$(mktemp)"
  chmod 0600 "$password_file"
  printf '%s' "$rpc_password" > "$password_file"

  if ! python3 - "$tmp_settings" "$download_dir" "$rpc_port" "$rpc_username" "$password_file" <<'PY'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
download_dir = sys.argv[2]
rpc_port = int(sys.argv[3])
rpc_username = sys.argv[4]
rpc_password = Path(sys.argv[5]).read_text(encoding="utf-8")

try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
except json.JSONDecodeError:
    settings = {}

settings.update(
    {
        "download_dir": download_dir,
        "incomplete_dir_enabled": False,
        "lpd_enabled": False,
        "port_forwarding_enabled": False,
        "rpc_authentication_required": True,
        "rpc_bind_address": "127.0.0.1",
        "rpc_enabled": True,
        "rpc_password": rpc_password,
        "rpc_port": rpc_port,
        "rpc_url": "/transmission/",
        "rpc_username": rpc_username,
        "rpc_whitelist": "127.0.0.1,::1",
        "rpc_whitelist_enabled": True,
        "umask": "002",
    }
)
settings_path.write_text(json.dumps(settings, indent=4, sort_keys=True) + "\n", encoding="utf-8")
PY
  then
    rm -f "$password_file"
    exit 1
  fi
  rm -f "$password_file"

  as_root install -o "$daemon_user" -g "$daemon_user" -m 0600 "$tmp_settings" "$settings_file"
  rm -f "$tmp_settings"
  echo "ok: wrote $settings_file"
}

port_owner() {
  ss -ltnp "sport = :${rpc_port}" 2>/dev/null | awk '/LISTEN/ {print}'
}

port_owner_pids() {
  port_owner | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

handle_rpc_port_conflict() {
  local owner
  owner="$(port_owner || true)"
  if [[ -z "$owner" ]]; then
    return
  fi
  if grep -q "transmission-daemon" <<<"$owner"; then
    return
  fi
  if [[ "$stop_gtk" -eq 1 ]] && grep -q "transmission-gt" <<<"$owner"; then
    echo "Stopping transmission-gtk so transmission-daemon can own RPC port $rpc_port"
    mapfile -t owner_pids < <(port_owner_pids || true)
    if [[ "${#owner_pids[@]}" -gt 0 ]]; then
      kill "${owner_pids[@]}" 2>/dev/null || true
    fi
    pkill -f '(^|[/ ])transmission-gtk($| )' 2>/dev/null || true
    for _ in $(seq 1 40); do
      if [[ -z "$(port_owner || true)" ]]; then
        return
      fi
      sleep 0.25
    done
    mapfile -t owner_pids < <(port_owner_pids || true)
    if [[ "${#owner_pids[@]}" -gt 0 ]]; then
      kill -KILL "${owner_pids[@]}" 2>/dev/null || true
      sleep 0.25
    fi
  fi
  owner="$(port_owner || true)"
  if [[ -n "$owner" && ! "$owner" =~ transmission-daemon ]]; then
    echo "error: RPC port $rpc_port is already in use:" >&2
    echo "$owner" >&2
    echo "  Close Transmission GTK or rerun with --stop-gtk." >&2
    exit 1
  fi
}

install_guard() {
  "$repo_dir/scripts/install_transmission_vpn_guard.sh" \
    --transmission-user "$daemon_user" \
    --transmission-service "$service_unit" \
    --vpn-interface "$vpn_interface" \
    --rpc-port "$rpc_port"
}

systemd_exec_arg() {
  local value="$1"
  if [[ "$value" =~ [[:space:]] ]]; then
    echo "error: systemd ExecStart argument contains whitespace: $value" >&2
    exit 1
  fi
  printf '%s\n' "$value"
}

write_daemon_service_override() {
  local dropin_dir dropin_file safe_download_dir safe_rpc_port tmp_dropin
  dropin_dir="/etc/systemd/system/${service_unit}.d"
  dropin_file="${dropin_dir}/20-magneto-backend.conf"
  safe_download_dir="$(systemd_exec_arg "$download_dir")"
  safe_rpc_port="$(systemd_exec_arg "$rpc_port")"

  tmp_dropin="$(mktemp)"
  cat > "$tmp_dropin" <<DROPIN
[Service]
ExecStart=
ExecStart=/usr/bin/transmission-daemon -f --log-level=error --rpc-bind-address 127.0.0.1 --allowed 127.0.0.1,::1 --port ${safe_rpc_port} --auth --download-dir ${safe_download_dir} --no-portmap --no-lpd
DROPIN
  as_root install -D -m 0644 "$tmp_dropin" "$dropin_file"
  rm -f "$tmp_dropin"
  as_root systemctl daemon-reload
  echo "ok: wrote $dropin_file"
}

start_daemon() {
  handle_rpc_port_conflict
  as_root systemctl enable --now "$service_unit"
  as_root systemctl restart "$service_unit"
  as_root systemctl status "$service_unit" --no-pager
}

verify_magneto_rpc() {
  set -a
  # shellcheck source=/dev/null
  source "$env_file"
  set +a
  "$repo_dir/.venv/bin/python" - <<'PY'
from magneto.config import AppConfig
from magneto.transmission import TransmissionClient

config = AppConfig.from_env()
client = TransmissionClient(
    config.transmission_url,
    username=config.username,
    password=config.password,
    timeout=config.request_timeout,
)
torrents = client.list_torrents()
print(f"ok: Magneto can reach transmission-daemon; {len(torrents)} torrent(s) visible")
PY
}

require_cmd auto-pass
require_cmd dnf
require_cmd python3
require_cmd ss
require_cmd sudo

run_step "Installing Transmission daemon package" install_packages
run_step "Preparing Snowbridge download directory" ensure_download_dir
run_step "Writing Transmission daemon settings" write_daemon_settings
run_step "Writing Transmission daemon systemd override" write_daemon_service_override
run_step "Checking RPC port availability" handle_rpc_port_conflict

if [[ "$install_vpn_guard" -eq 1 ]]; then
  run_step "Installing VPN egress guard" install_guard
else
  echo
  echo "==> Skipping VPN guard install"
fi

run_step "Starting Transmission daemon" start_daemon
run_step "Verifying Magneto RPC access" verify_magneto_rpc

echo
echo "Transmission daemon backend is ready."
