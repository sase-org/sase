---
create_time: 2026-03-25 16:24:18
status: done
prompt: sdd/prompts/202603/tui_commit_keybinding.md
---

# Plan: Add `c` (commit) keybinding to TUI plan approval modal

## Problem

The `sase ace` TUI's plan approval modal supports `a` (approve), `r` (reject), `f` (feedback), `e` (edit), and `E`
(epic) — but not `c` (commit). The backend already handles the "commit" action (commits SDD files without spawning a
coder agent), and the Telegram bot already has a Commit button. The TUI is the missing piece.

## Changes

### File 1: `src/sase/ace/tui/modals/plan_approval_modal.py`

1. Update `PlanApprovalResult` docstring: `"approve", "reject", or "epic"` → `"approve", "reject", "commit", or "epic"`
2. Add binding `("c", "commit", "Commit")` to `BINDINGS` (after approve, before reject)
3. Add `[green]c[/green]=Commit` to the hints string (after Approve)
4. Add `action_commit()` method following the same pattern as `action_approve`/`action_epic`:
   ```python
   def action_commit(self) -> None:
       """Commit the plan without running a coder agent."""
       if self._feedback_mode:
           return
       self.dismiss(PlanApprovalResult(action="commit"))
   ```

### File 2: `src/sase/ace/tui/actions/agents/_notification_actions.py`

In `handle_plan_approval()` → `on_dismiss()`:

1. Extend the plan-save block (line 570) from `if result.action == "approve"` to
   `if result.action in ("approve", "commit")` — commit should also save the plan to `.sase/plans/`.
2. Add `elif result.action == "commit":` to the status override block (after the epic branch, line 618):
   ```python
   elif result.action == "commit":
       app._agent_status_overrides[agent.identity] = "PLAN COMMITTED"
       persist_plan_approved(agent)
   ```

### No other files need changes

- `_plan_utils.py` line 185 already accepts "commit" in `("approve", "epic", "commit")`
- `run_agent_exec.py` line 415 already handles `plan_result.action == "commit"`
- No test files need updating (no modal-specific unit tests exist for plan approval actions)

## Verification

- `just check` passes (fmt, lint, tests)
- Manual: `sase ace --agent` with a plan approval notification, press `c` → confirms commit action
