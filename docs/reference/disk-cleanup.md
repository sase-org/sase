---
title: SASE disk cleanup
description: Inspect SASE-created bytes and delegate cleanup to the owning subsystem.
---

# SASE disk cleanup

This page describes disk inventory and cleanup ownership for SASE-managed storage.

## `sase disk`

Disk commands inspect SASE-created bytes by owner and delegate cleanup back to those
owners. With no subcommand, `sase disk` defaults to `sase disk list`.

<a id="cli-options-27"></a> Moved to [sase disk](disk-cleanup.md#sase-disk).

<a id="command-behavior-16"></a> Moved to
[SASE disk cleanup](disk-cleanup.md#command-behavior-16).

## Command behavior {#command-behavior-16}

Unowned Cargo-shaped strays are listed for human action and are never deleted by
`sase disk reap`.

The `sase disk list` table shows each row's owner, section, size, coverage, horizon, and
path. Managed-temp rows cover every registered root writers actually used, not only the
effective one. Workspace checkouts get one row per project plus sub-rows for
`.git/objects`, `.pytest_cache` (including `sase-visual`), `sase/repos`, `.venv`, and
in-tree `target/`, sized before the generic stray walk so budget exhaustion can only
clip that walk. Unowned rows are highlighted; a row whose coverage is `partial` or
`unresolved` means the owner could not account for every byte. When coverage is partial
or the filesystem is under pressure, an `unattributed` row reports filesystem used minus
attributed bytes on the filesystem holding `SASE_HOME`. When rows share physical storage
(for example workspaces that borrow primary Git objects), the size cell also shows the
exclusively counted bytes, and the footer reports the physical total, the logical row
total when it differs, the overall coverage status, and any partial-scan diagnostics.

The SASE-home inventory includes `cache/project_stats`, owned by `project_stats_cache`,
under `~/.sase/cache/project_stats/` or `$SASE_HOME/cache/project_stats/`. This
statistics cache is rebuildable from source repositories. Its row reports its size and
rebuildable status without offering a reclaim command; it is not one of the
`sase disk reap` cleanup passes.

`sase disk reap` runs, or previews, the owner passes in order: managed-temp reaping,
proc runtime cleanup, ACE-run artifact retention (the same owner as
`sase artifact prune-runs`), and workspace Git object compaction. It exits `1` when any
owner step is blocked, fails, or cannot report a trustworthy result, and `0` otherwise.
Because ACE-run deletion is currently preview-only, the artifact-run step reports
`blocked` under `--apply`.

## Related

- [Disk CLI reference](cli/disk.md) — inventory and cleanup options.
- [Workspace maintenance](agents/workspaces.md#workspace-maintenance) — workspace
  cleanup, recovery, and retention.
