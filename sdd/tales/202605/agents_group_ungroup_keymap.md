---
create_time: 2026-05-06 19:49:02
status: done
prompt: sdd/prompts/202605/agents_group_ungroup_keymap.md
---
# Plan: Agents Tab `,g` Group/Ungroup Toggle

## Goal

Add a leader keymap `,g` on the `sase ace` Agents tab that toggles between:

1. The current tag-split panel layout, where dynamic agent panels are separated by effective tag and agent rows do not
   show tag labels.
2. A merged layout, where every visible agent is rendered in one panel, using the active Agents-tab grouping mode
   (`STANDARD`, `BY_DATE`, or `BY_STATUS`) as if the agents had always belonged to one panel, and tagged rows show their
   effective tag label.

Pressing `,g` again returns to the tag-split layout and removes those row tag labels.

## Current Architecture

- Tags currently drive dynamic side panels through `src/sase/ace/tui/models/agent_panels.py`.
- `AgentPanelGroup.from_agents()` derives panel keys from effective tags, with workflow children inheriting the parent
  tag.
- `AgentPanelIndex` precomputes panel slices and global/local index maps from `panel_key_per_agent()`.
- Each `AgentList.update_list()` receives one panel slice and runs `build_agent_tree()` on that slice, so
  grouping/sorting is currently per panel.
- The grouping mode itself is app state in `AgentGroupingMixin`, with mode-specific fold registries.
- The comma prefix is already leader mode. Leader subkeys live in `LeaderModeKeymaps`, `default_config.yml`,
  `LeaderModeMixin._handle_leader_key()`, help modal bindings, footer bindings, and command palette leader-command
  metadata.

## Design

### 1. Add Explicit Panel Merge State

Add an Agents-tab state flag, likely `self._agent_panels_grouped: bool`, initialized to `False` in `_init_app_state`.

When true:

- `AgentPanelGroup.from_agents(..., merge_tag_panels=True)` should return a single panel, preserving an in-bounds focus
  index.
- `build_agent_panel_index(..., merge_tag_panels=True)` should assign every visible agent to the single panel.
- `agents_for_panel(..., merge_tag_panels=True)` and navigation helpers should see the full agent list for that one
  panel.

Avoid using a magic string panel key like `"all"` because user tag names are arbitrary. A boolean merge mode keeps
`PanelKey` semantics unchanged.

### 2. Preserve Effective Tag Information Separately

Keep the existing effective tag calculation for display annotations even when panel keys are merged.

Add a helper such as `effective_tag_per_agent(agents)` that returns the current tag bucket each agent would have had in
split mode, including workflow-child inheritance. In merged mode, pass these effective labels to the row renderer so
tagged entries are visible as tagged.

Do not mutate `Agent.tag` for display. The toggle is view state only.

### 3. Render Tag Labels Only In Merged Mode

Extend the `AgentList` row rendering path to accept optional tag labels aligned to its local `agents` list:

- `AgentList.update_list(..., tag_labels=None)`
- `build_list(..., tag_labels=None)`
- `format_agent_option(..., tag_label=None)`
- include `tag_label` in `agent_render_key()`

When `tag_label` is present, render a concise tag badge in the row near the name, styled distinctly from the existing
`@agent_name` annotation. When `tag_label` is absent, row output should remain byte-for-byte equivalent to the current
split-panel view.

### 4. Refresh Panels Through Existing Rebuild Path

Add an action, for example `action_toggle_agent_panel_grouping()`, available only on the Agents tab.

On toggle:

- Flip `_agent_panels_grouped`.
- Clear `_current_group_key` because banner focus keys can become ambiguous across a different tree.
- Clear `current_attempt_number`.
- Invalidate panel/nav caches via `_invalidate_agent_panel_cache()`.
- Rebuild via `_refresh_agents_display(list_changed=True)`.
- Notify with a short state label, e.g. `Agent panels: grouped` / `Agent panels: split`.

When moving back to split mode, `_sync_panel_group()` should rebuild the normal tag panel set and snap focus into a
valid panel.

### 5. Keep Navigation And Bulk Actions Consistent

Audit the panel-aware helpers that currently call `agents_for_panel()` directly:

- `_agents_visible_order()`
- `_panel_navigation_stops()`
- `_first_agent_idx_for_focused_group()`
- `_agents_in_focused_panel()`
- jump-hint panel enumeration in navigation advanced helpers
- event handler row resolution
- panel-scoped kill/dismiss helpers

Thread the merge flag into those paths so grouped mode naturally scopes actions to the single merged panel. In split
mode behavior should remain unchanged.

### 6. Keymap And UI Wiring

Add the leader key:

- `default_config.yml`: `ace.keymaps.modes.leader_mode.keys.toggle_agent_panel_grouping: "g"`
- `LeaderModeKeymaps` defaults
- `LeaderModeMixin._handle_leader_key()` dispatch for Agents tab
- `KeybindingFooter.update_leader_bindings()` on Agents tab
- `help_modal.bindings.agents_bindings()` under the Agents leader section
- command palette leader metadata: label and tab scope (`_AGENTS_ONLY`)

No app-level direct key is needed because the requested binding is `,g`, not bare `g`.

### 7. Tests

Add focused unit coverage before broad TUI tests:

- `agent_panels` tests for merged mode: one panel, all per-agent panel keys merged, workflow-child effective tag still
  available.
- `agent_panel_index` tests for merged mode: one slice containing all agents and correct global/local maps.
- row rendering tests: tag badge appears only when `tag_label` is passed and cache key changes when it changes.
- display/panel test: merged mode produces one panel and passes full agent list plus tag labels.
- grouping model/widget test: merged mode groups/sorts across formerly separate tag panels using the active grouping
  mode.
- leader key tests: default `,g` exists, help/footer/palette surface it, and `_handle_leader_key("g")` toggles only on
  Agents tab.
- navigation or panel-scoped action tests to confirm grouped mode treats all visible agents as the focused panel.

Run the narrow tests first, then `just install` if needed, then `just check` before final response because this repo
requires it after source changes.

## Risks And Mitigations

- **Panel key collision:** Avoid magic tag-like sentinel keys; use explicit merge state.
- **Stale row cache:** Include tag label in render cache keys.
- **Unexpected persistent tag changes:** Keep grouped labels as render-only data.
- **Navigation drift:** Reset banner focus and invalidate caches on toggle.
- **Bulk action scope surprises:** In grouped mode, “focused panel” intentionally means all visible agents; in split
  mode it remains the active tag panel.
