---
create_time: 2026-03-28 18:22:12
status: done
prompt: sdd/prompts/202603/remove_agents_m_keymap.md
---

# Plan: Remove `m` (message) keymap from Agents tab

## Context

The `m` key is bound to `toggle_mark`, which does double duty: on the CLs tab it toggles mark on a ChangeSpec, and on
the Agents tab it sends an interrupt message to a running agent. The goal is to remove only the Agents tab "message"
behavior and all supporting code, while keeping the CLs tab "mark" behavior intact.

## Changes

### 1. Remove the Agents-tab branch from `action_toggle_mark`

**File**: `src/sase/ace/tui/actions/marking.py`

Remove the `if self.current_tab == "agents"` branch (lines 28-30) that delegates to `action_send_agent_message()`.
Update the docstring accordingly.

### 2. Delete `_interrupt.py` (AgentInterruptMixin)

**File**: `src/sase/ace/tui/actions/agents/_interrupt.py`

This entire file exists solely to implement `action_send_agent_message()` and `_write_interrupt_request()`. Delete it.

### 3. Remove AgentInterruptMixin from the core mixin chain

**File**: `src/sase/ace/tui/actions/agents/_core.py`

- Remove `from ._interrupt import AgentInterruptMixin`
- Remove `AgentInterruptMixin` from the `AgentsMixinCore` base class list

### 4. Delete `agent_interrupt_modal.py` (AgentInterruptModal)

**File**: `src/sase/ace/tui/modals/agent_interrupt_modal.py`

The modal is only used by the interrupt action. Delete it.

### 5. Remove AgentInterruptModal from modals `__init__.py`

**File**: `src/sase/ace/tui/modals/__init__.py`

- Remove the `from .agent_interrupt_modal import AgentInterruptModal` import
- Remove `"AgentInterruptModal"` from the `__all__` list

### 6. Remove the "message" footer binding from the keybinding footer

**File**: `src/sase/ace/tui/widgets/keybinding_footer.py`

Remove the entire block (lines 450-459) that conditionally appends the `toggle_mark` → "message" binding for
interruptable agents.

### 7. Remove the help modal entry for "Send message to running agent"

**File**: `src/sase/ace/tui/modals/help_modal/bindings.py`

Remove the line `(d(a.toggle_mark), "Send message to running agent")` from the "Agent Actions" section.

## Validation

Run `just install && just check` to verify lint, types, and tests pass.
