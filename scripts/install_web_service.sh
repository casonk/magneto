#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${repo_dir}/.venv"
env_file="${repo_dir}/config/magneto.env.local"
unit_dir="${HOME}/.config/systemd/user"
unit_file="${unit_dir}/magneto-web.service"

if [[ ! -d "${venv_dir}" ]]; then
  python3 -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install -e "${repo_dir}"

if [[ ! -f "${env_file}" ]]; then
  cp "${repo_dir}/config/magneto.env.example" "${env_file}"
  chmod 600 "${env_file}"
  echo "Created ${env_file}; edit it if your Transmission RPC settings differ."
fi

mkdir -p "${unit_dir}"
cat > "${unit_file}" <<UNIT
[Unit]
Description=Magneto private torrent web UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${repo_dir}
EnvironmentFile=-${env_file}
ExecStart=${venv_dir}/bin/magneto web
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now magneto-web.service
systemctl --user status magneto-web.service --no-pager
