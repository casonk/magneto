# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

- [ ] [manual:2026-10-15] **Ask GitHub Support to purge pre-rewrite commits** — this
  repository's published history was rewritten (most recently on 2026-10-15,
  to remove per-commit AI attribution trailers). GitHub keeps serving the old
  commits to anyone with a hash, and through the read-only `refs/pull/*` refs
  of earlier pull requests, until Support garbage-collects them. The request
  is filed once for the whole portfolio from traction-control's backlog; mark
  this done when an old hash returns 404 here. Never push an old clone's
  history back.

## In Progress

## Done

- [x] [manual:2026-10-26] **Add per-torrent download rate presets.** Magneto
  can set or clear Transmission's per-torrent download limit from the torrent
  card.
- [x] [manual:2026-10-26] **Link torrent notifications to the detail card.**
  Completion and error messages include a deep link built from the configured
  `MAGNETO_PUBLIC_ORIGIN`.

- [x] [manual:2026-08-29] **Close four `AGENTS.md` shared-convention gaps.**
  The shared checker now passes; `AGENTS.md` names the control-plane reference,
  local handoff, durable lessons, and reproducible local verification.

- [x] [manual:2026-08-29] **Stop tracking the `pyreverse` scratch diagrams.**
  Removed the redundant root outputs, retained the normalized sources under
  `docs/diagrams/`, and ignored the transient root filenames.
