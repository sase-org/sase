---
create_time: 2026-05-23 14:09:23
bead_id: sase-40
tier: epic
status: done
prompt: sdd/prompts/202605/agents_sibling_keymap.md
---
# Agents Tab `~` Sibling Navigation Plan

## Goal

Add a `~` keymap to the Agents tab of `sase ace` that jumps between sibling agents. The interaction should match the
spirit of the CLs tab sibling navigation while fitting the Agents tab layout:

- `~` on an Agents-tab agent with exactly one visible sibling jumps directly to that sibling row.
- `~` on an Agents-tab agent with multiple visible siblings opens a polished chooser modal.
- The selected agent's visible sibling count is surfaced in the TUI without adding a side panel.
- The hot j/k navigation and info-panel update paths stay fast.

No SASE memory files should be modified.

## Sibling Definition

For an agent named `foo.bar`, its sibling family is `foo.*`. It is siblings with every other visible agent named
`foo.<name>`, where `<name>` may itself contain periods. Examples:

- `foo.plan`, `foo.code`, and `foo.review.pass1` are siblings.
- `foo` has no sibling family because it has no segment after the first period.
- `bar.plan` is not a sibling of `foo.plan`.

Use the explicit agent name (`Agent.agent_name`) as the source of truth. Preserve display casing, but use a case-folded
family key for matching so `Foo.plan` and `foo.code` behave as one family.

For the count and jump target list, "visible sibling" means an agent row that is currently rendered on the Agents tab
after query/filtering, dismissed/killed state, STARTING-row suppression, tag panels, grouping mode, and collapsed group
state are applied. A collapsed banner is not an agent row, so agents hidden under that banner are not jump targets until
the group is expanded.

## Design

Add a small cached index for sibling navigation rather than scanning the agent list on every selection change.

The index should be presentation-layer state in this repo, not Rust core: sibling navigation, folded visibility, panels,
and row rendering are TUI-only concerns. The Rust boundary does not need to change.

Recommended shape:

- New `src/sase/ace/tui/models/agent_siblings.py`
- `agent_sibling_family(agent: Agent) -> str | None`
- `AgentSiblingIndex` with:
  - `siblings_for(global_idx) -> tuple[int, ...]`
  - `sibling_count(global_idx) -> int`
  - `panel_idx_for(global_idx) -> int | None`
  - render-order-preserving sibling lists
- Build input: `self._agents` plus the currently visible agent rows across all rendered tag panels.
- Cache key: agents-list identity, panel key tuple, grouped/split panel mode, grouping mode, and
  `AgentGroupFoldRegistry.version`.

The modal should be a new `AgentSiblingModal`, not a side panel. It should be compact, keyboard-first, and visually
aligned with existing modal styling:

- Centered modal, double/thick accent border, surface background.
- Title: `Sibling Agents: foo.*` plus count.
- Rows in actual render order, excluding the current agent.
- Each row shows a quick key, agent name, status, tag/panel label, and a compact time/status hint when available.
- Bindings: `j/k` or arrows move, `enter` jumps, `a-z` quick-selects visible rows, `escape/q` closes.

The visible count should appear in `AgentInfoPanel`, not in each row. Row badges that depend on the current selection
would require row re-rendering during j/k bursts, which is the wrong tradeoff. A top-bar badge is cheaper and clearer:

`[siblings: 3 (~)]`

The footer can also advertise `~ sibling` / `~ siblings (N)` only when the focused agent has visible siblings.

## Performance Contract

The hot path must remain O(1) per selection for sibling state:

- `_update_agents_info_panel()` may read `sibling_count(current_idx)` from the cached index, but must not rebuild
  grouping trees or scan all agents on every j/k.
- The all-panel visible-row walk may happen when the agents list, grouping mode, fold version, or panel layout changes.
  It should be amortized across j/k bursts.
- Opening the modal may do richer formatting because `~` is not the j/k hot path.
- Existing render caches should keep working; do not add selected-sibling fields to agent row render keys unless the
  rows actually render that data.

Phase 4 should verify this with targeted cache tests and the existing TUI j/k bench harness when feasible.

## Phase 1: Sibling Index Foundation

Owner: Agent instance 1.

Implement the model-level sibling helpers and app-level cache plumbing, but do not wire `~` yet.

Deliverables:

- Add `agent_siblings.py` with pure sibling-family parsing and `AgentSiblingIndex`.
- Add an Agents mixin/helper method such as `_agent_sibling_index()` that builds the index once per cache key and reuses
  it from info/footer/navigation code.
- Reuse existing panel/tree helpers (`rendered_panel_slice`, `build_agent_tree`) so visibility matches rendered rows,
  including tag panels and folded groups.
- Invalidate or naturally refresh the cache when `_invalidate_agent_panel_cache` runs, when fold state changes, or when
  grouping/panel mode changes.

Tests:

- Unit tests for family parsing:
  - `foo.bar` and `foo.bar.baz` share `foo`.
  - `foo` and `.bar` do not produce a family.
  - matching is case-insensitive while display values are preserved.
- Unit tests for `AgentSiblingIndex`:
  - excludes current agent from siblings.
  - excludes dotless names.
  - excludes non-rendered STARTING rows.
  - respects collapsed groups by excluding hidden child agent rows.
  - preserves visible render order across panels.
- Cache test showing repeated sibling-count reads for unchanged state do not rebuild the visible-row walk.

Suggested files:

- `src/sase/ace/tui/models/agent_siblings.py`
- `src/sase/ace/tui/actions/agents/_display.py` or a small new `src/sase/ace/tui/actions/agents/_siblings.py`
- `src/sase/ace/tui/actions/agents/_core.py`
- `tests/ace/tui/models/test_agent_siblings.py`
- `tests/ace/tui/test_agent_sibling_index_cache.py`

## Phase 2: `~` Navigation And Modal

Owner: Agent instance 2.

Wire the key action for the Agents tab and add the chooser modal.

Deliverables:

- Extend `TreeNavigationMixin.action_start_sibling_mode()`:
  - existing CLs behavior remains unchanged.
  - Agents tab delegates to `_start_agent_sibling_navigation()`.
- Add `_start_agent_sibling_navigation()` and a helper that focuses an agent sibling by global index.
- Direct jump when the current agent has exactly one visible sibling.
- Open `AgentSiblingModal` when the current agent has more than one visible sibling.
- No-op when no selected agent row is focused, the selected agent has no sibling family, or no visible siblings exist.
- Respect the artifact-viewer navigation guard before changing rows.
- Preserve existing Agents-tab behavior when jumping:
  - clear `_current_group_key`.
  - move focused tag panel when the target is in another panel.
  - clear pinned attempt state.
  - acknowledge unread on the target and arm manual unread on departure using the same helpers as j/k navigation.
  - refresh the affected panel highlights and detail header without forcing a full list rebuild.

Tests:

- Pure action tests for no sibling, one sibling direct jump, and multiple siblings modal open.
- Cross-panel jump test: `~` moves focused panel and highlights the target row.
- Collapsed-group test: hidden sibling rows are not offered.
- Artifact-viewer guard test: `~` does not move selection while the artifact viewer is active.
- Modal tests for enter selection, `a-z` quick selection, `j/k`, and cancel.

Suggested files:

- `src/sase/ace/tui/actions/navigation/_tree.py`
- `src/sase/ace/tui/actions/agents/_siblings.py`
- `src/sase/ace/tui/actions/agents/_core.py`
- `src/sase/ace/tui/modals/agent_sibling_modal.py`
- `src/sase/ace/tui/modals/__init__.py`
- `src/sase/ace/tui/styles.tcss`
- `tests/ace/tui/test_agent_sibling_navigation.py`
- `tests/ace/tui/modals/test_agent_sibling_modal.py`

## Phase 3: Visual Affordances And Keymap Surfaces

Owner: Agent instance 3.

Surface the sibling count and make the key discoverable without adding a side panel.

Deliverables:

- Extend `AgentInfoPanel.update_state()` with `sibling_count`.
- Render `[siblings: N (~)]` when `N > 0`, using the active keymap registry for the displayed key.
- Keep countdown-only refresh cheap: sibling count belongs to the stable signature, so unchanged counts should still use
  the existing `update_countdown_only()` path.
- Pass sibling count from `_update_agents_info_panel_impl()` via the cached index.
- Add optional footer binding:
  - `~ sibling` for one visible sibling.
  - `~ siblings (N)` for multiple visible siblings.
- Update Agents help modal navigation section to list sibling jumping.
- Update command palette metadata so `start_sibling_mode` is scoped to CLs and Agents, while ancestor/child remain
  CL-only.

Tests:

- `AgentInfoPanel` rendering and style tests for no siblings, one sibling, and multiple siblings.
- Stable-state/countdown-only tests proving unchanged sibling count does not force a full info-panel update.
- Footer binding tests for sibling availability.
- Help/keymap tests proving `~` appears in Agents help and remains unchanged in CLs help.
- Command palette/catalog test for `start_sibling_mode` tab scope.

Suggested files:

- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `src/sase/ace/tui/actions/agents/_display_detail.py`
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`
- `src/sase/ace/tui/widgets/keybinding_footer.py`
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
- `src/sase/ace/tui/commands/catalog.py`
- `tests/ace/tui/widgets/test_agent_info_panel.py`
- `tests/test_keybinding_footer_agent.py`
- `tests/test_keymaps.py`

## Phase 4: Visual Snapshots, Performance Verification, And Polish

Owner: Agent instance 4.

Harden the feature and verify it does not regress TUI responsiveness.

Deliverables:

- Add or update PNG visual snapshot coverage:
  - Agents info-panel sibling badge.
  - Agent sibling modal with several sibling rows.
- Check narrow terminal behavior so modal rows truncate cleanly and no text overlaps.
- Run targeted unit/Pilot tests for phases 1-3.
- Run `just check` after implementation changes.
- Run the j/k bench where feasible:
  - `pytest -s -m slow tests/ace/tui/bench_tui_jk.py`
  - Compare Agents-tab p95 before/after if the bench environment is stable.
- If visual snapshots intentionally change, update goldens with `--sase-update-visual-snapshots` after inspecting
  actual/expected/diff artifacts.

Acceptance criteria:

- CLs tab `~` behavior is unchanged.
- Agents tab `~` direct-jumps with one visible sibling.
- Agents tab `~` opens the modal with two or more visible siblings.
- Selecting a modal row jumps to that exact agent row and panel.
- The selected-agent sibling count is visible in the Agents top bar.
- j/k selection remains responsive and does not rebuild sibling state per keystroke.
- The feature is covered by unit/action/modal tests and at least one visual snapshot.
