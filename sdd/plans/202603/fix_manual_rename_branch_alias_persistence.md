---
create_time: 2026-03-29 19:31:09
status: done
---

# Fix Manual ChangeSpec Rename Branch-Alias Persistence

## Context

Manual ChangeSpec rename via the `n` keymap (`RenameMixin.action_rename_cl`) currently:

- checks out the existing ChangeSpec revision,
- attempts a provider branch rename,
- updates ChangeSpec references in the project `.gp` file.

For immutable-branch providers (for example GitHub flows where the branch cannot be renamed without disrupting/opening
PR workflows), the rename operation needs to persist a branch alias in `~/.sase/projects/<project>/branch_map.json` so
the new ChangeSpec name resolves to the original branch.

## Verified Gap

`src/sase/ace/tui/actions/rename.py` currently does not perform immutable-branch alias handling during manual rename:

- no `provider.can_rename_branch(...)` gate,
- no alias write/re-key on immutable providers,
- no stale alias cleanup on successful mutable rename.

This diverges from `src/sase/status_state_machine/suffix.py`, which already handles immutable branch providers correctly
through `branch_map` alias persistence.

## Goals

1. Ensure manual `n` renames are safe for immutable providers by persisting branch aliases.
2. Preserve current behavior for mutable providers.
3. Keep `.gp` updates (`NAME`, `PARENT`, `RUNNING`) and workspace claim/release semantics intact.
4. Add focused regression tests that cover immutable/mutable rename branches.

## Plan

1. Update manual rename branch handling in `RenameMixin._execute_rename`.

- After revision resolution and checkout, branch by provider capability.
- Immutable provider path (`can_rename_branch == False`):
  - read existing branch map,
  - if old ChangeSpec name has alias, re-key to new name,
  - otherwise write new alias to resolved branch (`resolved.removeprefix("origin/")`),
  - skip provider branch rename call.
- Mutable provider path (`can_rename_branch == True`):
  - keep provider rename behavior,
  - remove stale alias for the new name on successful rename.

2. Preserve existing error/reporting behavior.

- Keep failure messages and return semantics consistent for rename failures.
- Only proceed to `.gp` file updates when branch step succeeds.

3. Add regression tests for manual rename alias persistence.

- New tests should verify:
  - immutable provider writes alias when none exists,
  - immutable provider re-keys alias from old name to new name when one exists,
  - mutable provider performs rename and removes stale alias,
  - immutable path does not call provider rename.
- Keep tests narrow by patching dependencies around `_execute_rename` and asserting alias calls.

4. Validate in repo workflow.

- Run targeted pytest for the new test module.
- Run `just install` (workspace requirement) and `just check` before finishing.

## Risks / Notes

- Avoid changing behavior of reverted ChangeSpec rename path, which intentionally skips VCS operations.
- Keep imports local where needed to match existing module style and avoid import cycles.
- Ensure project basename derivation remains aligned with branch_map file location conventions.
