# AGENTS.md - magneto

## Purpose

`magneto` provides a small private web UI for adding magnet links or torrent
files to Transmission and forcing downloads into the configured Snowbridge
share directory.

The app is intended to bind to localhost and be exposed to trusted devices
through `wiring-harness` Caddy/mTLS.

## Setup and Commands

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest -q
```

Run the web UI locally:

```bash
MAGNETO_DOWNLOAD_DIR=/srv/snowbridge/share/torrents magneto web
```

Install the user service:

```bash
./scripts/install_web_service.sh
```

## Operating Rules

1. Keep Transmission credentials and host-local paths in `config/magneto.env.local`.
2. Do not allow users to choose arbitrary download directories from the web UI.
3. Keep the app bound to `127.0.0.1` unless it is explicitly being tested with
   `MAGNETO_ALLOW_REMOTE=1`.
4. `wiring-harness/services.local.toml` owns the private hostname and Caddy
   proxy entry.
5. Use `scripts/install_transmission_vpn_guard.sh` to constrain Transmission
   egress to the VPN provider interface instead of relying on web UI behavior
   for network safety.

## Sudo Boundary

Agents will never be able to run `sudo` commands in this environment. If a task requires elevated system changes, make the repo edits and run the validation that can be done without `sudo`, then give the user the exact command(s) to run.

Always require the user to run those commands instead of retrying `sudo`; do not claim a sudo-backed live change was applied until the user shares the result.

## Local CI Verification

CI (`.github/workflows/ci.yml`) runs the shared `python-ci` workflow across
Python 3.10–3.12. Reproduce before pushing:

```bash
pip install -e .[dev]
pre-commit run --all-files
pytest -q
```

`pre-commit` auto-fixing hooks rewrite files and exit 1 on the run that made the
change; re-run, confirm exit 0, then stage what they rewrote. Keep the hook
versions in `.pre-commit-config.yaml` matched to what CI pins.

## Agent Memory

- `CHATHISTORY.md` — local-only session memory. Gitignored, never published.
- `LESSONSLEARNED.md` — tracked durable lessons for this repo.
- `REFS-LOCAL.md` — gitignored machine-specific reference notes.
- `REFS-PUBLIC.md` — tracked public references.

Read `LESSONSLEARNED.md` and, if present, `CHATHISTORY.md` after this file when
resuming. Before final reporting for meaningful work, either add any durable
lesson discovered or state why none was added. If the lesson generalizes beyond
this repo, add it to `traction-control/LESSONSLEARNED.md` instead.

Two tracked `pyreverse` scratch diagrams, `classes_magneto.puml` and
`packages_magneto.puml`, still live at the repo root; they should be normalized
into `docs/diagrams/python-{classes,packages}.puml` via `archility render` or
removed. See `BACKLOG.md`.

## Portfolio Standards Reference

Portfolio-wide standards, the repository-visibility authority, and the tiered
agent bootstrap live in the control plane at `../traction-control`. Read its
`AGENTS.md` before cross-repo work. `magneto` depends on `snowbridge` (the share
directory) and `wiring-harness` (the private hostname and Caddy/mTLS entry);
those are public shared utilities named freely, while private utilities are
resolved through the ignored local registry and not named in tracked files.
