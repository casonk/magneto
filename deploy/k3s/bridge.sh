#!/usr/bin/env bash
# bridge.sh on|off|status — switch 127.0.0.1:5400 between the host service and the K3s pod. No sudo.
#   on : stop and disable the host service, listen on 127.0.0.1:5400 and forward to the pod
#   off: stop the forwarder, then enable and start the host service again (the rollback)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
HOST_UNIT="magneto-web.service"
PORT="${MAGNETO_PORT:-5400}"
case "${1:-status}" in
  on)
    kubectl --kubeconfig "${KUBECONFIG:-$HOME/.kube/k3s.yaml}" -n magneto rollout status deploy/magneto-web --timeout=60s
    install -d "$UNITS"
    install -m 644 "$HERE/systemd/magneto-proxy.socket" "$HERE/systemd/magneto-proxy.service" "$UNITS/"
    systemctl --user daemon-reload
    # Disable as well as stop: both units are wanted at login, and two listeners on the port would race.
    systemctl --user disable --now "$HOST_UNIT"
    systemctl --user enable --now magneto-proxy.socket
    for _ in $(seq 1 15); do
      if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then echo "answered by the pod"; exit 0; fi
      sleep 2
    done
    echo "the pod did not answer on 127.0.0.1:$PORT" >&2
    exit 1
    ;;
  off)
    systemctl --user disable --now magneto-proxy.socket magneto-proxy.service 2>/dev/null || true
    systemctl --user enable --now "$HOST_UNIT"
    ;;
  status)
    for u in "$HOST_UNIT" magneto-proxy.socket; do
      printf '%-30s %-9s %s\n' "$u" "$(systemctl --user is-active "$u" 2>/dev/null || true)" "$(systemctl --user is-enabled "$u" 2>/dev/null || true)"
    done
    ;;
  *) echo "usage: $0 on|off|status"; exit 2 ;;
esac
