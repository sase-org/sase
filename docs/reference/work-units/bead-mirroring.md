---
title: Bead mirroring
description: How SASE beads can mirror issues from an external tracker.
---

# Bead mirroring

This page describes how SASE mirrors bead issues to and from external trackers.

## External Issue Mirroring

The `external_issue_mirror` AXE job (see
[external_mirror lane](../automation/scheduler-default-routines.md#external_mirror-15-minute-interval))
keeps every enabled project's issue tracker mirrored into task beads: each pass diffs
the tracker against local beads on `external_ref` and creates an explicitly `small`,
`open` task bead — never `ready` — for every uncovered issue, so a first-pass backlog
never floods the `TaskTriage` gate queue. Run
`sase bead sync-external [--project P] [--dry-run] [--full]` to trigger or preview the
same pass manually.

Flag-typed task beads are deliberately excluded from external mirroring. Feature-flag
removal is internal SASE hygiene owned by the registry, the `flag` task bead, and the
`FlagTriage` gate; it should not become GitHub issue noise.

A mirrored bead carries `external_ref` (the mirror's idempotency key, project-key
qualified) and a matching `bug:<display-name>#<n>` entry in `refs` (the human-facing,
searchable spelling); both normalize to the same identity. A bead that only carries the
`bug:` ref is a reference, not a mirror, and its status stays human-owned. When the
upstream issue behind `external_ref` closes or reopens, the mirror closes or reopens the
mirrored bead and appends one attributed note. It appends the note without changing
status when the bead is reference-only, claimed or in progress, has unclosed
descendants, or already matches the upstream state. Disappearances are also note-only
because there is no safe status target. After this reconciliation, the Beads pane's
drift badge means the link is still unreconciled: guard-skipped, reference-only, or
title drift. The
[`external_mirror.issues.filters`](../config/automation-behavior.md#externalmirror)
surface (empty by default) excludes tracker issues from mirroring by author, label,
title, or state; filters gate creation only, so clearing one re-examines the issues it
dropped without deleting a bead that already exists.

## Related

- [Beads](beads.md)
