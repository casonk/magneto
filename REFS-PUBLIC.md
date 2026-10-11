# REFS-PUBLIC.md — Public References

> Record external public repositories, datasets, documentation, APIs, or other
> public resources that this repository utilizes or depends on.
> This file is tracked and intentionally kept free of private or local-only details.

## Public Repositories

- https://github.com/transmission/transmission — Transmission daemon controlled through its local RPC interface

## Public Datasets and APIs

- No public data feed is consumed; Magneto sends authenticated JSON-RPC requests to a local Transmission daemon.

## Documentation and Specifications

- https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md — Transmission RPC protocol used by `TransmissionClient`
- https://flask.palletsprojects.com/ — Flask web UI framework reference
- https://requests.readthedocs.io/ — Requests HTTP client reference used by the Transmission RPC client
- https://wiki.nftables.org/ — nftables reference for the Transmission VPN egress guard

## Notes

- Transmission credentials, RPC addresses, download paths, and private ingress details remain local-only.
