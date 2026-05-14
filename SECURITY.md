# Security Policy

## Reporting

Do not file sensitive disclosures in public issues.

Report security issues privately to the repository owner or maintainer instead
of publishing exploit details in a public issue or pull request.

## Scope

This repository must not become a place to store live secrets, credentials,
tokens, private keys, personal data, or other private environment details.

- Treat `CHATHISTORY.md` as local-only operational memory and do not publish it.
- Do not commit machine-specific absolute filesystem paths, hostnames, internal
  endpoint addresses, or local-only config files unless the exact value is
  strictly required and already safe to disclose.
- Treat tracked example files, fixtures, screenshots, copied logs, and issue or
  pull-request snippets as public documentation. Use synthetic placeholders and
  redacted examples instead of real usernames, hostnames, account identifiers,
  secrets, or private operational data.

## Runtime Trust Boundary

- `magneto` binds to `127.0.0.1` by default. The wider network is exposed only
  through the `wiring-harness` Caddy/mTLS proxy on a trusted LAN/VPN.
- Do not expose the web UI directly on `0.0.0.0` unless the deployment is
  explicitly behind a trusted reverse proxy with authentication.
- Transmission credentials and download-directory paths are local-only config
  and must stay in `config/magneto.env.local` (gitignored), not in tracked files.
- Users cannot override the download destination from the web UI; that path is
  fixed to the configured Snowbridge directory.

## Safe Documentation Practices

- Use generic paths, placeholder usernames, and redacted examples in tracked
  docs unless a concrete value is required for the workflow.
- Keep durable security guidance in tracked files such as `SECURITY.md`,
  `AGENTS.md`, and `LESSONSLEARNED.md`.
- Keep transient local operational details in gitignored files such as
  `CHATHISTORY.md`, `REFS-LOCAL.md`, and `config/magneto.env.local`.
