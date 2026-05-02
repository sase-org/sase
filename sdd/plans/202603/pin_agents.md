---
create_time: 2026-03-29 16:51:54
status: done
prompt: sdd/prompts/202603/pin_agents.md
---

# Plan: Pin Agents on the Agents Tab

## Summary

Add a `P` keymap to the Agents tab that toggles a "pinned" state on completed agents. Pinned agents are visually
distinct (pin icon + amber highlight) and are excluded from `X` (dismiss all). Pin state is persisted across TUI
sessions via a dedicated JSON file, following the same pattern as `dismissed_agents.json`.

## Design Decisions

### Visual Treatment

Pinned agents get a **pushpin icon** (`📌`) rendered in amber (`#FFD700`) immediately before the existing done icon
(`✘`). The done icon itself shifts from bold red to **dim** when pinned, signaling that the agent is "protected" from
dismissal. This creates a clear visual hierarchy:

```
📌 ✘ [agent] my_feature (DONE)     ← pinned: amber pin, dimmed ✘
   ✘ [agent] other_thing (DONE)    ← normal: red ✘, dismissable
```

The pin icon occupies the same visual layer as the approve (`⚡`) and hidden (`◌`) icons -- it is a status badge, not a
structural change. This approach is minimal, beautiful, and immediately understandable.

### Persistence

A new file `~/.sase/pinned_agents.json` stores a list of `[agent_type, cl_name, raw_suffix]` tuples, mirroring the
`dismissed_agents.json` format exactly. A new module `src/sase/ace/pinned_agents.py` provides `load_pinned_agents()` /
`save_pinned_agents()` / `toggle_pinned_agent()` functions.

### Pin Scope

- **Who can be pinned?** Any agent in a dismissable status (`DONE`, `FAILED`, `PLAN COMMITTED`, `PLAN DONE`). Pinning a
  running agent would be meaningless since running agents can't be dismissed.
- **Workflow parents:** Pinning a workflow parent implicitly protects all its child steps from dismiss-all. Child steps
  are not independently pinnable.
- **Unpin:** Pressing `P` again on a pinned agent removes the pin. The agent becomes dismissable again.

### Dismiss-All Interaction

`_dismiss_all_done_agents()` currently collects all agents with `status in DISMISSABLE_STATUSES`. With this change, it
filters out pinned agents. The confirmation modal count and description list reflect only the non-pinned agents. If all
dismissable agents are pinned, the user sees "No agents to dismiss".

### Footer & Help

- **Footer:** `P` appears conditionally when the selected agent is in a dismissable status, showing `P pin` or `P unpin`
  depending on current state.
- **Help modal:** Added to the "Agent Actions" section as `P  Pin / unpin agent`.

## Phases

### Phase 1: Persistence Layer

Create `src/sase/ace/pinned_agents.py` with:

- `_PINNED_AGENTS_FILE = Path.home() / ".sase" / "pinned_agents.json"`
- `load_pinned_agents() -> set[tuple[AgentType, str, str | None]]`
- `save_pinned_agents(pinned: set[...]) -> bool`
- `toggle_pinned_agent(pinned: set[...], identity: tuple[...]) -> bool` (returns new pin state)

Follow the exact patterns from `dismissed_agents.py` (same serialization, same error handling).

### Phase 2: Keymap Registration

1. **`default_config.yml`**: Add `pin_agent: "P"` under `ace.keymaps.app` in the "Agent / axe" section.
2. **`keymaps/types.py`**: Add `pin_agent: str` field to `AppKeymaps` dataclass and a corresponding entry in
   `_BINDING_META`.
3. These two changes are all that's needed -- the keymap loader and binding builder are generic.

### Phase 3: Action Handler

Add `action_pin_agent()` to the agent interaction mixin (`_interaction.py`):

- Gate on `current_tab == "agents"`.
- Get the currently selected agent. Validate it has a dismissable status and a `raw_suffix`.
- Call `toggle_pinned_agent()` to flip state.
- Persist to disk via `save_pinned_agents()`.
- Show a brief notification: "Pinned agent_name" or "Unpinned agent_name".
- Refresh the agent list display (the pin icon will appear/disappear).

### Phase 4: Dismiss-All Exclusion

In `_killing.py`, modify `_dismiss_all_done_agents()`:

- Filter out agents whose identity is in `self._pinned_agents`.
- If filtering removes all candidates, show "No agents to dismiss" (or "All completed agents are pinned").

### Phase 5: Visual Rendering

In `agent_list.py`, modify `_format_agent_option()`:

- Accept a `pinned_agents` set parameter (or check via a passed-in predicate).
- Before the done icon, if agent is pinned, append `📌 ` in `bold #FFD700`.
- Change the done icon style from `bold red` to `dim red` when pinned.

Also update `_calculate_entry_display_width()` to account for the pin icon width.

### Phase 6: TUI State Wiring

In `app.py`:

- Load `_pinned_agents` set in `__init__` (alongside `_dismissed_agents`).
- Thread the pinned set through to `AgentList.update_list()` and the rendering code.

### Phase 7: Footer & Help Updates

1. **`keybinding_footer.py`**: In `_compute_agent_bindings()`, add a conditional binding for `pin_agent` when the
   selected agent has a dismissable status. Label: "pin" or "unpin".
2. **`help_modal/bindings.py`**: Add `(d(a.pin_agent), "Pin / unpin agent")` to the "Agent Actions" section in
   `agents_bindings()`.

### Phase 8: Tests

Add tests for:

- `pinned_agents.py`: round-trip load/save, toggle behavior.
- Dismiss-all filtering: verify pinned agents are excluded.
- Pin toggle action: verify state changes correctly.
