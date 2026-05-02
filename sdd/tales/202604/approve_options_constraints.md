---
create_time: 2026-04-01 10:20:19
status: done
prompt: sdd/prompts/202604/approve_options_constraints.md
---

# Plan: ApproveOptionsModal — Enforce Valid Option Combinations

## Problem

The ApproveOptionsModal allows all four combinations of {commit_plan, run_coder}, including both-OFF which is
meaningless. The user wants the invariant **at least one must be ON** enforced in the UI.

## Valid States

| State          | Commit plan    | Run coder      | Prompt area | Notes                     |
| -------------- | -------------- | -------------- | ----------- | ------------------------- |
| Both ON (dflt) | ON, unlocked   | ON, unlocked   | Enabled     | Full options              |
| Commit only    | ON, **locked** | OFF, unlocked  | Disabled    | Coder OFF → commit locked |
| Coder only     | OFF, unlocked  | ON, **locked** | Enabled     | Commit OFF → coder locked |

## Design

### Locking Mechanism

When a switch is toggled OFF, the _other_ switch is set to `disabled=True`, which:

- Grays it out (Textual built-in)
- Prevents toggling (space/click ignored)
- Skips during focus navigation (Tab, ctrl+n, ctrl+p)

When the switch is toggled back ON, the other is re-enabled.

### Visual Treatment

- Locked switch labels get a `.locked` CSS class → `$text-disabled` color
- Label text updates to append " (required)" when locked, making the constraint self-explanatory
- Prompt area disabling (already implemented) stays as-is

### Implementation

Single `_sync_constraints()` method replaces current `on_switch_changed` logic. Called on every switch change, it reads
both switch values and enforces the invariant declaratively.

Labels get IDs (`commit-plan-label`, `run-coder-label`) for reliable querying.

## Files to Change

| File                                               | Change                                                                 |
| -------------------------------------------------- | ---------------------------------------------------------------------- |
| `src/sase/ace/tui/modals/approve_options_modal.py` | Add `_sync_constraints()`, refactor `on_switch_changed`, add label IDs |
| `src/sase/ace/tui/styles.tcss`                     | Add `.approve-options-label.locked` style                              |
| `tests/test_approve_options_modal.py`              | Add constraint enforcement tests                                       |
