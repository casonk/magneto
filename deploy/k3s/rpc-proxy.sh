#!/usr/bin/env bash
# rpc-proxy.sh on|off|status|ip — let the magneto pod reach the host's Transmission RPC. No sudo.
# Transmission listens on 127.0.0.1:9091 only. A user socket on the node's pod-network address (the address pods
# see for the host) forwards that port to loopback, so nothing new is exposed on the LAN. Cilium admits the pod to
# that one host port and nothing else.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ip_of() {
  local ip
  ip="$(ip -4 -o addr show dev "${MAGNETO_RPC_INTERFACE:-cilium_host}" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)"
  [ -n "$ip" ] || { echo "no IPv4 address on ${MAGNETO_RPC_INTERFACE:-cilium_host}: is K3s running?" >&2; return 1; }
  printf '%s\n' "$ip"
}
case "${1:-status}" in
  ip) ip_of ;;
  on)
    rpc_ip="$(ip_of)"
    install -d "$UNITS"
    sed "s#__RPC_IP__#$rpc_ip#g" "$HERE/systemd/magneto-rpc.socket" >"$UNITS/magneto-rpc.socket"
    install -m 644 "$HERE/systemd/magneto-rpc.service" "$UNITS/"
    systemctl --user daemon-reload
    systemctl --user enable --now magneto-rpc.socket
    # Restart if the address changed since the socket was last started (a K3s reinstall can hand out another one).
    systemctl --user restart magneto-rpc.socket
    echo "Transmission RPC forwarded on $rpc_ip:9091"
    ;;
  off)
    systemctl --user disable --now magneto-rpc.socket magneto-rpc.service 2>/dev/null || true
    rm -f "$UNITS/magneto-rpc.socket" "$UNITS/magneto-rpc.service"
    systemctl --user daemon-reload
    ;;
  status)
    printf '%-24s %-9s %s\n' magneto-rpc.socket "$(systemctl --user is-active magneto-rpc.socket 2>/dev/null || true)" \
      "$(systemctl --user is-enabled magneto-rpc.socket 2>/dev/null || true)"
    ;;
  *) echo "usage: $0 on|off|status|ip"; exit 2 ;;
esac
