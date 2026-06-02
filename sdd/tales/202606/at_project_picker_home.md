---
create_time: 2026-06-02 06:25:00
status: done
prompt: sdd/prompts/202606/at_project_picker_home.md
---
# Plan: Show Real Projects In The @ Picker

## Goal

Stop showing the synthetic `~ (home directory)` option when the top-level `@` keymap opens the custom agent picker. The
picker should show only real SASE launch targets: launchable projects and active ChangeSpecs. If the real `home`
ProjectSpec is launchable, it should appear as the normal `home` project and selection should launch through the
`#git:home` workflow instead of direct home mode.

## Current Behavior

- `@` is bound to `start_custom_agent`, which calls `action_start_custom_agent()` and opens `ProjectSelectModal`.
- `ProjectSelectModal._load_items()` unconditionally inserts a synthetic home row: `[H] ~ (home directory)` with
  `item_type="home"`.
- `project_discovery.list_launchable_projects()` asks the Rust lifecycle facade for records with `include_home=False`,
  so the real `home` project is excluded from the project rows.
- `project_discovery.is_launchable_project()` also rejects `project_name == "home"`, which means persisted replay
  selections and VCS MRU filtering treat `#git:home` as non-launchable when they validate known project prefixes.
- Selecting a normal project already builds a VCS prefix with `_vcs_prompt_prefix_or_notify()`. If `home` becomes a
  normal project row, that path should prefill `#git:home ` and the existing home-mode prompt resolution will switch to
  workspace-managed VCS launch when the prompt is submitted.

## Implementation Approach

1. Update project discovery so `home` can be a launchable project only when it exists as a real active ProjectSpec:
   - Change `list_launchable_projects()` to request lifecycle records with `include_home=True`.
   - Remove the hard-coded `project_name == "home"` rejection from `is_launchable_project()`.
   - Keep the existing launchability checks: active lifecycle state, project file present, workspace path exists, and a
     workspace provider can detect the workflow type.

2. Remove the synthetic direct-home row from `ProjectSelectModal._load_items()`:
   - Do not append `[H] ~ (home directory)`.
   - Keep the optional `[*] ALL` item for flows that request `include_all=True`.
   - Let `[P] home` appear naturally when `list_launchable_projects()` returns `home`.
   - Keep the `[H]` rendering branch harmless unless follow-up cleanup removes the legacy `home` item type entirely.

3. Preserve direct home-mode behavior outside the `@` picker:
   - Do not remove `_show_prompt_input_bar_for_home()` or `_select_and_open_editor_for_home()`, because other actions
     and history/editor flows still use direct home-mode semantics.
   - Do not change the leader-mode `agent_home` shortcut in this change unless a failing test shows it depends on the
     same picker entry. The requested behavior is specifically the `@` picker.

4. Update persistence and replay behavior to match the new semantics:
   - Persisted selections for `home` as `item_type="project"` should validate through `is_launchable_project("home")`.
   - Existing saved legacy `item_type="home"` values can still load and replay direct home mode for backward
     compatibility, but new picker selections should no longer create them.
   - MRU pruning should stop treating `#git:home` as stale when the real `home` project is launchable.

5. Update focused tests:
   - `tests/ace/tui/modals/test_project_select_modal.py` should expect launchable `home` in the project list when its
     ProjectSpec is valid, and should no longer expect `[H] ~ (home directory)` in modal items.
   - `is_launchable_project("home")` should be true for valid active home ProjectSpecs and false for stale/missing or
     inactive home ProjectSpecs.
   - Add or adjust a narrow entry-point test if needed to assert selecting `[P] home` constructs `#git:home ` rather
     than direct home mode.
   - Keep legacy `item_type="home"` load/save tests only if backward compatibility remains intentional.

## Verification

- Run the focused project picker tests:
  `uv run pytest tests/ace/tui/modals/test_project_select_modal.py tests/ace/test_last_agent_selection.py`
- Run related entry-point/MRU tests if impacted:
  `uv run pytest tests/ace/tui/test_entry_points_vcs_prefix_errors.py tests/history`
- Because this repo requires it after file changes, run: `just install` `just check`

## Risks And Constraints

- `home` is system-managed in project lifecycle operations, but launch selection is different from management. This
  change should include `home` only in launch discovery, not in project-management mutation flows.
- If the Rust lifecycle facade marks `home` as `system_managed`, that should not exclude it from launchability; the
  decisive checks are real ProjectSpec presence, active state, valid workspace, and provider detection.
- Removing support for the `home` `SelectionItem` type would be broader than necessary because persisted selection files
  may already contain it. The first pass should stop producing it from the picker while continuing to tolerate it.
