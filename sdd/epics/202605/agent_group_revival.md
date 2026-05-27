---
create_time: 2026-05-27 11:52:09
status: done
prompt: sdd/prompts/202605/agent_group_revival.md
bead_id: sase-47
tier: epic
---
# Agent Group Save And Revival Plan

## Goal

Add an Agents-tab `S` workflow that dismisses marked agents without killing any process, saves that marked set as a
revivable group, and replaces the current Agents-tab `R` flow with a richer revival panel:

- `S` on Agents saves the current marked agent set as a group and dismisses/hides those agents.
- `S` never sends process signals. Running agents must not be killed as a side effect.
- `R` on Agents opens a new revival panel listing saved groups first.
- The panel initially shows up to 20 saved groups, supports load-more paging, lets the user preview each group, and
  revives a selected group as one operation.
- The final entry opens the legacy custom revival search panel, equivalent to the current pre-change `R` flow.

The implementation should keep the ChangeSpecs-tab `S` bulk status behavior and the ChangeSpecs-tab `R` rewind behavior.

## Current Architecture Notes

- App keybindings are global, not tab-scoped. `S` is already bound to `bulk_change_status`, and that action currently
  no-ops outside the ChangeSpecs tab.
- Adding a second app binding with key `S` would conflict with the existing keymap system. The pragmatic approach is to
  make `action_bulk_change_status` dispatch by tab: ChangeSpecs keeps bulk status, Agents calls a new
  save-marked-agent-group flow.
- The existing Agents-tab `R` behavior lives in `AgentRevivalMixin.action_start_rewind`: Agents opens project selection
  and then `DismissedAgentSelectModal`; other tabs delegate to rewind.
- Existing dismissal and kill paths share machinery. The new `S` path must not reuse the bulk kill path because that
  sends SIGTERM for running agents.
- Existing dismissed agent bundles are per-agent under `~/.sase/dismissed_bundles`, with Python facades in
  `src/sase/ace/dismissed_agents.py` and shared Rust core archive/cleanup APIs in `../sase-core`.
- Cross-frontend state belongs in `../sase-core`; the TUI should own only presentation and event-loop glue.

## Product Design

The revival panel should be a two-pane modal, visually related to the existing dismissed-agent modal but more scannable:

- Left pane: saved groups as compact rows.
  - Row content: generated group title, relative/absolute saved time, agent count, status mix, project/CL hint, and
    small model/runtime hints when available.
  - The last row is always `Custom revival search...` and opens the legacy modal.
  - If more than 20 groups exist, show a `Load more saved groups...` row above the custom-search row.
- Right pane: selected group preview.
  - Header with title, saved timestamp, count, and status breakdown.
  - A concise agent list grouped by project/CL where helpful.
  - Preview excerpts or metadata for the highlighted group without requiring the user to enter the custom search.
- Controls:
  - `j/k` navigation, Enter revive/open, Esc/q cancel.
  - A clear hint line with load-more/custom-search behavior.
- Empty state:
  - If no saved groups exist, the panel still opens and shows the custom-search entry.

Generated group titles should be deterministic and useful, for example:

- `3 agents from @backend`
- `2 agents in my-cl`
- `5 agents across 3 CLs`

## Data Model

Add a saved-group record separate from individual dismissed bundles. A group should reference existing per-agent bundles
instead of duplicating full agent payloads.

Proposed group fields:

- `schema_version`
- `group_id`
- `created_at`
- `source`: initially `"marked_agents"`
- `title`
- `agent_count`
- `top_level_agent_count`
- `status_counts`
- `project_names`
- `cl_names`
- `agent_refs`

Each `agent_ref` should include:

- `agent_type`
- `cl_name`
- `raw_suffix`
- `bundle_path` if known
- `is_workflow_child`
- `parent_timestamp`
- `display_name`
- `agent_name`
- `status`
- `start_time`
- `model`
- `llm_provider`

Store groups under a new archive location such as `~/.sase/dismissed_agent_groups/` with a small indexed/queryable API.
The exact layout can be JSON files plus an index, but the public interface should be stable:

- save group
- list summaries with `limit` and `cursor`
- load one group with refs
- mark group revived
- tolerate missing/corrupt referenced bundles

## Phase 1 - Core Group Archive Contract

Owner: core/backend agent.

Implement the shared saved-group persistence contract in `../sase-core` and expose Python bindings/facades in this repo.

Deliverables:

- Rust wire structs and functions for saved agent groups: save, list page, load by id, mark revived.
- Python wrapper/facade near `src/sase/ace/dismissed_agents.py`, keeping TUI callers thin.
- Tests in `sase-core` for serialization, paging, corrupt/missing group files, and revived marking.
- Python tests for facade behavior with temporary `~/.sase` paths.

Design constraints:

- Do not store full agent payloads in the group file; reference per-agent dismissed bundles.
- Preserve enough summary fields for the revival panel to render without loading every bundle.
- Keep cursor paging deterministic: newest groups first by `created_at`.
- Support old installs gracefully when the Rust binding is missing, using a Python fallback if this repo already follows
  that pattern for adjacent archive behavior.

Acceptance criteria:

- A saved group can be persisted and listed in newest-first pages of 20.
- Loading a saved group returns stable refs even if some bundle files are missing.
- Marking a group revived does not delete group metadata.

## Phase 2 - Non-Killing `S` Save/Dismiss Flow

Owner: TUI/actions agent.

Implement the Agents-tab `S` branch and the save/dismiss operation for marked agents.

Deliverables:

- Update `action_bulk_change_status` so:
  - ChangeSpecs tab keeps existing bulk status behavior.
  - Agents tab calls a new `_save_marked_agent_group()` action.
  - Other tabs still no-op.
- Add a non-killing dismissal path for marked agents.
- Save per-agent dismissed bundles for all selected/cascaded agents, then save one group record referencing those
  bundles.
- Add selected identities to `_dismissed_agents`, clear marks on success, update in-memory rows, and persist the
  dismissed index.
- Update Agents help/footer/palette labels so `S` reads as saving/dismissing marked agents on the Agents tab.

Important behavior:

- Never call `_kill_process_group`, `_do_bulk_kill_agents`, or any SIGTERM path.
- Running agents should be hidden via dismissed identity state, but their process and live artifacts/workspace claim
  should not be torn down merely because `S` was pressed.
- Completed agents can use existing dismissal marker-cleanup behavior where safe.
- Workflow parent selection should cascade to workflow children for saved bundle refs and revival.
- If no agents are marked, show a warning and make no writes.

Tests:

- Unit test that Agents-tab `S` dispatches to `_save_marked_agent_group`.
- Unit test that ChangeSpecs-tab `S` still opens bulk status.
- Unit test that marked running agents are not killed.
- Unit test that group records include marked agents in stable display order.
- Unit test that workflow children are included when a parent is selected.
- Keymap/help tests reflecting the new Agents-tab `S` label.

## Phase 3 - Revival Panel UI

Owner: TUI/modal agent.

Build the new revival panel modal and route Agents-tab `R` to it.

Deliverables:

- New modal, likely `SavedAgentGroupRevivalModal`, with:
  - paged group list
  - preview pane
  - load-more sentinel
  - final custom-search sentinel
- New rendering helpers for group row labels and previews.
- Styles in `styles.tcss` consistent with the existing modal but visually upgraded.
- `AgentRevivalMixin._revive_agent()` opens this panel instead of directly opening project selection/custom search.
- Selecting custom search calls the existing `_show_dismissed_agents_for_scope` path with the same behavior users have
  today.

Tests:

- Modal unit tests for initial 20-group page, load-more row, custom-search final row, empty state, and preview updates.
- Routing test that `R` on Agents opens the new panel.
- Routing test that choosing custom search opens the legacy project/scope + dismissed-agent modal flow.

## Phase 4 - Group Revival Execution

Owner: TUI/revival agent.

Wire selecting a saved group to actual revival using the existing batch revive machinery.

Deliverables:

- Resolve group refs to `Agent` objects by loading dismissed bundles for the group's suffixes.
- Hydrate `_dismissed_agent_objects` with the loaded group agents so existing child/follow-up cascade logic works.
- Revive the group through `_do_revive_agents`, preserving the current full-history refresh and focus-selection
  behavior.
- Mark the group revived after successful revive.
- Show partial-failure feedback when some refs cannot be loaded.
- Reuse revive logging and add group metadata to logs where practical.

Tests:

- Reviving a group removes all relevant dismissed aliases.
- Reviving a group restores parent/child artifacts and schedules full-history refresh once.
- Partial missing bundle refs are skipped with a warning; valid refs still revive.
- The first selected top-level group agent is selected after refresh.

## Phase 5 - Polish, Visual Coverage, And Regression Pass

Owner: integration/polish agent.

Run the feature end to end, tighten visual design, and cover regressions.

Deliverables:

- Visual snapshot coverage for the new panel in normal, empty, load-more, and preview-rich states.
- Integration-style tests around marking agents, pressing `S`, pressing `R`, previewing the saved group, and reviving
  it.
- Verify command palette availability and help modal text.
- Run `just install` if needed, then `just check` after code changes.

Quality bar:

- The panel should feel dense and polished, not like a generic form.
- Text must fit at common terminal widths.
- The final custom-search entry must always remain accessible.
- No existing `x` kill/dismiss behavior should regress.
- Existing custom revival search behavior should remain available and functionally equivalent.

## Suggested Handoff Order

1. Phase 1 must land first because later phases need a stable group persistence API.
2. Phase 2 can start after Phase 1 facades exist.
3. Phase 3 can start with mocked group summaries once Phase 1 wire shapes are agreed, but should not land before the
   facade names are stable.
4. Phase 4 depends on Phases 1 and 3.
5. Phase 5 should be last and should own visual snapshots plus `just check`.

## Main Risks

- Running-agent dismissal semantics are subtle. The `S` path must hide without killing and should not release workspaces
  or delete live markers in a way that breaks an active process.
- The existing dismissed-bundle index in Python and the newer archive APIs in `sase-core` are not perfectly aligned.
  Phase 1 should choose one stable contract and keep compatibility wrappers clear.
- Global keybindings are not tab-scoped, so the implementation should avoid adding a second `S` binding.
- Large dismissed archives need paging; the revival panel should render summaries first and load full bundles only for
  preview/revival.
