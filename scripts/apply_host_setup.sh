#!/usr/bin/env bash
# Apply the normal host-side Magneto runtime setup in one pass.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/apply_host_setup.sh [options]

Default behavior:
  - create/update the Magneto virtualenv
  - create config/magneto.env.local when missing
  - verify Transmission credentials through auto-pass
  - verify Transmission RPC accepts those credentials
  - stop any old manual "python -m magneto web" process from this repo
  - install/restart magneto-web.service as a user service
  - verify the local health endpoint

Options:
  --with-wiring-harness       Also refresh wiring-harness DNS, mTLS SANs, and Caddy
  --wg-ip IP                  WireGuard server IP for wiring-harness (default: 10.99.0.1)
  --cleanup-vpn-guard         Remove the previously installed system VPN guard unit/drop-in
  --install-vpn-guard         Install/start the VPN guard after web setup
  --transmission-user USER    Dedicated Transmission daemon user for VPN guard
  --transmission-service UNIT Transmission daemon systemd unit for VPN guard drop-in
  --vpn-interface IFACE       VPN interface for VPN guard (default: nordlynx)
  --rpc-port PORT             Transmission RPC port (default: 9091)
  --skip-rpc-check            Do not call Transmission RPC during verification
  --skip-web                  Do not install/restart magneto-web.service
  -h, --help                  Show this help

Do not use --install-vpn-guard against transmission-gtk running as your normal
login user. The UID-based guard is meant for a dedicated daemon user.
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parent_dir="$(dirname "$repo_dir")"
venv_dir="${repo_dir}/.venv"
env_file="${repo_dir}/config/magneto.env.local"

with_wiring_harness=0
cleanup_vpn_guard=0
install_vpn_guard=0
skip_rpc_check=0
skip_web=0
wg_ip="${WH_WG_IP:-10.99.0.1}"
transmission_user="transmission"
transmission_service=""
vpn_interface="nordlynx"
rpc_port="9091"

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
    --cleanup-vpn-guard)
      cleanup_vpn_guard=1
      shift
      ;;
    --install-vpn-guard)
      install_vpn_guard=1
      shift
      ;;
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
    --skip-rpc-check)
      skip_rpc_check=1
      shift
      ;;
    --skip-web)
      skip_web=1
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

ensure_runtime_files() {
  if [[ ! -d "$venv_dir" ]]; then
    python3 -m venv "$venv_dir"
  fi
  "$venv_dir/bin/python" -m pip install --upgrade pip
  "$venv_dir/bin/python" -m pip install -e "$repo_dir"

  if [[ ! -f "$env_file" ]]; then
    cp "$repo_dir/config/magneto.env.example" "$env_file"
    chmod 600 "$env_file"
    echo "Created $env_file; review it before exposing the site."
  fi
}

verify_config_and_rpc() {
  set -a
  # shellcheck source=/dev/null
  source "$env_file"
  set +a

  "$venv_dir/bin/python" - <<'PY'
from magneto.config import AppConfig

config = AppConfig.from_env()
print(
    "ok: config loaded "
    f"rpc={config.transmission_url} "
    f"username_present={bool(config.username)} "
    f"password_present={bool(config.password)}"
)
if not config.username or not config.password:
    raise SystemExit("error: Transmission RPC auth is required but was not resolved.")
PY

  if [[ "$skip_rpc_check" -eq 1 ]]; then
    echo "Skipping Transmission RPC check."
    return
  fi

  "$venv_dir/bin/python" - <<'PY'
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
print(f"ok: Transmission RPC accepted credentials; {len(torrents)} torrent(s) visible")
PY
}

stop_user_service_and_manual_processes() {
  systemctl --user stop magneto-web.service >/dev/null 2>&1 || true

  local pids=()
  mapfile -t pids < <(pgrep -f "python.*-m magneto web" || true)
  for pid in "${pids[@]}"; do
    [[ -n "$pid" ]] || continue
    [[ "$pid" != "$$" ]] || continue
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    if [[ "$cwd" == "$repo_dir" ]]; then
      echo "Stopping manual Magneto process $pid"
      kill "$pid" 2>/dev/null || true
    fi
  done
}

install_web_service() {
  stop_user_service_and_manual_processes
  "$repo_dir/scripts/install_web_service.sh"
}

verify_web_health() {
  set -a
  # shellcheck source=/dev/null
  source "$env_file"
  set +a
  host="${MAGNETO_HOST:-127.0.0.1}"
  port="${MAGNETO_PORT:-5400}"

  for _ in $(seq 1 40); do
    if curl -fsS "http://${host}:${port}/healthz" >/dev/null; then
      echo "ok: Magneto health endpoint is up at http://${host}:${port}/healthz"
      return
    fi
    sleep 0.25
  done

  echo "error: Magneto health endpoint did not come up at http://${host}:${port}/healthz" >&2
  systemctl --user status magneto-web.service --no-pager >&2 || true
  exit 1
}

cleanup_system_vpn_guard() {
  as_root systemctl disable --now magneto-transmission-vpn-guard.service >/dev/null 2>&1 || true
  as_root rm -f /etc/systemd/system/magneto-transmission-vpn-guard.service
  as_root rm -f /etc/systemd/system/transmission-daemon.service.d/10-magneto-vpn-guard.conf
  as_root rmdir /etc/systemd/system/transmission-daemon.service.d >/dev/null 2>&1 || true
  as_root systemctl daemon-reload
  as_root systemctl reset-failed magneto-transmission-vpn-guard.service >/dev/null 2>&1 || true
  echo "ok: removed stale Magneto Transmission VPN guard unit/drop-in"
}

install_system_vpn_guard() {
  local args=(
    --transmission-user "$transmission_user"
    --vpn-interface "$vpn_interface"
    --rpc-port "$rpc_port"
  )
  if [[ -n "$transmission_service" ]]; then
    args+=(--transmission-service "$transmission_service")
  fi
  "$repo_dir/scripts/install_transmission_vpn_guard.sh" "${args[@]}"
}

apply_wiring_harness() {
  local script="${parent_dir}/wiring-harness/scripts/apply_site_changes.sh"
  if [[ ! -x "$script" ]]; then
    echo "error: wiring-harness apply script not found or not executable: $script" >&2
    exit 1
  fi
  (cd "${parent_dir}/wiring-harness" && bash scripts/apply_site_changes.sh --wg-ip "$wg_ip")
}

require_cmd python3
require_cmd curl
if [[ "$cleanup_vpn_guard" -eq 1 || "$install_vpn_guard" -eq 1 || "$with_wiring_harness" -eq 1 ]]; then
  require_cmd sudo
fi

run_step "Preparing Magneto runtime" ensure_runtime_files
run_step "Verifying Transmission auth" verify_config_and_rpc

if [[ "$skip_web" -eq 0 ]]; then
  run_step "Installing/restarting Magneto user service" install_web_service
  run_step "Checking Magneto web health" verify_web_health
else
  echo
  echo "==> Skipping Magneto web service setup"
fi

if [[ "$cleanup_vpn_guard" -eq 1 ]]; then
  run_step "Cleaning stale VPN guard service" cleanup_system_vpn_guard
fi

if [[ "$install_vpn_guard" -eq 1 ]]; then
  run_step "Installing Transmission VPN guard" install_system_vpn_guard
fi

if [[ "$with_wiring_harness" -eq 1 ]]; then
  run_step "Applying wiring-harness site changes" apply_wiring_harness
fi

echo
echo "Magneto host setup complete."
