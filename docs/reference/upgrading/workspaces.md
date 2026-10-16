---
title: Workspace upgrades
description: Upgrade notes for the managed workspace root and adjacent checkouts.
---

# Workspace upgrades

This page records the compatibility and migration guidance for workspace storage.

## Adjacent Compatibility And Migration

The default `workspace.root` is `xdg-state` for unconfigured installations and projects.
Existing adjacent `<primary>_<num>/` directories are not moved during ordinary
resolution; SASE only creates new managed checkouts under the configured root. To carry
old adjacent checkouts into the managed root, run:

```bash
sase workspace migrate --to xdg-state [--symlink-transition] [--dry-run]
sase workspace migrate --finalize [--dry-run]
```

The first form moves every existing `<primary>_<num>` checkout under the managed root
and records it in the registry. With `--symlink-transition`, the original
`<primary>_<num>` path becomes a symlink to the canonical managed checkout so legacy
tooling that walks `..` for siblings keeps working. Migration refuses to overwrite a
real directory at the managed destination; pre-existing managed content is reported and
skipped. `--dry-run` reports the planned actions without touching the filesystem or
registry.

Once workflows have adapted to the managed paths, `sase workspace migrate --finalize`
removes the leftover transition symlinks without touching the canonical checkouts.

## Post-Default Migration Guidance

Users and environments that still rely on sibling checkouts should set
`workspace.root: adjacent` explicitly, either in the project-local `sase/sase.yml` or
globally in `~/.config/sase/sase.yml`. The managed-root default is intentionally
non-migrating: it prevents silent moves, but a project with old adjacent clones and no
explicit config will create new non-primary checkouts under the state root after the
default change.

Before switching shared CI images, containers, or network-mounted homes to the default,
confirm the state root is mounted, backed up, and on storage fast enough for agent work.
Use an absolute `workspace.root` when the platform state directory is not the right
operational location.

## Related

- [Upgrading](index.md) — the section hub.
