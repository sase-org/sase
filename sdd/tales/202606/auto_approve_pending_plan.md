---
create_time: 2026-06-27 14:42:04
status: done
prompt: sdd/prompts/202606/auto_approve_pending_plan.md
---
# Fix: `%auto` set via the `A` keymap does not auto-approve an already-pending plan

## Problem statement

On the **Agents** tab of `sase ace`, pressing `A` opens the Auto-Approve menu. Choosing `plan` / `tale` / `epic` is
meant to turn on `%auto` for the selected agent. The user reports that doing this "doesn't auto-approve the plan
properly."

After tracing the full flow, the report is **correct for one specific (and very common) case**: when the agent is
**already paused at the plan-approval gate** (status `PLAN`, i.e. a plan has been proposed and is waiting for review).
In that case pressing `A` and selecting a mode is effectively a no-op — the pending plan stays pending.

This matters because `PLAN` status is exactly the moment a user naturally reaches for `A`: the agent is sitting in the
"Stopped" bucket asking for action on the plan it just produced.

## Root cause

There are two cooperating pieces, and the gap is between them.

### 1. The TUI side correctly persists the config

Pressing `A` routes through:

- `action_accept_proposal` (`src/sase/ace/tui/actions/proposal_rebase.py`) → on the agents tab, for an approve-eligible
  status (which includes `PLAN`), calls `action_open_auto_approve_menu`.
- `action_open_auto_approve_menu` / `_apply_auto_approve_choice` (`src/sase/ace/tui/actions/agents/_approve.py`) →
  persists the choice via `persist_agent_directive_update`:
  - writes `approve: true` (for `plan`) or `auto_approve_plan_action: "tale"|"epic"` into the agent's `agent_meta.json`,
    and
  - inserts the canonical `%auto` directive into the prompt files (`raw_xprompt.md`, `submitted_xprompt.md`, history,
    stash) via `set_prompt_auto_mode`.

This part works. After pressing `A`, `agent_meta.json` does contain the auto-approve flag.

### 2. The runtime reads the auto-approve flag only ONCE, before it starts waiting

When an agent finishes planning, `handle_plan_approval()` in `src/sase/llm_provider/_plan_utils.py` runs:

```python
auto_action = get_auto_plan_approval_action()   # checked exactly once, up front
if auto_action is not None:
    ...
    return PlanApprovalResult(action=auto_action, plan_file=plan_file)

# ...otherwise create the notification (status -> PLAN) and poll:
while True:
    if killed_check is not None and killed_check():
        return None
    if response_path.exists():
        ...        # only a plan_response.json from the approval modal unblocks this
    time.sleep(_POLL_INTERVAL)
```

`get_auto_plan_approval_action()` (`src/sase/main/plan_approve_handler.py`) reads `agent_meta.json` fresh from disk, so
the value is _not_ cached. The problem is purely **timing**: it is consulted a single time, before the poll loop begins.
The poll loop then waits only for `plan_response.json` (written by the manual approval modal) or a kill. It never
re-reads `agent_meta.json`.

So the sequence that fails is:

1. Agent launched **without** `%auto`. It produces a plan.
2. `handle_plan_approval()` calls `get_auto_plan_approval_action()` → `None` → it creates the plan-approval
   notification, the agent shows `PLAN`, and it enters the poll loop.
3. User presses `A`, selects `plan`. `agent_meta.json` now has `approve: true`.
4. The blocked agent process keeps polling for `plan_response.json`. It never looks at `agent_meta.json` again. The
   pending plan is never auto-approved.

This is consistent with the _documented_ design — the Auto-Approve menu's docstring
(`src/sase/ace/tui/modals/auto_approve_modal.py`) says it "configures _future_ plan auto-approval" and points users to
the separate `PlanApprovalModal` (Enter / leader `n`) for an already-submitted plan. But for a plan-handoff agent there
are no "future" plans: it proposes exactly one plan and hands off. So on a `PLAN`-status agent the menu currently does
nothing useful, which is precisely the surprising behavior the user hit.

### What is NOT broken (scope clarification)

Setting `%auto` via `A` **before** the agent reaches the plan gate (i.e. while it is `RUNNING`) works correctly: when
the agent later proposes a plan, the up-front `get_auto_plan_approval_action()` reads the freshly-written
`agent_meta.json` and auto-approves. Verified end-to-end:

- A fresh agent launched without `%auto` has no `SASE_AGENT_AUTO_APPROVE` env var (`src/sase/axe/run_agent_runner.py`
  only exports it when `info.approve`, i.e. `auto_mode == "plan"` at launch — `run_agent_directives.py:314`), so the
  later `agent_meta.json` update is authoritative and honored.

The defect is specifically the **already-pending** case.

## Fix

Make the plan-approval wait loop honor an auto-approve flag that is enabled **while a plan is already pending**, so
`%auto` behaves uniformly regardless of when it is set (via the `A` key, a prompt edit in Neovim, or any external
tooling that writes `agent_meta.json`).

### Primary change — re-check auto-approve inside the poll loop

In `handle_plan_approval()` (`src/sase/llm_provider/_plan_utils.py`), re-evaluate `get_auto_plan_approval_action()` on
each poll iteration. When it transitions from `None` to a real action while waiting, treat the pending plan as
auto-approved:

- mark the in-flight notification handled and dismiss it (see notification-cleanup note below), reusing the existing
  `_mark_auto_approved_plan_handled(plan_file, agent_name)` helper, and
- return `PlanApprovalResult(action=auto_action, plan_file=plan_file)` — the same value the up-front check already
  returns.

This is a small, localized change to logic the runtime already owns. The cost is at most one poll interval (~0.5s) of
latency between pressing `A` and the plan auto-approving, which is imperceptible in practice.

Chosen over the alternatives because it is the most general and least duplicative:

- It covers every way of enabling `%auto` while a plan waits, not just the `A` keymap.
- It keeps the TUI `A` action purely about persisting config (consistent with the existing design split), instead of
  teaching the TUI to synthesize a `plan_response.json`.
- It avoids duplicating the approval-response protocol in a second place.

### Notification cleanup (must handle)

The up-front auto-approve path returns _before_ any notification is created, so it only needs the best-effort
`_mark_auto_approved_plan_handled` call. The new loop path is different: a plan-approval **notification already exists**
(the agent is showing `PLAN`). The manual modal path dismisses it via `mark_dismissed(notification.id)`
(`src/sase/ace/tui/actions/agents/_notification_modals.py`).

The plan implementation must ensure the loop path also clears that live notification so the row leaves the
"Stopped"/needs-input state and the inbox entry does not linger. Confirm whether `_mark_auto_approved_plan_handled` (via
`sase.notifications.pending_actions .mark_plan_approval_auto_handled`) is sufficient on its own, or whether an explicit
`mark_dismissed` of the plan-approval notification for this plan/agent is also required, and add whichever is missing.
This is the main implementation subtlety to get right.

### Tests

- Unit test in `tests/test_plan_utils.py`: drive `handle_plan_approval()` with `get_auto_plan_approval_action()`
  initially returning `None`, then flipping to `"approve"` (and separately `"tale"`/`"epic"`) after the first poll
  iteration; assert it returns a `PlanApprovalResult` with the right action without any `plan_response.json` ever being
  written. Mirror the existing mock/poll structure already in that file.
- Test that `killed_check` still wins (a kill during the wait returns `None` and does not auto-approve).
- Test/assert the in-flight notification is dismissed/handled on the loop auto-approve path.

## Secondary finding (related; recommend a follow-up, not bundled)

There is a separate, opposite-direction correctness gap in the same area: `get_auto_plan_approval_action()` checks the
`SASE_AGENT_AUTO_APPROVE` env var **before** `agent_meta.json`, and `run_agent_runner.py` exports that env var stickily
at launch for any `%auto:plan` agent. As a result, choosing **disable** in the `A` menu for an agent that was _launched_
with `%auto:plan` does not take effect — the sticky env var keeps the auto-approve on. This is over-approval (the
reverse of the reported bug), so it is out of scope for the user's complaint, but it shares the same root theme:
`agent_meta.json` should be the authoritative source for a running agent. Worth a follow-up that makes the meta
authoritative (or drops/de-prioritizes the launch-time env override). Flagging here for visibility; not part of this
change.

## Boundary / conventions notes

- The entire plan-approval poll flow already lives in Python (`_plan_utils.py`, `plan_approve_handler.py`); this change
  stays within that existing Python logic and adds no cross-frontend API. No `sase-core` Rust change is implied.
- No new CLI options, keymaps, or config are introduced, so the default config, help modal, and footer do not need
  updates.
- Run `just check` after implementation (source files change).
