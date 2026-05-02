---
create_time: 2026-05-01 12:26:37
status: done
prompt: sdd/prompts/202605/workspace_bead_id_allocation.md
---
# Workspace-Aware Bead ID Allocation

## Problem

Top-level bead IDs are currently allocated from the local workspace's `sdd/beads/config.json` `next_counter`. That is
not enough for version-controlled SASE workspaces because each agent may be running in a separate sibling clone such as
`sase`, `sase_101`, or `sase_102`. If two agents create a new epic from different workspace directories, both can read
the same local counter and emit the same top-level ID, for example `sase-1q`.

Read commands already have a workspace-aware path through `get_project_beads_dirs()` and `MergedBeadView`, but writes
still use only the active workspace's `BeadProject` counter.

## Goals

- Before allocating a new top-level bead ID, inspect all known bead stores for the current project workspace set.
- Choose the next available base36 suffix for the configured prefix, even if the local workspace counter is stale.
- Keep local, single-workspace behavior unchanged when workspace discovery is unavailable.
- Preserve the current ID format: `<prefix>-<base36>` for top-level beads and `<parent_id>.<N>` for phase children.
- Add focused regression tests that reproduce two workspace directories with divergent counters.

## Non-Goals

- Do not redesign bead storage or merge writes into one global database.
- Do not change list/show/ready semantics; they already use the merged read view where appropriate.
- Do not alter the user-facing `sase bead create` interface.

## Proposed Design

1. Add a workspace-aware ID scan helper.
   - Place this close to ID logic, likely in `src/sase/bead/ids.py`, with a small reader that can inspect `issues.jsonl`
     files without requiring every sibling workspace to open a writable SQLite database.
   - Given an `issue_prefix` and a list of bead directories, parse existing top-level IDs that match
     `^<prefix>-([0-9a-z]+)$`.
   - Convert matching suffixes with `from_base36()` and return the maximum allocated counter value.
   - Ignore malformed JSONL lines and malformed IDs, matching the existing tolerant import/merged-view behavior.

2. Wire top-level creation through the scan.
   - In `BeadProject.create()`, when `parent_id is None`, compute the starting counter as:
     `max(local_config_next_counter, max_workspace_id_counter + 1)`.
   - Use that value for allocation, then persist the resulting `next_counter` back to the current workspace's config.
   - Keep the existing in-process lock around `IdGenerator.next_id()` so one Python process remains serialized.

3. Discover workspace bead directories from the write path.
   - Reuse `sase.bead.workspace.get_project_beads_dirs()` when available.
   - Include the current `self.beads_dir` even if discovery fails or omits it, so fallback behavior remains correct.
   - Avoid changing non-version-controlled SDD mode behavior: discovery returns primary-only there, so allocation
     remains centralized on the primary bead store.

4. Consider child IDs separately but keep scope tight.
   - The user-reported collision is for new epic beads, which are top-level plan beads.
   - Phase IDs are scoped under an existing parent and are normally created by the same epic-creation agent, but the
     same pattern can be applied to `_next_child_id()` if tests show an equivalent risk. If included, scan sibling JSONL
     files for direct children of the parent before choosing `<parent_id>.<N>`.

5. Test coverage.
   - Unit-test the ID scan helper with valid IDs, wrong prefixes, child IDs, corrupt JSONL lines, and higher local
     config.
   - Add a project-level regression test with two sibling workspaces:
     - workspace A has `sase-1`;
     - workspace B has stale `next_counter: 1`;
     - creating from workspace B produces `sase-2`, not `sase-1`.
   - Add a case where local config is ahead of all workspace JSONL files and remains authoritative.
   - If child scanning is implemented, add a sibling-workspace child collision test for `<parent_id>.<N>`.

## Verification

- Run focused tests:
  - `pytest tests/test_bead/test_ids.py tests/test_bead/test_project.py tests/test_bead/test_workspace_resolution.py`
- Because this repo's memory requires it after edits, run:
  - `just install`
  - `just check`

## Risks and Mitigations

- This scan reduces stale-counter collisions across sibling workspaces, but two independent processes can still race if
  they scan at exactly the same time before either writes. A robust follow-up would add a shared advisory lock under
  `~/.sase/` or the primary workspace before scan-and-create. If the current task should fully eliminate concurrent
  same-machine races, include that lock in this change around top-level ID allocation.
- If a sibling workspace has unexported SQLite-only bead data, JSONL scanning will not see it. Existing create/update
  paths export immediately, so this should be limited to interrupted or manually modified states.
