---
create_time: 2026-04-09 19:12:32
status: done
prompt: sdd/prompts/202604/kill_dismiss_all.md
---

# Plan: `,X` Kill/Dismiss All Agents Keymap

## Overview

Add a new `,X` (leader mode + shift-X) keymap on the Agents tab that kills **all** running agents AND dismisses all
dismissable agents — a "nuclear option" compared to the existing `X` which only dismisses completed agents. Requires
double-confirmation (two `y` presses) with a visual state change between confirmations.

## UX Design

### Behavior

- `,X` on the Agents tab collects two groups:
  1. **Killable agents**: have a PID, status NOT in DISMISSABLE_STATUSES, not pinned
  2. **Dismissable agents**: status in DISMISSABLE_STATUSES, not pinned
- Shows a confirmation modal listing both groups with counts
- First `y` press: modal changes colors (border goes red, title changes to "FINAL CONFIRMATION") and updates message to
  warn this is irreversible
- Second `y` press: performs the kill+dismiss action
- `n`, `escape`, or `q` at any point cancels

### Double Confirmation Modal

- **Phase 1** (initial): Standard modal appearance (primary border), title "Confirm Kill & Dismiss All", message lists
  agent counts and names, "Yes (y)" button in error variant
- **Phase 2** (after first `y`): Border changes to red/error, title changes to "⚠ FINAL CONFIRMATION", message changes
  to emphasize irreversibility ("This will KILL N running agents and dismiss M completed agents. Press y again to
  confirm."), button text changes to "Confirm (y)"

## Implementation

### Phase 1: Config & Registry (2 files)

**`src/sase/default_config.yml`** — Add `kill_all: "X"` to leader_mode keys.

**`src/sase/ace/tui/keymaps/types.py`** — Add `"kill_all": "X"` to `LeaderModeKeymaps` default dict.

### Phase 2: Double-Confirmation Modal (3 files)

**`src/sase/ace/tui/modals/confirm_kill_modal.py`** — Add `ConfirmKillAllModal(ModalScreen[bool])`:

- Constructor takes `agent_description: str`
- Internal `_confirmed_once: bool = False` state
- On first `y`: set `_confirmed_once = True`, update border to red, change title label text, change message label text,
  change button text
- On second `y`: `self.dismiss(True)`
- Cancel always: `self.dismiss(False)`

**`src/sase/ace/tui/styles.tcss`** — Add CSS for `ConfirmKillAllModal` (same base styles as existing confirm modals).
Add a `.confirmed-once` class variant that sets border to `thick $error` for the color change.

**`src/sase/ace/tui/modals/__init__.py`** — Export `ConfirmKillAllModal`.

### Phase 3: Kill+Dismiss Action (1 file)

**`src/sase/ace/tui/actions/agents/_killing.py`** — Add `_kill_and_dismiss_all_agents()`:

- Collect killable agents (have PID, not dismissable status, not pinned)
- Collect dismissable agents (DISMISSABLE_STATUSES, not pinned)
- If neither list has entries, show "No agents to kill or dismiss" warning
- Build description showing both groups
- Push `ConfirmKillAllModal`
- On final confirmation: kill each killable agent via `_do_kill_agent()`, then dismiss batch via `_do_dismiss_all()`

### Phase 4: Leader Mode Dispatch (1 file)

**`src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`** — Add handler for `kill_all` key in
`_handle_leader_key()`:

- Only active on agents tab
- Calls `self._kill_and_dismiss_all_agents()`

### Phase 5: Footer & Help (2 files)

**`src/sase/ace/tui/widgets/keybinding_footer.py`** — In `update_leader_bindings()`, add `,X` binding when on agents tab
(show "kill & dismiss all" or similar with count).

**`src/sase/ace/tui/modals/help_modal/bindings.py`** — Add `,X` entry to agents tab leader mode section: "Kill & dismiss
all agents".
