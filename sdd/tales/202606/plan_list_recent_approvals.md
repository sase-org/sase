---
create_time: 2026-06-17 07:07:50
status: done
prompt: sdd/prompts/202606/plan_list_recent_approvals.md
---
# Fix `sase plan list` Recent Approvals

## Problem

`sase plan list` reports the last 10 approved plans as 3d old even though plans were approved yesterday and this
morning. The current output also shows several June 16 archived plans in the inferred rejected section, even though
matching `agent_meta.json` files under `~/.sase/projects/.../artifacts/...` show those plans were approved.

## Root Cause

`src/sase/main/plan_inventory.py` builds the approved section from `_agent_meta_paths_newest_first()`. That helper still
walks only the legacy flat artifact layout:

```text
~/.sase/projects/<project>/artifacts/<workflow>/<YYYYmmddHHMMSS>/agent_meta.json
```

Recent SASE artifacts are now stored in the day-sharded layout:

```text
~/.sase/projects/<project>/artifacts/<workflow>/<YYYYMM>/<DD>/<YYYYmmddHHMMSS>/agent_meta.json
```

Because the approved-plan scan ignores the sharded paths, recent approved metadata is invisible. The archived plan files
are still discovered via `iter_sharded_files("plans")`, so those plan paths are not represented in the proposed or
approved sets and are incorrectly rendered as inferred rejected plans.

## Proposed Fix

1. Replace the ad hoc flat-only artifact walk in `_agent_meta_paths_newest_first()` with the existing artifact-layout
   abstraction from `sase.core.agent_artifact_paths`.
   - Iterate projects and workflow directories under `sase_projects_dir()`.
   - Use `iter_agent_artifact_dirs(project, workflow, newest_first=True)` so both legacy flat and day-sharded artifact
     directories are considered.
   - Keep a global newest-first sort by artifact timestamp, preserving deterministic tie-breaking by path.

2. Keep the inventory behavior otherwise unchanged.
   - Continue reading `agent_meta.json` only.
   - Continue deduping approved rows by canonical plan path.
   - Continue applying the fixed approved/rejected display limits.
   - Continue using `_approval_timestamp()` for display ordering of rows that are collected.

3. Add regression coverage in `tests/test_plan_inventory.py`.
   - Create an approved plan whose `agent_meta.json` lives under `canonical_agent_artifact_path(...)` so the physical
     path is day-sharded.
   - Assert it appears in the approved list.
   - Assert its archived plan path is not also shown as inferred rejected.
   - Keep an existing legacy-layout case passing so older artifacts remain supported.

4. Verify with focused and required checks.
   - Run the focused plan inventory tests.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check`.
   - Re-run `sase plan list --json` locally and confirm recent sharded approvals appear in the approved section rather
     than the rejected section.

## Expected Outcome

`sase plan list` should show the most recent approved plans from the current day-sharded artifact layout, and recently
approved archived plans should no longer be mislabeled as inferred rejected.
