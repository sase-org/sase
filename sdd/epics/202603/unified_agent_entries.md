---
bead_id: sase-our6
status: done
prompt: sdd/prompts/202603/unified_agent_entries.md
---

# Plan: Unified Agent Entries for Axe-Spawned Agents

## Overview

Convert axe-spawned agents (fix-hook, mentor, crs, summarize) from custom entry types (`[crs]`, `[fix_hook]`,
`[mentor]`) to proper `[agent]` entries on the Agents tab, with full support for diffs, files, and all standard agent
features. Introduce a `hidden` boolean property to control default visibility, replacing the current type-based
visibility logic.

## Phase 1: Add `hidden` Property and `%hide` Directive (Foundation)

Add the `hidden` boolean field to Agent and `%hide` directive. Wire up visibility logic to use `hidden` instead of
type-based checks. Pure additive change.

### Changes

- **src/sase/ace/tui/models/agent.py**: Add `hidden: bool = False` field to Agent dataclass.
- **src/sase/xprompt/directives.py**: Add `"hide"` to `_KNOWN_DIRECTIVES`, `"h": "hide"` alias, `hide: bool = False` to
  `PromptDirectives`, wire up in `extract_prompt_directives()`.
- **src/sase/ace/tui/actions/agents/\_core.py**: Rewrite `_is_always_visible()` to use `agent.hidden` instead of
  `_is_axe_spawned_agent()`. Keep `_is_axe_spawned_agent()` for notification suppression.
- **src/sase/ace/tui/models/\_loaders/\_artifact_loaders.py**: In `enrich_agent_from_meta()`, read `hide` from
  `agent_meta.json` and set `agent.hidden = True`.
- **src/sase/ace/tui/models/\_loaders/\_changespec_loaders.py**: Set `hidden=True` on all agents created by
  hook/mentor/comment loaders.
- **src/sase/axe_run_agent_runner.py** (or agent_meta writer): Write `hide` field to `agent_meta.json` when `%hide`
  directive is set.
- **src/sase/ace/tui/actions/agents/\_core.py**: In `_load_agents()`, after loading and filtering, auto-dismiss hidden
  agents that have reached DONE or FAILED status. For each agent where
  `agent.hidden and agent.status in DISMISSABLE_STATUSES`, call `self._persist_dismissed_agent(agent.identity)` and
  filter it out of the agent list. This ensures hidden agents disappear automatically when complete rather than sitting
  in a dismissable state behind the `.` toggle.

### Acceptance Criteria

- `hidden` field exists on Agent, defaults to False.
- `%hide` / `%h+` are recognized directives parsed into `PromptDirectives.hide`.
- `_is_always_visible()` uses `agent.hidden` for visibility.
- All ChangeSpec-loaded agents (FIX_HOOK, SUMMARIZE, MENTOR, CRS) have `hidden=True`.
- `.` toggle behavior unchanged from user perspective.
- Hidden agents with DONE/FAILED status are auto-dismissed (removed from agent list, added to dismissed set).
- `just check` passes.

---

## Phase 2: Make Axe Runners Write `done.json` Artifacts

Have axe runner scripts write `done.json` markers on completion, matching the format used by `ace(run)` agents. Extend
`load_done_agents()` to scan artifact subdirectories beyond `ace-run`.

### Changes

- **src/sase/axe_runner_utils.py**: Extend `finalize_axe_runner()` to write `done.json` into artifacts directory with
  standard fields plus `hidden: true`.
- **src/sase/axe_fix_hook_runner.py**: Wire artifacts_dir to finalization for done.json.
- **src/sase/axe_crs_runner.py**: Same treatment.
- **src/sase/axe_summarize_hook_runner.py**: Same treatment.
- **src/sase/ace/scheduler/mentor_runner.py**: Same treatment for mentor subprocess.
- **src/sase/ace/tui/models/\_loaders/\_artifact_loaders.py**: Extend `load_done_agents()` to scan `fix-hook/`, `crs/`,
  `summarize-hook/`, `mentor-*/` artifact directories. Read `hidden` from done.json.

### Acceptance Criteria

- Completed fix-hook/crs/summarize/mentor agents produce `done.json` in their artifacts dir.
- `load_done_agents()` picks up these agents with `hidden=True`.
- Existing ChangeSpec loaders still work (dual-source, dedup handles it).
- `just check` passes.

---

## Phase 3: Update Deduplication to Prefer `[agent]` Representation

When both a RUNNING/done.json entry and a ChangeSpec entry exist for the same axe-spawned agent, prefer the
RUNNING/done.json representation and merge ChangeSpec metadata into it.

### Changes

- **src/sase/ace/tui/models/agent_loader.py**: Reverse deduplication logic. Currently drops RUNNING entries in favor of
  ChangeSpec entries for axe agents. Instead: keep RUNNING entry, merge type-specific fields (hook_command,
  mentor_profile, reviewer) from ChangeSpec entry.
- **src/sase/ace/tui/models/agent.py**: Update `get_artifacts_dir()` to handle `axe(...)` workflow prefixes for
  RUNNING-typed agents.
- **src/sase/ace/tui/models/\_loaders/\_artifact_loaders.py**: Set `hidden=True` on agents with `axe(...)` workflow
  prefixes in `load_agents_from_running_field()`.

### Acceptance Criteria

- Running axe-spawned agents appear as `[agent]` (not `[fix-hook]`, `[mentor]`, etc.).
- Completed axe-spawned agents appear as `[agent]` via done.json.
- Type-specific metadata (hook_command, reviewer, mentor_profile) preserved on merged agent.
- Artifacts (diffs, files, response) accessible for these agents.
- `hidden=True` set for all axe-spawned agents.
- `just check` passes.

---

## Phase 4: Clean Up Agent Type System and Display Logic

Remove redundant `AgentType` enum values and simplify type-dispatching code.

### Changes

- **src/sase/ace/tui/models/agent.py**: Remove FIX_HOOK, SUMMARIZE, MENTOR, CRS from AgentType. Remove type-specific
  branches in `get_artifacts_dir()`. Simplify `is_agent_entry`.
- **src/sase/ace/tui/models/\_loaders/\_changespec_loaders.py**: Create agents with `AgentType.RUNNING` + `hidden=True`
  (keep loaders for running agents without done.json yet).
- **src/sase/ace/tui/actions/agents/\_core.py**: Simplify `_is_axe_spawned_agent()` to just check `agent.hidden`.
- **src/sase/ace/tui/actions/agents/\_killing.py**: Remove type-dispatch for removed types.
- **src/sase/ace/tui/widgets/agent_list.py**: Remove color entries for removed types.
- **src/sase/ace/tui/modals/revive_agent_modal.py**: Remove color entries for removed types.
- **tests/**: Update all tests referencing removed enum values.

### Acceptance Criteria

- AgentType enum has only RUNNING and WORKFLOW.
- All agents show as `[agent]` or `[workflow]` on Agents tab.
- Kill, dismiss, revive work for all agents.
- `_is_axe_spawned_agent()` simplified to use `agent.hidden`.
- No references to removed enum values in codebase.
- `just check` passes.
