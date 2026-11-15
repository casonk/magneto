#!/usr/bin/env bash
# apply.sh — create the magneto web pod in K3s. No sudo. Safe to repeat.
# The namespace, the network policy and the Secret exist before the Deployment. The Transmission credentials are
# resolved from the vault here, on the host, into a private file that is removed on exit; they reach the cluster only
# as a Secret, never on a command line or in a manifest. First time on this machine: build-image.sh comes first.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
ENV_FILE="${MAGNETO_ENV_FILE:-$REPO/config/magneto.env.local}"
PYTHON="${MAGNETO_PYTHON:-$REPO/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

kubectl wait --for=condition=Ready node --all --timeout=60s
kubectl get crd ciliumnetworkpolicies.cilium.io >/dev/null
[ -f "$ENV_FILE" ] || { echo "no settings at $ENV_FILE (copy config/magneto.env.example)"; exit 1; }
RPC_IP="$("$HERE/rpc-proxy.sh" ip)"

SECRET_DIR="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/magneto-k3s.XXXXXX")"; chmod 700 "$SECRET_DIR"
trap 'rm -rf "$SECRET_DIR"' EXIT
"$PYTHON" -I "$HERE/make_pod_env.py" "$ENV_FILE" "$RPC_IP" "$SECRET_DIR/env"

kubectl apply -f "$HERE/manifests/00-namespace.yaml"
kubectl -n magneto create secret generic magneto-env --from-env-file="$SECRET_DIR/env" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$HERE/manifests/30-network-policy.yaml"
kubectl apply -f "$HERE/manifests/20-deployment.yaml"
kubectl -n magneto rollout restart deploy/magneto-web >/dev/null
kubectl -n magneto rollout status deploy/magneto-web --timeout=120s
echo "Deployed. Prove it with deploy/k3s/verify.sh, then bring the bridge up with deploy/deploy.sh --mode k3s up"
