---
create_time: 2026-03-31 21:43:53
status: done
---

# Plan: Approve with Options Modal

## Problem

The plan notification panel currently has a `c` (commit) keybinding that commits the plan without running a coder agent.
This is a rigid binary: either approve (runs coder) or commit (no coder). Users need finer-grained control over what
happens after plan approval — whether to commit SDD files, whether to spawn a coder agent, and what additional
instructions to give the coder.

## Design

Replace `c` with a new `A` (approve w/ options) keybinding. Pressing `A` pushes a form modal **on top of** the plan
panel (so `q`/Escape goes back to the plan). The modal has three controls:

### Modal Layout

```
╔══════════════════════════════════════════════════════╗
║              Approve with Options                    ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║    Commit plan              ━━━━━━━━━━━━━━━━━━━●     ║
║    Run coder agent          ━━━━━━━━━━━━━━━━━━━●     ║
║                                                      ║
║    Additional prompt:                                ║
║    ┌────────────────────────────────────────────────┐║
║    │ e.g. #review+  (supports xprompts)             │║
║    └────────────────────────────────────────────────┘║
║                                                      ║
╠══════════════════════════════════════════════════════╣
║  enter=Approve  space=Toggle  tab=Next  q=Back       ║
╚══════════════════════════════════════════════════════╝
```

- **Commit plan** (Switch, default: on) — Whether to commit SDD files to the project repo (or `.sase/sdd/` if
  `sdd.version_controlled` is not set).
- **Run coder agent** (Switch, default: on) — Whether to spawn a follow-up coder agent.
- **Additional prompt** (Input, default: empty) — Extra text appended to the coder prompt. Supports xprompt references
  (e.g. `#review+`). Visually disabled when "Run coder agent" is off.

### Navigation & Interaction

- **Tab / Shift+Tab**: Cycle focus between Switch → Switch → Input.
- **Space**: Toggle the focused Switch.
- **Enter**: Approve with current options (from any widget).
- **Escape / q**: Dismiss modal, return to plan panel.
- When "Run coder agent" is toggled off, the Input is disabled and dimmed.

### Data Flow

1. **TUI modal** → `PlanApprovalResult` gains three new optional fields: `commit_plan`, `run_coder`, `coder_prompt`.
2. **`_notification_modals.py`** → Writes these fields into `plan_response.json`.
3. **`_plan_utils.py`** (agent-side) → `PlanApprovalResult` gains matching fields; polling code reads them from JSON.
4. **`run_agent_exec_plan.py`** → Uses fields to control:
   - `commit_plan=False` → Skip SDD git commit (files still written to disk).
   - `run_coder=False` → Return `"plan_committed"` instead of spawning coder.
   - `coder_prompt` → Appended to coder agent prompt before `embedded_refs`.

### Behavioral Matrix

| commit_plan | run_coder | Behavior                                     |
| ----------- | --------- | -------------------------------------------- |
| ✓           | ✓         | Write SDD + commit + spawn coder (= old `a`) |
| ✓           | ✗         | Write SDD + commit + return (= old `c`)      |
| ✗           | ✓         | Write SDD (no commit) + spawn coder          |
| ✗           | ✗         | Write SDD (no commit) + return               |

The old `a` (approve) keybinding is kept as-is for quick approval with defaults.

## Changes

### Phase 1: New Modal

**New file: `src/sase/ace/tui/modals/approve_options_modal.py`**

- `ApproveOptionsResult` dataclass: `commit_plan: bool`, `run_coder: bool`, `coder_prompt: str | None`.
- `ApproveOptionsModal(ModalScreen[ApproveOptionsResult | None])`: Form with two `Switch` widgets, one `Input`, footer
  hints. Uses Textual's built-in focus system (Tab/Shift+Tab). Listens for `Switch.Changed` to disable/enable the Input
  when "Run coder" toggles. Enter from any widget calls `_do_approve()`.

**Modify: `src/sase/ace/tui/modals/__init__.py`**

- Export `ApproveOptionsModal` and `ApproveOptionsResult`.

**Modify: `src/sase/ace/tui/styles.tcss`**

- Add CSS rules for `ApproveOptionsModal` and its container/widgets (centered, `width: 70`, border, padding).

### Phase 2: Plan Approval Modal Integration

**Modify: `src/sase/ace/tui/modals/plan_approval_modal.py`**

- Remove `c` binding and `action_commit()`.
- Add `A` binding → `action_approve_options()`.
- `action_approve_options()` pushes `ApproveOptionsModal` via `self.app.push_screen()`. On dismiss callback: if result
  is not None, dismiss self with
  `PlanApprovalResult(action="approve", commit_plan=..., run_coder=..., coder_prompt=...)`.
- Add `commit_plan`, `run_coder`, `coder_prompt` fields to `PlanApprovalResult` dataclass.
- Update footer hints: replace `c=Commit` with `A=Options`.

### Phase 3: Response Handler

**Modify: `src/sase/ace/tui/actions/agents/_notification_modals.py`**

- In `on_dismiss()`: when writing `plan_response.json`, include `commit_plan`, `run_coder`, and `coder_prompt` fields
  from the result.
- Remove the `result.action == "commit"` status override branch (now handled by `run_coder=False`).
- The status override becomes: `"PLAN APPROVED"` if `run_coder`, else `"PLAN COMMITTED"`.

### Phase 4: Agent-Side Consumption

**Modify: `src/sase/llm_provider/_plan_utils.py`**

- Add `commit_plan: bool = True`, `run_coder: bool = True`, `coder_prompt: str | None = None` to `PlanApprovalResult`.
- In `handle_plan_approval()`: read `commit_plan`, `run_coder`, `coder_prompt` from `response_data` when constructing
  the result. Map old `"commit"` action to `action="approve", run_coder=False` for backward compat.

**Modify: `src/sase/axe/run_agent_exec_plan.py`**

- Replace `if plan_result.action == "commit"` with `if not plan_result.run_coder` — same logic (commit SDD if
  `commit_plan`, return `"plan_committed"`).
- Gate SDD commit calls on `plan_result.commit_plan`.
- In the coder prompt construction: if `plan_result.coder_prompt` is set, append it after the "Implement it now." line
  (before `embedded_refs`).
