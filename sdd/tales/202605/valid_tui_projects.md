---
create_time: 2026-05-07 15:52:37
status: done
prompt: sdd/prompts/202605/valid_tui_projects.md
---
# Plan: Show Only Valid Projects in TUI Project Pickers

## Problem

The ace TUI `@` project picker currently lists any directory shaped like `~/.sase/projects/<name>/<name>.gp`. That file
layout is too weak to mean "launchable project": empty project files, home-mode/project-artifact buckets, stale
fixtures, and non-workspace placeholders can all match it. Selecting those entries later fails when workflow detection
cannot identify a workspace provider.

The visible user-facing issue is in the `@` keymap modal, but `ProjectSelectModal` is also used by axe background
command launch and agent revive filtering, so the fix should live at the shared picker/data-source boundary.

## Product Behavior

- Keep the explicit `[H] ~ (home directory)` option.
- Keep ChangeSpec (`[C]`) entries for active statuses exactly as today.
- Only show `[P]` project entries that can actually be used as project-scoped agent targets.
- Do not show placeholder project files such as `home`, empty `.gp` files without workspace metadata, stale directories
  with missing workspaces, or project files no workspace provider can claim.
- Keep `include_all=True` behavior for consumers that need the `[*] ALL` option.

## Technical Approach

1. Introduce a small project-discovery helper in the Python/TUI side of the repo. The helper should enumerate
   `~/.sase/projects/<name>/<name>.gp`, parse the configured `WORKSPACE_DIR`, require the workspace path to exist, and
   require `workspace_provider.detect_workflow_type(project_file)` to succeed.

2. Reuse existing project-file/workspace-provider APIs rather than duplicating workflow logic:
   - `parse_workspace_dir()` for the project metadata check.
   - `detect_workflow_type()` for the definitive "launchable by a workspace plugin" check.
   - Skip `home`, because the modal already presents home as a separate `[H]` target.

3. Update `ProjectSelectModal._load_items()` to build `[P]` rows from this helper instead of the raw directory scan.
   This should fix all current TUI consumers of the modal, including `@`, axe bg commands, and revive project filtering.

4. Add focused tests for the helper and the modal data loading:
   - valid project with existing `WORKSPACE_DIR` and detected workflow is shown;
   - empty/stale/no-workspace/no-provider projects are hidden;
   - `home` is not duplicated as `[P] home`;
   - active ChangeSpecs are still included.

5. Verify with targeted pytest first, then run the repo-required check sequence: `just install` followed by
   `just check`.

## Boundary Decision

This is TUI presentation/launch-selection behavior, but validity depends on existing workspace-provider detection. I
will keep the new code as a thin Python/TUI adapter for now and avoid changing Rust core unless implementation reveals
another frontend already needs the exact same launchable-project list.
