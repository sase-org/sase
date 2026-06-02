---
create_time: 2026-06-02 16:53:12
status: done
prompt: sdd/prompts/202606/hide_home_project_from_at_panel.md
---
# Hide `home` Project From `@` Agent Selector

## Problem

The `@` keymap invokes `action_start_custom_agent`, which opens `ProjectSelectModal`. That modal currently loads every
launchable project from `list_launchable_projects()`, including the system/home bare-git project named `home`, so the
selector shows `[P] home`.

This creates a redundant and confusing launch path because bare `space` already starts a home-mode agent directly. The
goal is to stop presenting the `home` bare-git project in the `@` selector while preserving the dedicated home-mode
entry point and existing project/CL launch behavior.

## Relevant Context

- `src/sase/ace/tui/bindings.py` binds `at` to `start_custom_agent` and `space` to `start_agent_home`.
- `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` implements:
  - `action_start_custom_agent()`, which opens `ProjectSelectModal`.
  - `action_start_agent_home()`, which directly calls `_show_prompt_input_bar_for_home()`.
- `src/sase/ace/tui/modals/project_select_modal.py` builds `[P] ...` rows from `list_launchable_projects()`.
- `src/sase/ace/tui/modals/project_discovery.py` intentionally treats `home` as launchable when it is a real active
  project. That behavior is useful for validation and stale-selection checks, so the display fix should not blindly make
  `home` non-launchable everywhere.
- `item_type="home"` remains a distinct legacy/semantic selection type. The requested change is only about the bare-git
  project row `[P] home`.

## Plan

1. Add a caller-scoped project exclusion option to `ProjectSelectModal`.
   - Introduce an optional constructor argument such as `exclude_project_names`.
   - Store it as a set/frozenset.
   - When loading project rows, skip exact project-name matches before creating `[P] ...` `SelectionItem`s.
   - Leave CL loading unchanged, so active ChangeSpecs from other projects still appear.
   - Leave `include_all` behavior unchanged.

2. Use that exclusion only for the `@` custom-agent selector.
   - In `action_start_custom_agent()`, instantiate `ProjectSelectModal(exclude_project_names={"home"})`.
   - Keep `action_start_agent_home()` and leader home handling unchanged so `space` and `,h` still start home mode.
   - Keep background-command and revival callers unchanged unless tests reveal they are unintentionally using the same
     user-facing `@` flow.

3. Preserve launchability validation.
   - Do not change `list_launchable_projects()` or `is_launchable_project()` semantics in `project_discovery.py`.
   - Existing persisted last selections and VCS xprompt MRU validation should continue to regard `home` as launchable
     when the project record is real and active.
   - `_start_custom_agent_from_selection()` can continue handling `project_name="home"` defensively if a saved/manual
     selection reaches it.

4. Add targeted tests.
   - Add a modal unit test proving `exclude_project_names={"home"}` removes `[P] home` while preserving other projects,
     active CLs, and optional `[*] ALL`.
   - Add or update an entry-point test proving `action_start_custom_agent()` pushes a `ProjectSelectModal` whose loaded
     items do not include `[P] home` when the discovery source returns `home`.
   - Update any existing test that directly modeled the `@` panel with an unfiltered `ProjectSelectModal`.

5. Verify.
   - Run the focused tests around project selection and agent entry points first.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Non-Goals

- Do not remove the `home` project from project discovery or project lifecycle management.
- Do not change the `space`, `Ctrl+Space`, or leader-mode keymaps.
- Do not delete or migrate persisted last-agent selections in this change.
