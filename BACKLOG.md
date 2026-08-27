# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

- [ ] [manual:2026-08-24] **Close four `AGENTS.md` shared-convention gaps.**
  Flagged by `scripts/check_agents_md.py` in traction-control; the existing
  `## Sudo Boundary` section already passes.
  (a) add a `## Portfolio Standards Reference` heading pointing back at
  `./util-repos/traction-control`;
  (b) name `CHATHISTORY.md` as the local-only, gitignored session memory (the
  `.gitignore` entry is already correct — `AGENTS.md` just does not say so);
  (c) name `LESSONSLEARNED.md` as the durable lesson file;
  (d) add a `## Local CI Verification` section — the repo ships CI workflows
  but nothing documents how to reproduce them locally.
  Seed from `../traction-control/docs/templates/AGENTS.md`. Verify with
  `python3 ../traction-control/scripts/check_agents_md.py --repo .`

- [ ] [manual:2026-08-24] **Stop tracking the `pyreverse` scratch diagrams.**
  `classes_magneto.puml` and `packages_magneto.puml` are committed at the repo
  root. Those are exactly the transient per-repo filenames the shared render
  path is supposed to normalize into `docs/diagrams/python-{classes,packages}.puml`;
  tracking them at root means a partial failed run can have its leftovers
  re-rendered as if they were primary checked-in diagrams. Either regenerate
  them through `archility render` into the normalized paths, or delete them and
  add the transient names to `.gitignore`.

## In Progress

## Done
