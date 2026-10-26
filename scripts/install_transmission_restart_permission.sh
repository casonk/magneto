#!/usr/bin/env bash
# Grant the Magneto user one fixed systemd action for the web restart button.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "error: run this as the user that runs magneto-web.service" >&2
  exit 1
fi

operator_user="$(id -un)"
if [[ ! "${operator_user}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "error: unsupported sudoers username" >&2
  exit 1
fi

tmp_rule="$(mktemp)"
trap 'rm -f "${tmp_rule}"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block restart transmission-daemon.service\n' \
  "${operator_user}" > "${tmp_rule}"

sudo visudo -cf "${tmp_rule}"
sudo install -o root -g root -m 0440 "${tmp_rule}" /etc/sudoers.d/magneto-transmission-restart
sudo visudo -c
echo "ok: ${operator_user} may request only a nonblocking transmission-daemon.service restart"
