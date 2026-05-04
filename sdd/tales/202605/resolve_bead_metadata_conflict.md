---
create_time: 2026-05-04 14:35:10
status: done
---
# Resolve Bead Metadata Merge Conflict

## Context

The primary workspace `/home/bryan/projects/github/sase-org/sase` is on `master` and has a single unmerged file:
`sdd/beads/issues.jsonl`. The conflict appears to be from applying stashed bead metadata onto an updated upstream
working tree:

- upstream contains `sase-20.7` closed with commit metadata, closes `sase-20`, and adds `sase-21` plus phases
  `sase-21.1` through `sase-21.5`;
- the stashed side contains older in-progress versions of `sase-20.7` and `sase-21.*`, but includes newer work-claim
  metadata for the `sase-21` plan and phases.

The main correctness constraint is to avoid dropping any bead metadata. This means resolving by JSON object identity and
field freshness, not by choosing one side of the conflict wholesale.

## Plan

1. Confirm the full conflict state before editing.
   - Re-read `git status`, `git diff --name-only --diff-filter=U`, and the three index stages for
     `sdd/beads/issues.jsonl`.
   - Identify every bead ID that differs between stages and compare complete JSON objects for those IDs.

2. Resolve `sdd/beads/issues.jsonl` with a metadata-preserving merge.
   - Keep all non-conflicting JSONL rows unchanged.
   - For `sase-20` and `sase-20.7`, keep the upstream closed state because it has later `updated_at` timestamps,
     `closed_at`, and commit note metadata that supersede the stashed in-progress state.
   - For `sase-21`, preserve the stashed side’s newer `updated_at` and `is_ready_to_work=true` fields unless a later
     upstream value exists.
   - For `sase-21.1`, keep the upstream closed state because it has later `updated_at` and `closed_at`.
   - For `sase-21.2` through `sase-21.5`, preserve the stashed side’s in-progress status, assignee claims, and newer
     `updated_at` fields, while retaining all dependencies and other stable fields.
   - Remove all conflict markers.

3. Validate bead metadata integrity.
   - Parse every line in `sdd/beads/issues.jsonl` as JSON.
   - Check that bead IDs are unique.
   - Compare stage 2 and stage 3 IDs against the resolved file to confirm no bead rows were lost.
   - Inspect the focused diff to ensure only the intended rows changed.

4. Complete the Git conflict resolution.
   - Stage `sdd/beads/issues.jsonl`.
   - If Git reports an active merge or rebase, continue it with the appropriate non-interactive command.
   - If this was only a stash-apply conflict, proceed with the normal resolved working tree.

5. Run required checks.
   - Run `just install` first if the workspace environment needs it.
   - Run `just check` as required by repo instructions after changes in this repo.
   - Run a focused bead command such as `sase bead list --status=in_progress` to verify bead metadata remains readable.

6. Commit through `/sase_git_commit`.
   - Re-read `git status` and `git diff`.
   - Determine whether an in-progress bead is associated with this conflict-resolution change.
   - Write a human-authored commit message file.
   - Run `sase commit -M <message-file> -f sdd/beads/issues.jsonl` with `--bead-id` only if an appropriate in-progress
     bead exists.
   - Verify `git status --short --branch` is clean and not ahead of upstream; push if the commit workflow leaves it
     ahead.
