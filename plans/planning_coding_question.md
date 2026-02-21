---
bead_id: sase-0dw
---

# Plan: Add PLANNING, CODING, and QUESTION agent statuses

## Context

The Agents tab side-panel currently shows statuses RUNNING, WAITING INPUT, DONE, and FAILED. We need three new statuses
that reflect intermediate agent states:

- **PLANNING** — agent sent a plan notification awaiting user review
- **CODING** — plan was approved, agent is now implementing
- **QUESTION** — agent asked a question awaiting user answer

These must be treated exactly like RUNNING in ALL scenarios: visibility, sorting, PID-checking, kill behavior,
auto-refresh, keybindings, etc.

## Key challenge: Notification → Agent mapping

Plan/question notifications currently carry only `session_id` — no agent identity. We must thread agent identity
(cl_name, project_file, timestamp) through env vars so the plan-approve and user-question handlers can include it in the
notification's `action_data`.

---

## Phase 1 — Foundation (all items parallelizable)

All items in this phase are independent and can be implemented concurrently.

### 1. Pass agent identity via env vars during launch

**File:** `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`

In `_launch_background_agent` (around line 332), add to `subprocess_env`:

```python
subprocess_env["SASE_AGENT_CL_NAME"] = cl_name
subprocess_env["SASE_AGENT_PROJECT_FILE"] = project_file
subprocess_env["SASE_AGENT_TIMESTAMP"] = timestamp
```

### 2. Include agent identity in notification action_data

**File:** `src/sase/notifications/senders.py`

Add optional `agent_cl_name`, `agent_project_file`, `agent_timestamp` params to `notify_plan_approval()` and
`notify_user_question()`. Store them in `action_data`.

**File:** `src/sase/main/plan_approve_handler.py` (around line 178)

Read env vars and pass to `notify_plan_approval`:

```python
agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
```

**File:** `src/sase/main/user_question_handler.py` (around line 123)

Same pattern — read env vars and pass to `notify_user_question`.

### 3. Add status colors to the agent list

**File:** `src/sase/ace/tui/widgets/agent_list.py` (lines 247-254)

Add color styling for new statuses:

```python
elif agent.status == "PLANNING":
    text.append(agent.status, style="bold #FF87AF")  # Pink
elif agent.status == "CODING":
    text.append(agent.status, style="bold #00D7AF")  # Green-blue (teal)
elif agent.status == "QUESTION":
    text.append(agent.status, style="bold #FFAF00")  # Amber/orange
```

### 4. Add status colors to the detail panel metadata

**File:** `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py` (line 98)

Add to the `status_style` dict:

```python
"PLANNING": "#FF87AF",
"CODING": "#00D7AF",
"QUESTION": "#FFAF00",
```

### 5. Treat new statuses like RUNNING in agent_detail.py

**File:** `src/sase/ace/tui/widgets/agent_detail.py` (lines 158, 175)

Change `("RUNNING", "WAITING INPUT")` to include all active statuses — these are "active" statuses that show
auto-refreshing file panels.

Define a module-level constant to avoid repetition:

```python
_ACTIVE_STATUSES = ("RUNNING", "WAITING INPUT", "PLANNING", "CODING", "QUESTION")
```

### 6. Treat new statuses like RUNNING in PID liveness checks

**File:** `src/sase/ace/tui/models/_loaders/_workflow_loaders.py` (lines 105-110)

The PID liveness check currently only covers `("RUNNING", "WAITING INPUT")`. Update to include the new statuses so that
a PLANNING/CODING/QUESTION agent with a dead PID is correctly marked as FAILED:

```python
if (
    display_status in _ACTIVE_STATUSES
    and pid is not None
    and not is_process_running(pid)
):
    display_status = "FAILED"
```

Use the same `_ACTIVE_STATUSES` constant (import it or define a shared one). Note: the override system (Phase 2) sets
display statuses _after_ loading, so this check applies to the underlying disk status. The override system in step 8
already handles clearing overrides when the disk status is DONE/FAILED (which includes dead-PID detection).

---

## Phase 2 — Override System (depends on Phase 1; items are sequential)

These items build on each other and should be implemented in order.

### 7. Add status override system to the TUI

**File:** `src/sase/ace/tui/actions/agents/_core.py`

Add two new attributes to `AgentsMixinCore`:

```python
_agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
_agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
```

In `_load_agents()`, after loading and filtering agents, apply overrides:

- If agent disk status is DONE/FAILED → clear any override (agent finished; covers dead-PID detection too)
- Else if agent has an active override → replace `agent.status` with the override

Also clean overrides for agents that no longer exist in the loaded list (agent was killed/dismissed externally).

**File:** `src/sase/ace/tui/app.py`

Initialize the new dicts in `__init__`:

```python
self._agent_status_overrides = {}
self._agent_pre_question_status = {}
```

### 8. Detect new plan/question notifications during polling

**File:** `src/sase/ace/tui/actions/agents/_notifications.py`

Extend `_poll_agent_completions()` to scan unread notifications:

- For each unread `PlanApproval` notification with agent identity in `action_data`: set override to "PLANNING"
- For each unread `UserQuestion` notification with agent identity in `action_data`:
  - **Only save** the previous override into `_agent_pre_question_status` if the current override is **not** already
    "QUESTION". This prevents re-polling from overwriting the original pre-question status (e.g., "CODING" or None) with
    "QUESTION".
  - Set override to "QUESTION"

The overrides are idempotent (re-set on each poll if notification is still unread), but the pre-question save is
conditional to avoid data loss.

---

## Phase 3 — Interaction Handlers (depends on Phase 2; items are parallelizable)

All items in this phase are independent and can be implemented concurrently.

### 9. Add agent-notification matching helper

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

Add a helper `_find_agent_for_notification(app, notification)` that matches by `agent_cl_name` + `agent_timestamp` in
`action_data` against the currently loaded agents list. Returns the matching `Agent` or `None`.

### 10. Update status on plan approval/rejection/feedback

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

Extend `handle_plan_approval()`'s `on_dismiss` callback:

- **Approve** (`action="approve"`): write response file, set override to "CODING", reload agents
- **Reject** (`action="reject"`, no feedback): kill agent via `app._kill_workflow_agent(agent)` (this kills the entire
  process group including the plan_approve_handler, so no response file write is needed — the handler dies with the
  agent). Clear the override. The kill logic already sets the disk status to FAILED.
- **Feedback** (`action="reject"`, has feedback): write response file (handler reads it and emits deny decision with
  feedback to Claude Code). Keep "PLANNING" override — the agent continues and will send a new plan notification.

### 11. Update status on question answer

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

Extend `handle_user_question()`'s `on_dismiss` callback:

- On answer: write response file, then restore previous override from `_agent_pre_question_status` (could be "CODING" or
  None). If None, remove the override (agent reverts to disk status, i.e. "RUNNING"). Clear the
  `_agent_pre_question_status` entry. Reload agents.

### 12. Dismiss plan/question notifications when agent is killed directly

**File:** `src/sase/ace/tui/actions/agents/_killing.py`

Extend `_dismiss_notifications_for_agent()` to also dismiss `PlanApproval` and `UserQuestion` notifications whose
`action_data` contains matching `agent_cl_name` + `agent_timestamp`. Without this, killing an agent via the `x`
keybinding would leave stale plan/question notifications in the unread queue.

Also clear the agent's entry from `_agent_status_overrides` and `_agent_pre_question_status` in the kill handler so the
override system doesn't try to re-apply a stale override.

---

## Files modified (summary)

| File                                                         | Phase | Change                                                          |
| ------------------------------------------------------------ | ----- | --------------------------------------------------------------- |
| `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`   | 1     | Add agent identity env vars                                     |
| `src/sase/notifications/senders.py`                          | 1     | Accept + store agent identity in action_data                    |
| `src/sase/main/plan_approve_handler.py`                      | 1     | Read env vars, pass to notification sender                      |
| `src/sase/main/user_question_handler.py`                     | 1     | Read env vars, pass to notification sender                      |
| `src/sase/ace/tui/widgets/agent_list.py`                     | 1     | Status colors for PLANNING/CODING/QUESTION                      |
| `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py` | 1     | Status colors in detail metadata                                |
| `src/sase/ace/tui/widgets/agent_detail.py`                   | 1     | Treat new statuses as active (auto-refresh file panels)         |
| `src/sase/ace/tui/models/_loaders/_workflow_loaders.py`      | 1     | Include new statuses in PID liveness check                      |
| `src/sase/ace/tui/actions/agents/_core.py`                   | 2     | Add override dicts, apply in \_load_agents, clean stale entries |
| `src/sase/ace/tui/app.py`                                    | 2     | Initialize override dicts                                       |
| `src/sase/ace/tui/actions/agents/_notifications.py`          | 2     | Detect plan/question notifications in polling                   |
| `src/sase/ace/tui/actions/agents/_notification_actions.py`   | 3     | Agent matching + status updates on approve/reject/answer        |
| `src/sase/ace/tui/actions/agents/_killing.py`                | 3     | Dismiss plan/question notifications + clear overrides on kill   |

## Verification

1. **Lint/type-check:** `just lint` — ensure all new code passes ruff + mypy
2. **Tests:** `just test` — ensure existing tests pass
3. **Manual TUI test:** `.venv/bin/sase ace --agent` to verify agent list renders
4. **End-to-end:** Launch an agent via `sase ace`, trigger a plan notification, verify:
   - Agent shows PLANNING status (pink) when plan notification arrives
   - Approving switches to CODING (green-blue)
   - Rejecting kills the agent (FAILED status)
   - Feedback keeps PLANNING
   - Question notification switches to QUESTION (amber)
   - Answering restores previous status
   - Killing an agent with active plan/question notification dismisses the notification
   - Dead PID with PLANNING/CODING/QUESTION override → clears override, shows FAILED
