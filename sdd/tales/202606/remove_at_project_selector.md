---
create_time: 2026-06-19 20:55:12
status: wip
prompt: sdd/prompts/202606/remove_at_project_selector.md
---
# Remove Legacy `@` Project/ChangeSpec Agent Selector

## Goal

Remove support for the legacy top-level `@` custom-agent keymap and the Project/ChangeSpec selection panel it opens. The
prompt input now supports `+` / `#+` VCS project and ChangeSpec completion, so selecting a project or ChangeSpec through
a separate modal before opening the prompt should no longer be part of the agent-launch workflow.

## Current Findings

- The direct `@` path is `start_custom_agent`, bound as `at` in `src/sase/default_config.yml`,
  `src/sase/ace/tui/bindings.py`, and the generated keymap registry metadata.
- The related repeat-last path is `start_agent_from_changespec`, bound to `ctrl+@` / Ctrl+Space, backed by
  `sase.ace.last_agent_selection` and `_last_custom_agent_selection` state. This exists to replay a selection made by
  the old `@` panel, so it should be removed with the selector.
- `ProjectSelectModal` is the legacy selection panel. It currently has agent-launch behavior such as custom-name
  fallback, `^G` open-in-editor, and project deletion. It is also reused by background command and dismissed-agent
  revival flows, so implementation must either replace those call sites with narrower purpose-built flows or explicitly
  split reusable project-scope selection away from the obsolete `@` launch panel.
- The quick current-context launch flows are separate and still useful: bare `Space` opens a home prompt, and leader
  `, Space` launches from the current PR or selected agent without the old panel. These should remain.
- There are many intentional non-feature `@` references that must stay: file references (`@path`), xprompt picker
  (`#@`), agent-name templates (`%name:@...`), agent/tag display text, and docs for those features.

## Plan

1. Remove the app-level keymap actions for the obsolete workflow:
   - Drop `start_custom_agent` and `start_agent_from_changespec` from `AppKeymaps`, `_BINDING_META`, default config, and
     fallback bindings.
   - Remove command-palette metadata and availability predicates for those app commands.
   - Keep `start_agent_home`, `start_last_vcs_xprompt_in_editor`, and leader `agent_from_cl` intact.

2. Remove repeat-last selection state and persistence:
   - Delete `src/sase/ace/last_agent_selection.py` if no non-obsolete users remain.
   - Remove `_last_custom_agent_selection`, `_load_last_custom_agent_selection`, stale-selection clearing, and any save
     calls from launch/relaunch/quick-launch paths.
   - Replace comments and toasts mentioning `@/Ctrl+Space` with current behavior or remove them.

3. Remove the legacy selector panel from the agent-launch path:
   - Delete `action_start_custom_agent` and `_start_custom_agent_from_selection`.
   - Remove `ProjectSelectModal` usage from agent launch.
   - For remaining non-agent-launch users, avoid preserving the old `@` panel under the same API/name. Prefer a smaller
     scope-selection modal or direct current-context flow if needed by background command or revival, with names and
     docs that do not imply the old `@` agent picker.

4. Clean up modal exports, styles, snapshots, and tests:
   - Remove or rename `ProjectSelectModal`, `ProjectSelectResult`, and `SelectionItem` exports as appropriate after the
     remaining call sites are handled.
   - Delete obsolete project-select visual snapshots and modal tests, or rewrite tests around any narrower replacement
     modal.
   - Update keymap, command catalog, help modal, E2E, and agent-launch tests to assert the absence of the removed
     actions and the continued behavior of `Space`, leader `, Space`, `Ctrl+G`, and `#+` prompt completion.

5. Update user-facing docs:
   - Remove `@` rows from `docs/ace.md` workflow/agent/AXE command tables.
   - Remove Ctrl+Space/repeat-last help text.
   - Add or preserve references to the new `+` / `#+` prompt completion where docs already describe prompt-input
     completion, without disturbing unrelated `@path`, `#@`, or agent-name-template docs.

6. Verify thoroughly:
   - Run targeted tests for keymaps, command catalog/help, prompt completion, agent launch, and any replacement
     background-command/revival scope selector.
   - Run `just install` and then `just check` after implementation changes, per repo instructions.
   - Finish with `rg` checks for removed symbols and obsolete text: `start_custom_agent`, `start_agent_from_changespec`,
     `last_agent_selection`, `_last_custom_agent_selection`, `ProjectSelectModal`, `ProjectSelectResult`, and
     `@/Ctrl+Space`.

## Non-Goals

- Do not remove `@path` prompt file-reference completion.
- Do not remove `#@` xprompt picker behavior.
- Do not remove `@` agent-name-template semantics.
- Do not change the shared Rust/Python `#+` VCS project completion algorithm unless tests reveal a direct integration
  issue.
