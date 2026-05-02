---
create_time: 2026-03-26 17:23:51
status: done
prompt: sdd/prompts/202603/fix_non_primary_sdd_path_resolution.md
---

# Fix non-primary SDD writes for workspace-suffixed parent dirs

## Problem statement

When `sdd.version_controlled` is `false`, SDD files should always be written under the primary workspace at
`<primary>/.sase/sdd/`. A bug causes non-primary workspaces like `/google/src/cloud/bbugyi/pat_102/google3` to be
treated as primary, resulting in writes to `/google/src/cloud/bbugyi/pat_102/google3/.sase/sdd/...`.

## Root cause

`get_sdd_dir()` correctly delegates primary resolution to `get_primary_workspace_dir()` in non-VC mode. The fallback
branch in `get_primary_workspace_dir()` only strips `_{workspace_num}` if the full path string ends with that suffix:

- Works for `/home/user/project_2`
- Fails for `/google/.../pat_102/google3` because `_102` is in a parent path component, not at string end.

When project metadata resolution (`_resolve_primary_from_project`) is unavailable, this fallback returns the non-primary
workspace unchanged, so `get_sdd_dir()` points to the wrong location and creates `.sase/sdd` there.

## Fix approach

1. Update fallback logic in `get_primary_workspace_dir()`:

- Normalize by stripping trailing slash.
- For `workspace_num > 1`, locate the rightmost path component that ends with `_{workspace_num}`.
- Remove that suffix from that component.
- Reconstruct and return the path.
- If no component matches, return the original path.

2. Preserve precedence:

- Keep `_resolve_primary_from_project()` as first choice.
- Only apply enhanced suffix stripping when metadata resolution fails.

3. Add regression tests:

- `get_primary_workspace_dir("/google/src/cloud/bbugyi/pat_102/google3", 102)` returns
  `/google/src/cloud/bbugyi/pat/google3`.
- `get_sdd_dir(..., version_controlled=False)` for same workspace resolves to
  `/google/src/cloud/bbugyi/pat/google3/.sase/sdd`.

4. Validate:

- Run targeted tests in `tests/test_sdd.py`.
- Run lint/type checks if needed for touched files.

## Expected outcome

In non-VC mode, SDD plans/specs are always written to the primary workspace path, even when workspace numbering is
encoded in a parent directory component.
