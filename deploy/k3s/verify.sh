#!/usr/bin/env bash
# verify.sh — prove the magneto pod's network policy and its path to Transmission. Every probe states what it
# expects; one that cannot run is a FAIL, never an "ok". Needs rpc-proxy.sh on (deploy.sh does that first).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
NS=magneto POD=magneto-verify
fail=0
# shellcheck disable=SC2329  # invoked by the EXIT trap below
cleanup() { kubectl -n "$NS" delete pod "$POD" --ignore-not-found --wait=false >/dev/null 2>&1; }
trap cleanup EXIT
# A previous run's pod may still be terminating (its `sleep` ignores SIGTERM); wait until it is gone.
kubectl -n "$NS" delete pod "$POD" --ignore-not-found --wait=true --timeout=120s >/dev/null 2>&1 || true

RPC_IP="$("$HERE/rpc-proxy.sh" ip)" || { echo "FAIL  cannot tell the node's pod-network address"; exit 2; }
NODE_IP="$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' | awk '{print $1}')"

kubectl apply -f "$HERE/manifests/verify-pod.yaml" >/dev/null
if ! kubectl -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=120s >/dev/null 2>&1; then
  echo "FAIL  the verification pod did not become ready; nothing was verified"
  kubectl -n "$NS" describe pod "$POD" 2>&1 | tail -8
  exit 2
fi

probe() { # probe <expect: open|closed> <label> <host> <port>
  local expect=$1 label=$2 host=$3 port=$4 got
  got="$(kubectl -n "$NS" exec "$POD" -- python3 -c "
import socket
try:
    socket.create_connection(('$host', $port), timeout=5).close(); print('open')
except OSError:
    print('closed')" 2>/dev/null | tail -1)"
  case "$got" in
    open|closed)
      if [ "$got" = "$expect" ]; then echo "ok    $label ($host:$port is $got)"
      else echo "FAIL  $label ($host:$port is $got, expected $expect)"; fail=1; fi ;;
    *) echo "FAIL  $label (could not run the probe inside the pod)"; fail=1 ;;
  esac
}
probe open   "Transmission RPC through the forwarder" "$RPC_IP" 9091
probe closed "host SSH on the pod-network address"     "$RPC_IP" 22
probe closed "host SSH on the node address"            "$NODE_IP" 22
probe closed "the host's web UI port, other address"   "$NODE_IP" 5400
probe closed "internet by address"                     1.1.1.1 443
probe closed "link-local metadata"                     169.254.169.254 80
probe closed "Kubernetes API"                          10.43.0.1 443
probe closed "Kubernetes API on the node address"      "$NODE_IP" 6443
probe closed "Kubernetes API on the pod-network address" "$RPC_IP" 6443
probe closed "in-cluster registry"                     10.43.0.50 5000
probe closed "another service's pod (locality)"        10.43.0.60 5434

check() { # check <label> <command run in the verification pod>
  if kubectl -n "$NS" exec "$POD" -- sh -c "$2" >/dev/null 2>&1; then echo "ok    $1"
  else echo "FAIL  $1"; fail=1; fi
}
echo "--- identity:"
check "no service-account token mounted" 'test ! -e /var/run/secrets/kubernetes.io'
check "root filesystem is read-only"     '! touch /app/.write-probe'

echo "--- the running pod, end to end:"
if kubectl -n "$NS" exec deploy/magneto-web -- python3 -c "
import json, urllib.request
for path in ('/healthz', '/healthz/transmission'):
    with urllib.request.urlopen('http://127.0.0.1:5400' + path, timeout=15) as r:
        assert json.load(r).get('ok') is True, path
" 2>/dev/null; then echo "ok    the UI answers and Transmission accepts its credentials"
else echo "FAIL  the UI or Transmission did not answer (is rpc-proxy.sh on, and are the credentials right?)"; fail=1; fi
exit $fail
