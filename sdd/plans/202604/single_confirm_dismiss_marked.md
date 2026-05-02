---
create_time: 2026-04-23 16:30:05
status: done
prompt: sdd/prompts/202604/single_confirm_dismiss_marked.md
---

# Plan: Single-Confirmation Dismiss for Marked Agents When None Are Running

## Problem

In the `sase ace` TUI, marking agents with `m` and then pressing `x` always routes through `ConfirmKillAllModal`, which
requires pressing `y` **twice** (the second press is a "FINAL CONFIRMATION" guard against accidentally killing live
processes).

When none of the marked agents are running (i.e. every marked agent is already in a dismissable state like `DONE`,
`FAILED`, `PLAN COMMITTED`, `PLAN DONE`, or has no pid), the double confirmation is unnecessary friction — nothing is
actually being killed, just dismissed.

## Desired Behavior

Pressing `x` with marked agents should:

- **Show double confirmation** (`ConfirmKillAllModal`) **only if** at least one marked agent is still running (i.e.
  `killable` is non-empty).
- **Show single confirmation** (`ConfirmDismissAllModal`) **otherwise** — a single `y` press dismisses the marked
  agents.

This matches the existing single-agent `x` flow, where a running agent triggers a kill confirmation and a completed
agent is dismissed with no confirmation (or a lighter confirmation) — the bulk path just hadn't been differentiated.

## Implementation Approach

### Scope: one function, one file

All behavior changes live in `_bulk_kill_marked_agents()` inside `src/sase/ace/tui/actions/agents/_marking.py` (lines
83–150).

The split between `killable` and `dismissable` lists already exists at lines 98–107 — we just need to branch on whether
`killable` is empty when choosing which modal to push.

### Change in `_bulk_kill_marked_agents()`

1. **Import both modals** from `...modals`:
   - `ConfirmKillAllModal` (double confirmation) — already imported.
   - `ConfirmDismissAllModal` (single confirmation) — needs to be added.

2. **Adjust the description header text** when no killable agents exist, since the current description mixes "Kill: N
   running" and "Dismiss: N" lines. When nothing is killable, the description should read naturally as a dismiss-only
   operation (i.e. just the dismiss list, no "Kill:" section — which already happens naturally because the
   `if killable:` guard at line 110 already skips the kill section).

3. **Branch on `killable`**:
   - If `killable` is non-empty → `push_screen(ConfirmKillAllModal(...), on_dismiss)` (current behavior).
   - If `killable` is empty → `push_screen(ConfirmDismissAllModal(...), on_dismiss)` (new behavior).

4. **Leave `on_dismiss` unchanged.** The callback already handles both `killable` and `dismissable` lists correctly; it
   just iterates the appropriate list and calls `_do_kill_agent` / `_do_dismiss_all`. When `killable` is empty, the
   `for agent in list(killable):` loop is a no-op, which is exactly what we want.

### No changes to the modals themselves

Both `ConfirmDismissAllModal` and `ConfirmKillAllModal` already exist in `src/sase/ace/tui/modals/confirm_kill_modal.py`
with the correct semantics:

- `ConfirmDismissAllModal` — single `y` press → `dismiss(True)`.
- `ConfirmKillAllModal` — two `y` presses with "FINAL CONFIRMATION" state between.

### No changes to the `x` keymap dispatch

`action_kill_agent()` in `_kill_pin.py` already correctly routes to `_bulk_kill_marked_agents()` when `_marked_agents`
is non-empty, and to the single-agent kill flow otherwise. That entry point is unchanged.

## Files to Modify

| File                                          | Purpose                                                                           |
| --------------------------------------------- | --------------------------------------------------------------------------------- |
| `src/sase/ace/tui/actions/agents/_marking.py` | Add `ConfirmDismissAllModal` import; branch modal choice on `killable` emptiness. |

## Files Touched for Verification Only (No Edits)

- `src/sase/ace/tui/modals/confirm_kill_modal.py` — confirm both modals exist and behave as expected.
- `src/sase/ace/tui/actions/agents/_kill_pin.py` — confirm `_bulk_kill_marked_agents` is still the single entry point
  and doesn't need tweaks.
- `src/sase/ace/tui/actions/agents/_core.py` — confirm `DISMISSABLE_STATUSES` is the correct "not running" signal.

## Testing

1. **Manual: no running marked agents.** Mark two `DONE` / `FAILED` agents, press `x`. Expect a single-confirmation
   modal ("Confirm Dismiss All"). Press `y` once; both agents disappear.

2. **Manual: one running + one done.** Mark one `RUNNING` and one `DONE` agent, press `x`. Expect the existing
   double-confirmation modal ("Confirm Kill & Dismiss All" → "FINAL CONFIRMATION"). Press `y` twice; running agent
   killed, done agent dismissed.

3. **Manual: all running.** Mark only running agents, press `x`. Expect double confirmation.

4. **Edge: no-op path.** If all marked identities have been cascaded away before the modal fires, the existing
   `if not marked_agents` early return still triggers.

5. **Regression check.** Run `just check` in the workspace directory.

## Risks / Non-Goals

- **Non-goal:** changing single-agent `x` behavior or the help modal. Only the bulk (marked) path changes.
- **Risk:** user muscle memory that assumes "`x` on marks always needs two `y`s". Acceptable — the new behavior is
  strictly less friction and only for the safe case.
- **Risk:** an agent transitions from `RUNNING` to `DONE` between the modal opening and `on_dismiss` firing. This is
  already tolerated today (the callback re-checks `live_ids` and routes via `_do_kill_agent` / `_do_dismiss_all` which
  themselves handle state transitions). No new race introduced.
