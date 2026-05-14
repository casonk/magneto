# Contributing

## Expectations

- Keep `magneto` bound to localhost by default; any wider network exposure is
  the reverse proxy's responsibility (`wiring-harness`).
- Do not allow users to choose arbitrary download directories from the web UI.
- Keep Transmission credentials and host-specific paths out of tracked files.
- Update tests and the architecture docs when the Flask routes or RPC client
  behavior changes.

## Local Validation

```bash
pip install -e .[dev]
ruff check .
ruff format --check .
black --check --diff .
pytest -q
```

## Repo Baseline

This repository follows the portfolio standards in `./util-repos/traction-control`
from the portfolio root.
