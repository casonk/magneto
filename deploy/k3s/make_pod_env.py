"""Turn the host's magneto settings into the environment file for the pod's Secret.

The pod cannot reach the vault, so Transmission's credentials are resolved here, on the host, with magneto's own
loader (``AppConfig.from_env``). Only an allow-list of settings is copied; vault entry names, notification and
library settings and the host's loopback URL never reach the cluster.

    make_pod_env.py ENV_FILE RPC_IP OUT_FILE

writes OUT_FILE (mode 0600) and prints only what it wrote, never a value.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COPIED = (
    "MAGNETO_SECRET_KEY",
    "MAGNETO_PUBLIC_ORIGIN",
    "MAGNETO_ALLOWED_ORIGINS",
    "MAGNETO_DOWNLOAD_DIR",
    "MAGNETO_NO_SEED_BY_DEFAULT",
    "MAGNETO_DEFAULT_DOWNLOAD_LIMIT_KBPS",
    "MAGNETO_DEFAULT_UPLOAD_LIMIT_KBPS",
    "MAGNETO_DEFAULT_SEED_RATIO",
    "MAGNETO_REQUEST_TIMEOUT",
    "MAGNETO_MAX_TORRENT_UPLOAD_BYTES",
)
_PLAIN = re.compile(r"^[^\s\"'\\]*$")


def parse(text: str) -> dict[str, str]:
    """KEY=value lines as systemd reads them: the last assignment wins and surrounding quotes are dropped."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if match:
            value = match.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            found[match.group(1)] = value
    return found


def build(
    settings: dict[str, str], rpc_ip: str, username: str | None, password: str | None
) -> dict[str, str]:
    env = {key: settings[key] for key in COPIED if settings.get(key)}
    env["MAGNETO_TRANSMISSION_URL"] = f"http://{rpc_ip}:9091/transmission/rpc"
    if username:
        env["MAGNETO_TRANSMISSION_USERNAME"] = username
    if password is not None:
        env["MAGNETO_TRANSMISSION_PASSWORD"] = password
    return env


def main(argv: list[str]) -> int:
    env_file, rpc_ip, out_file = argv
    try:
        settings = parse(Path(env_file).read_text(encoding="utf-8"))
    except OSError:
        print("cannot read the settings file", file=sys.stderr)
        return 1
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", rpc_ip):
        print("the RPC address must be an IPv4 address", file=sys.stderr)
        return 1
    # Resolve the vault entry exactly as the host service does, in a scrubbed environment.
    sys.path.insert(0, str(REPO / "src"))
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update({k: v for k, v in settings.items() if k.startswith("MAGNETO_")})
    try:
        from magneto.config import AppConfig, ConfigurationError

        try:
            config = AppConfig.from_env()
        except ConfigurationError as exc:
            print(f"cannot resolve the Transmission credentials: {exc}", file=sys.stderr)
            return 1
    finally:
        os.environ.clear()
        os.environ.update(saved)
    env = build(settings, rpc_ip, config.username, config.password)
    bad = [k for k, v in env.items() if not _PLAIN.match(v) or "\n" in v]
    if bad:
        # kubectl's --from-env-file keeps quotes literally; refuse a value it would mangle rather than ship it.
        print(
            f"these settings contain whitespace or quotes the Secret file cannot carry: {', '.join(sorted(bad))}",
            file=sys.stderr,
        )
        return 1
    fd = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for key in sorted(env):
            stream.write(f"{key}={env[key]}\n")
    print(f"wrote {len(env)} settings: {', '.join(sorted(env))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
