---
create_time: 2026-04-07 23:03:10
status: done
prompt: sdd/prompts/202604/agents_move_keymaps.md
---

# Plan: `J`/`K` Move Agent Entries on the Agents Tab

## Context

The `sase ace` TUI Agents tab displays a list of agents/workflows sorted by start time (most recent first), with
workflow children interleaved after their parents. Currently `j`/`k` navigate the selection cursor up/down. The user
wants `J` (shift+j) and `K` (shift+k) to **move the selected agent entry** down/up in the list, reordering it relative
to its siblings.

### Current Architecture

- **Agent loading**: `_load_agents()` in `_loading.py` calls `load_all_agents()` → `_sort_and_reorder()` which produces
  a time-sorted list. Every periodic refresh rebuilds this list from scratch.
- **Panel split**: After loading, `_build_panel_indices()` splits agents into main and pinned panels. Navigation
  operates on panel-local indices.
- **Persistence**: Pinned agents and dismissed agents are persisted to JSON files under `~/.sase/`. No custom ordering
  exists yet.
- **Keymap system**: All app-level actions are declared in `AppKeymaps` dataclass, registered in `_BINDING_META`, and
  configured in `default_config.yml`. The key `J` (uppercase) maps to Textual key name `"J"`.
- **Existing `J`/`K` usage**: `J` is used inside the vim-normal text widget (unrelated). `K` is used in task_queue and
  mentor_review modals (not app-level). Neither is bound at the app level, so they're available.

### Key Design Decision: How to Persist Custom Order

When `_load_agents()` refreshes, it rebuilds the list from disk artifacts sorted by time. Without persistence, any
manual reordering would be lost on every refresh cycle (default 10s). The approach:

1. Maintain an in-memory `_agent_custom_order: list[tuple[AgentType, str, str | None]]` (list of agent identities in
   user's desired order).
2. Persist this to `~/.sase/agent_order.json` (same pattern as `pinned_agents.json`).
3. After `_sort_and_reorder()` produces the default time-sorted list, apply the custom order: agents whose identity
   appears in the custom order list get placed at their specified positions; new agents (not in the custom order) are
   inserted at the top (most recent first, as today).
4. When the user presses `J`/`K`, swap the selected agent's position in the custom order list and persist.

### Scope of Move

- `J` moves the selected entry **down** (toward higher index / lower on screen).
- `K` moves the selected entry **up** (toward lower index / higher on screen).
- Move operates within the **focused panel** only (main or pinned), consistent with how `j`/`k` navigation works.
- Workflow children should move with their parent (moving a parent moves its entire group). Moving a child within its
  parent's group reorders just the child among siblings — but this adds complexity. For the initial implementation,
  **only top-level agents (non-children) can be moved**. Pressing `J`/`K` on a workflow child is a no-op.

## Phases

### Phase 1: Keymap Wiring

Add two new app-level actions: `move_agent_down` and `move_agent_up`.

**Files to modify:**

1. `src/sase/default_config.yml` — Add entries under `ace.keymaps.app`:

   ```yaml
   move_agent_down: "J"
   move_agent_up: "K"
   ```

2. `src/sase/ace/tui/keymaps/types.py` — Add fields to `AppKeymaps` dataclass and entries to `_BINDING_META`:

   ```python
   # In AppKeymaps:
   move_agent_down: str
   move_agent_up: str

   # In _BINDING_META:
   ("move_agent_down", "Move Down", False),
   ("move_agent_up", "Move Up", False),
   ```

### Phase 2: Custom Order Persistence

Create a new module `src/sase/ace/agent_order.py` following the same pattern as `pinned_agents.py`:

- `_AGENT_ORDER_FILE = Path.home() / ".sase" / "agent_order.json"`
- `load_agent_order() -> list[tuple[AgentType, str, str | None]]` — Load from disk.
- `save_agent_order(order) -> bool` — Persist to disk.

### Phase 3: Apply Custom Order During Agent Loading

In `_loading.py`'s `_load_agents()`, after the existing sort/filter pipeline produces `self._agents`, apply the custom
order:

- Add `_agent_custom_order` attribute to the mixin type declarations.
- After `self._agents` is finalized (post-filter, post-fold), reorder top-level agents according to
  `_agent_custom_order` while keeping workflow children grouped after their parents.
- Initialize `_agent_custom_order` in `app.py` alongside `_pinned_agents`.

### Phase 4: Move Action Implementation

Create the action methods, likely in a new mixin or added to `AgentsMixinCore`:

- `action_move_agent_down()` / `action_move_agent_up()`:
  1. Guard: return early if `current_tab != "agents"`.
  2. Guard: return early if selected agent is a workflow child.
  3. Get the focused panel's indices.
  4. Find the selected agent's position among top-level entries in the panel.
  5. Compute the swap target (next/previous top-level entry in the panel).
  6. Swap the two entries in `_agent_custom_order`.
  7. Persist with `save_agent_order()`.
  8. Rebuild `self._agents` ordering and panel indices in-place (without a full reload from disk).
  9. Update `current_idx` to follow the moved agent.
  10. Call `_refresh_agents_display(list_changed=True)`.

### Phase 5: Footer and Help Modal Updates

1. **Footer** (`keybinding_footer.py`): Add `J`/`K` move bindings to `_compute_agent_bindings()`. These are conditional
   (only shown when a moveable agent is selected), so they belong in the footer per the convention.

2. **Help modal** (`help_modal.py`): Add `J`/`K` move entries to the Agents tab section.
