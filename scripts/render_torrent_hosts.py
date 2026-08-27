#!/usr/bin/env python3
"""Render the approved Magneto host selector from the private site registry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

HOST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _valid_url(value: object, *, description: str) -> str:
    url = str(value).strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{description} must be an absolute HTTPS URL without credentials, query, or fragment"
        )
    return url.rstrip("/") + "/"


def _host_url(service: dict, *, wireguard_ip: str) -> str:
    explicit = service.get("torrent_home_url")
    if explicit:
        return _valid_url(
            explicit, description=f"{service.get('name', 'service')}.torrent_home_url"
        )
    edge_port = service.get("macos_edge_listen_port")
    if service.get("macos_edge_role") == "magneto" and isinstance(edge_port, int) and wireguard_ip:
        return _valid_url(
            f"https://{wireguard_ip}:{edge_port}/", description="Air Magneto endpoint"
        )
    hostname = str(service.get("hostname", "")).strip()
    if not hostname:
        raise ValueError(
            f"{service.get('name', 'service')}: torrent host needs torrent_home_url or hostname"
        )
    return _valid_url(
        f"https://{hostname}/", description=f"{service.get('name', 'service')}.hostname"
    )


def render_hosts(
    *, services_path: Path, current_id: str, current_url: str
) -> list[dict[str, object]]:
    if not HOST_ID_RE.fullmatch(current_id):
        raise ValueError(
            "current host id may contain only letters, numbers, dot, underscore, and hyphen"
        )
    import tomllib

    data = tomllib.loads(services_path.read_text(encoding="utf-8"))
    local_path = services_path.with_name(services_path.stem + ".local.toml")
    if local_path.exists():
        local = tomllib.loads(local_path.read_text(encoding="utf-8"))
        base_by_name = {str(item.get("name", "")): item for item in data.get("services", [])}
        for item in local.get("services", []):
            name = str(item.get("name", ""))
            if name in base_by_name:
                base_by_name[name].update(item)
            else:
                data.setdefault("services", []).append(item)

    hosts: list[dict[str, object]] = []
    seen: set[str] = set()
    wireguard_ip = str(data.get("wg_ip", "")).strip()
    for service in data.get("services", []):
        host_id = service.get("torrent_host")
        if not isinstance(host_id, str):
            continue
        host_id = host_id.strip()
        if not HOST_ID_RE.fullmatch(host_id):
            raise ValueError(f"{service.get('name', 'service')}: invalid torrent_host {host_id!r}")
        if host_id in seen:
            raise ValueError(f"duplicate torrent_host {host_id!r}")
        seen.add(host_id)
        label = str(service.get("torrent_label", host_id)).strip()
        if not label or len(label) > 80 or any(ord(char) < 0x20 for char in label):
            raise ValueError(f"{service.get('name', 'service')}: invalid torrent_label")
        hosts.append(
            {
                "id": host_id,
                "label": label,
                "url": (
                    _valid_url(current_url, description="current host URL")
                    if host_id == current_id
                    else _host_url(service, wireguard_ip=wireguard_ip)
                ),
                "current": host_id == current_id,
            }
        )

    if current_id not in seen:
        raise ValueError(f"no torrent host {current_id!r} found in the service registry")
    return sorted(hosts, key=lambda item: (not bool(item["current"]), str(item["label"]).lower()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--services", type=Path, required=True)
    parser.add_argument("--current-id", required=True)
    parser.add_argument("--current-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hosts = render_hosts(
        services_path=args.services.resolve(),
        current_id=args.current_id,
        current_url=args.current_url,
    )
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"hosts": hosts}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    # This contains only labels and navigation URLs; Magneto runs as an
    # unprivileged service and therefore needs to be able to read it.
    args.output.chmod(0o644)
    print(f"Rendered {args.output} ({len(hosts)} torrent host{'s' if len(hosts) != 1 else ''})")


if __name__ == "__main__":
    main()
