---
create_time: 2026-05-01 12:15:08
status: wip
---
# Independent Plan-Chain Agents

## Goal

Split the plan/question/feedback/coder handoff chain into independent Agents-tab entries while preserving the naming
conventions users already rely on:

- planner: `<name>.plan`
- question prompt: `<name>.q`
- feedback replans: `<name>.<N>`
- coder: `<name>.coder`

The current system already creates separate artifact directories for follow-up work, but the TUI and several helper
paths still treat these artifacts as child rows of a parent workflow. The implementation should preserve lineage, status
aggregation, cleanup behavior, chat links, `#resume`, `%wait`, and name reservation while making each phase appear and
act like its own agent entry on the Agents tab.

## Relevant Current Behavior

- `src/sase/axe/run_agent_exec_plan.py` handles `sase plan` and `sase questions` markers. It mutates the current
  artifact metadata for `.plan` / `.q`, then creates follow-up artifacts via `create_followup_artifacts()`.
- `src/sase/axe/run_agent_helpers.py` writes follow-up metadata with `parent_timestamp`, `role_suffix`, optional
  `workflow_name`, and `name`.
- `src/sase/ace/tui/models/agent_loader.py` currently collects follow-up artifacts by `parent_timestamp`, folds them
  under the parent, propagates status/timestamps/diff data to the parent, and renders them adjacent to workflow steps.
- `Agent.is_workflow_child` is currently true for any `parent_timestamp`, which makes plan-chain follow-ups look like
  child rows even when they represent independent LLM invocations.
- `src/sase/agent/running.py` intentionally skips `parent_timestamp` follow-ups for CLI running-agent lists; this is
  correct for today’s dedup model but conflicts with independent entries.
- Naming is inconsistent with the requested convention: coder is currently represented as `.code` in several places,
  while the desired visible/name convention is `.coder`. Legacy `.code` artifacts must continue to load and resolve.

## Phase 1: Introduce Explicit Plan-Chain Identity

Owned area: runner metadata and shared role helpers.

1. Add a small shared role/naming helper module for plan-chain phases:
   - canonical role suffixes: `.plan`, `.q`, numeric feedback suffixes, `.coder`
   - legacy coder suffix alias: `.code`
   - helpers to classify plan-chain artifacts independently of generic workflow steps
   - helpers to produce visible names from base agent name plus role
2. Update `handle_plan_marker()` and `handle_questions_marker()` to use the helper instead of inline string
   construction.
3. Change new coder artifacts to use `.coder` and `<name>.coder`, while keeping `.code` accepted as a legacy suffix in
   readers.
4. Keep writing the existing lineage fields for compatibility, but add a forward-looking metadata field if needed, such
   as `plan_chain_parent_timestamp`, so future phases can distinguish handoff lineage from workflow-step parentage.
5. Add focused tests around artifact metadata creation:
   - first plan becomes `<name>.plan`
   - question becomes `<name>.q`
   - feedback rounds become `<name>.<N>`
   - coder becomes `<name>.coder`
   - legacy `.code` still classifies as coder

Verification for this phase:

- `pytest tests/test_axe_run_agent_helpers.py tests/test_axe_run_agent_exec.py tests/test_agent_names_auto_name.py tests/test_agent_names_workflow.py`

## Phase 2: Loader Model Split Without TUI Rendering Changes

Owned area: Agents-tab model loading and status derivation.

1. Extend the `Agent` model with an explicit distinction between:
   - workflow child steps from `prompt_step_*.json`
   - plan-chain follow-up agents from separate `ace-run/<timestamp>` artifact dirs
2. Preserve lineage and aggregation data, but stop relying on `Agent.is_workflow_child` for plan-chain artifacts.
3. Refactor `_apply_status_overrides()` to use plan-chain classification instead of raw
   `parent_timestamp and not parent_workflow` checks.
4. Keep parent status summaries working:
   - root `.plan` still shows `PLANNING`, `PLAN APPROVED`, `PLAN DONE`, `EPIC CREATED`, etc.
   - question-only states still become `QUESTION`
   - feedback rounds still affect the root plan’s displayed progress
5. Keep legacy artifacts loadable:
   - `.code` maps to coder behavior
   - artifacts that only have `parent_timestamp` still link to their parent
6. Add tests that assert the loaded model can distinguish plan-chain entries from workflow step children without
   changing UI order yet.

Verification for this phase:

- `pytest tests/test_agent_loader_status_overrides.py tests/test_agent_loader_dedup_pid.py tests/test_agents_tab_query_integration.py tests/test_fold_filtering.py`

## Phase 3: Render Plan-Chain Phases As Independent Agents

Owned area: Agents-tab ordering, grouping, folding, selection, and counts.

1. Change `_sort_and_reorder()` so plan-chain agents are not inserted as child rows under the root workflow. They should
   appear as normal independent rows in the main list.
2. Keep same-base grouping useful: standard grouping can still place `a.plan`, `a.q`, `a.2`, and `a.coder` under the
   same name-root banner, but each row should be selectable and rendered as its own agent entry, not as an indented
   workflow child.
3. Keep actual workflow steps nested under workflow parents.
4. Update grouping keys if needed so plan-chain rows do not inherit the parent’s grouping identity in ways that hide
   them under the parent fold.
5. Ensure tab counts, filters, hidden toggles, selection restoration, jump hints, tagging, marking, and detail-panel
   updates all operate on the independent phase rows.
6. Add TUI/model tests for a representative chain:
   - `<name>.plan`
   - `<name>.q`
   - `<name>.2`
   - `<name>.coder`
   - an unrelated workflow with real prompt-step children

Verification for this phase:

- `pytest tests/test_ace_tui_widgets.py tests/test_agent_kill_dismiss_fast_path.py tests/test_agent_dismiss_in_memory.py tests/test_agent_kill_bulk.py tests/test_fold_filtering.py`

## Phase 4: CLI, Lookup, Cleanup, Resume, And Wait Compatibility

Owned area: agent name APIs and non-TUI lifecycle behavior.

1. Update `src/sase/agent/running.py` so `sase agents status` can include independent plan-chain entries instead of
   skipping every `parent_timestamp` artifact. Preserve skips for true duplicate workflow children.
2. Update `find_named_agent()` and `is_workflow_complete()` to resolve both old and new metadata:
   - exact phase names such as `<name>.coder`
   - root workflow references such as `<name>`
   - legacy `<name>.code`
3. Update active-name reservation so independent phase names do not collide while the base auto-name remains reserved
   for the visible chain.
4. Update explicit rename behavior to rewrite child phase prefixes when a root workflow is renamed. There is already a
   TODO in `claim_agent_name()` for this.
5. Audit kill, dismiss, revive, wait, and cleanup paths so operating on one independent phase row has predictable scope,
   while bulk cleanup by root/tag can still handle an entire chain.
6. Add regression coverage for:
   - `sase agents status --all` showing phase entries
   - kill/dismiss on a single phase
   - dismissing a root chain still handles related phases
   - `#resume:<name>.coder` and `%wait:<name>.coder`
   - legacy `.code` lookup

Verification for this phase:

- `pytest tests/test_running_agents_snapshot.py tests/test_agent_names_workflow.py tests/test_dismissed_agent_lifecycle.py tests/test_core_facade/test_agent_cleanup.py tests/test_agent_revive.py`

## Phase 5: Chat Links, History, Detail Panels, And Migration Polish

Owned area: user-facing details and compatibility polish.

1. Update chat-link labels and saved history suffixes to display `.coder` for new coder phases while preserving existing
   `.code` links.
2. Update detail panels and timestamp sections so parent summaries do not duplicate information that is now visible on
   independent phase rows.
3. Update any copy/help text that refers to `.code` or child-row behavior.
4. Confirm plan file, Q&A, feedback, diff, and generated attachment panels attach to the correct independent phase row.
5. Add a small compatibility fixture using old `.code` and `parent_timestamp`-only metadata so existing user history
   still renders.

Verification for this phase:

- `pytest tests/history/test_chat_links.py tests/history/test_chat_extras.py tests/test_agent_model_timestamps.py tests/test_ace_tui_widgets.py`

## Phase 6: End-To-End Validation And Cleanup

Owned area: cross-cutting validation after the prior phases land.

1. Run a real local flow with a named agent that:
   - asks a question
   - submits a plan
   - receives feedback
   - submits a revised plan
   - launches a coder
2. Verify the Agents tab shows independent entries with the expected names:
   - `<name>.plan`
   - `<name>.q`
   - `<name>.2`
   - `<name>.coder`
3. Verify selection, detail panels, chat links, kill/dismiss, resume, wait, and grouping behavior manually in
   `sase ace`.
4. Run the full repository checks after installation:
   - `just install`
   - `just check`
5. Remove or rewrite obsolete tests that asserted child-row folding for plan-chain follow-ups, but keep compatibility
   tests for old artifacts.

## Implementation Notes

- Do not delete support for legacy `.code`; treat it as an input alias indefinitely.
- Avoid runtime-specific branches. Claude, Gemini, Codex, and plugin runtimes should all use the same metadata and
  naming behavior.
- Keep artifact schema changes additive until compatibility tests prove old artifacts still work.
- Be careful with `parent_timestamp`: it currently means both “workflow child” and “handoff lineage.” The core design
  work is separating those concepts without breaking old artifacts.
- If a phase changes `sase ace` behavior or key/help text, update the help popup per `src/sase/ace/AGENTS.md`.
