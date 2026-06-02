---
create_time: 2026-06-02 18:25:22
status: done
prompt: sdd/prompts/202606/project_management_inactive_vcs_launch.md
---
# Plan: Project Management Inactive Visibility and VCS Launch Reactivation

## Context

The Project Management modal already loads all non-home, non-system-managed project lifecycle records through
`list_project_records(..., "all", include_home=False)`, then applies a local state filter. Its default filter is
`active`, so inactive projects are hidden unless the user cycles to `inactive` or `all` with Tab. Rows already have a
state column, but inactive rows are not visible in the default working view.

Inactive project launch behavior is currently defensive: launch helpers and prompt resolution check lifecycle state and
raise or notify with a message telling users to run `sase project activate <project>`. The new behavior should instead
reactivate a project automatically when the user actually launches work through a VCS project ref such as `#gh:sase`,
`#git:sase`, or `#gh:sase-org/sase`.

## Goals

1. Add a `Ctrl+X` keybinding to the Project Management modal that reveals inactive projects in the panel without
   requiring Tab navigation.
2. Make inactive rows visually obvious when revealed, with an explicit inactive indicator adjacent to the project row,
   not only implied by launchability.
3. When a launch prompt references a known inactive project as a VCS workflow argument, activate that project before
   launch resolution continues.
4. Cover TUI launch, CLI/query launch, mobile/spawn launch, and multi-prompt/fan-out launch surfaces that share the VCS
   prompt resolution helpers.
5. Keep lifecycle mutation centralized around the existing locked `set_project_state_locked(..., "active")` path.

## UX Plan

- Add a modal-local `Ctrl+X` binding, labeled `Show Inactive` or `Inactive`, to `ProjectManagementModal.BINDINGS`.
- Track a boolean visibility override such as `_show_inactive_projects`, defaulting to `False`.
- When `Ctrl+X` is pressed:
  - Toggle `_show_inactive_projects`.
  - Clear pending force state because the visible target set has changed.
  - Reapply filters and refresh the list, summary, detail pane, and footer.
  - Show a concise status such as `Inactive projects visible` or `Inactive projects hidden`.
- Filtering behavior:
  - The existing state tabs remain available.
  - In the default `active` view, enabling the override shows both active and inactive projects.
  - Existing `inactive` and `all` filters continue to work as they do today.
  - Text filtering still applies after the state/visibility decision.
- Rendering:
  - Add an inactive indicator in `record_label()` near the project name or mark column, for example an amber `!` or
    `inactive` badge, so rows are obviously inactive even when shown beside active rows.
  - Keep the existing state column and detail text as supporting context.
  - Update footer and summary text to show the `Ctrl+X` affordance and whether inactive rows are currently visible.

## Launch Reactivation Plan

- Add a focused helper for launch-time lifecycle activation, likely near `xprompt.loader_sources` or a small new module
  under `sase.xprompt` / `sase.agent`, with a public shape similar to:
  - resolve a ref against lifecycle records from `list_project_records(..., "all")`;
  - accept both exact project names and owner/repo refs by reusing `resolve_known_project_ref`;
  - if the resolved record is inactive, call `set_project_state_locked(project, "active")`;
  - return the active project name and any updated record metadata needed by callers;
  - raise a clear launch error if activation fails.
- Do not change catalog/browse behavior to activate projects. Activation should happen only on launch paths, not when
  merely rendering xprompt catalogs, project-local prompts, or mobile menus.
- Replace launch-path uses of `inactive_project_message_for_ref()` that currently block inactive refs:
  - `sase.agent.launch_cwd.resolve_known_project_vcs_launch_ref()`;
  - `sase.main.query_handler._query._resolve_vcs_cwd()`;
  - TUI launch fallback in `AgentLaunchBodyMixin._run_agent_launch_body()`;
  - standalone/project-local workflow execution checks in `WorkflowExecMixin._try_execute_workflow()`.
- Ensure activation happens before active-only workspace discovery:
  - For known-project fallback, detect the inactive project using all lifecycle records, activate it, then call
    `get_known_project_workspaces()` again so the project appears in the active workspace map.
  - Clear `detect_project` caches where CWD changes already require it.
- For multi-prompt and fan-out:
  - Scan all prompt segments for known-project VCS refs before dispatch, not only the first ref used for launch context.
  - Activate every referenced inactive known project once per submitted prompt.
  - Preserve current first-ref behavior for choosing launch context unless the code already supports per-segment
    context.

## Edge Cases

- Owner/repo refs such as `#gh:sase-org/sase` should activate the registered `sase` project if `sase` is inactive.
- Legacy states `archived` and `closed` normalize to inactive through the existing lifecycle wire helpers and should
  reactivate to canonical `active`.
- Unknown refs should continue to behave as they do today; do not create new projects merely because a VCS-looking ref
  appears in a prompt.
- System-managed `home` should not be mutated.
- If activation fails due to missing ProjectSpec, invalid name, lock failure, or another lifecycle error, abort the
  launch and surface the error in the same style as the current launch failure path.
- `Ctrl+X` reveal should not mutate state by itself. Visibility is read-only until the user launches or explicitly
  activates through existing modal actions.

## Tests

- Modal tests:
  - `Ctrl+X` in `ProjectManagementModal` reveals inactive rows in the default active view.
  - Pressing `Ctrl+X` again hides inactive rows from the active view.
  - Row labels include the inactive indicator.
  - Footer/summary mention the new keybinding and visible state.
  - Existing Tab/Shift+Tab state filters still pass.
- Launch tests:
  - Update the current inactive-ref error tests to expect activation plus normal launch/chdir behavior.
  - Add a `resolve_known_project_vcs_launch_ref()` test for an inactive project that becomes active before workspace
    resolution.
  - Add/adjust TUI launch-body coverage for known inactive project refs.
  - Add a multi-prompt test where a later segment references an inactive project and activation still happens.
- Snapshot/visual tests:
  - If footer or row rendering changes affect existing Project Management PNG snapshots, update them intentionally.

## Verification

After implementation:

1. Run `just install` if the workspace environment has not already been refreshed.
2. Run focused tests for project management modal behavior, launch CWD resolution, known-project launch fallback, and
   xprompt parsing/launch helpers.
3. Run `just check` before finishing because this repo requires it after code changes.
