---
bead_id: sase-1xc
---

# Plan: Add PLANNING, CODING, and QUESTION agent statuses

## Context

The Agents tab side-panel currently shows statuses RUNNING, DONE, and FAILED. We need three new statuses that reflect
intermediate agent states:

- **PLANNING** — agent sent a plan notification awaiting user review
- **CODING** — plan was approved, agent is now implementing
- **QUESTION** — agent asked a question awaiting user answer

These must be treated like RUNNING for visibility, sorting, PID-checking, and kill behavior.

## Key challenge: Notification → Agent mapping

Plan/question notifications currently carry only `session_id` — no agent identity. We must thread agent identity
(cl_name, timestamp) through env vars so the plan-approve and user-question handlers can include it in the
notification's `action_data`.

---

## Implementation Steps

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

### 3. Add status override system to the TUI

**File:** `src/sase/ace/tui/actions/agents/_core.py`

Add two new attributes to `AgentsMixinCore`:

```python
_agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
_agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
```

In `_load_agents()`, after loading and filtering agents, apply overrides:

- If agent disk status is DONE/FAILED → clear any override (agent finished)
- Else if agent has an active override → replace `agent.status` with the override

**File:** `src/sase/ace/tui/app.py`

Initialize the new dicts in `__init__`:

```python
self._agent_status_overrides = {}
self._agent_pre_question_status = {}
```

### 4. Detect new plan/question notifications during polling

**File:** `src/sase/ace/tui/actions/agents/_notifications.py`

Extend `_poll_agent_completions()` to scan unread notifications:

- For each unread `PlanApproval` notification with agent identity: set override to "PLANNING"
- For each unread `UserQuestion` notification with agent identity: save previous override in
  `_agent_pre_question_status`, set override to "QUESTION"

The overrides are idempotent (re-set on each poll if notification is still unread).

### 5. Update status on plan approval/rejection/feedback

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

Add a helper `_find_agent_for_notification(app, notification)` that matches by `agent_cl_name` + `agent_timestamp` in
`action_data`.

Extend `handle_plan_approval()`'s `on_dismiss` callback:

- **Approve** (`action="approve"`): set override to "CODING", reload agents
- **Reject** (`action="reject"`, no feedback): write response, then kill agent via `app._do_kill_agent(agent)`, clear
  override
- **Feedback** (`action="reject"`, has feedback): write response, keep "PLANNING" override

### 6. Update status on question answer

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

Extend `handle_user_question()`'s `on_dismiss` callback:

- On answer: restore previous override from `_agent_pre_question_status` (could be "CODING" or None). If None, remove
  override (agent reverts to disk status, i.e. "RUNNING"). Reload agents.

### 7. Add status colors to the agent list

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

### 8. Add status colors to the detail panel metadata

**File:** `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py` (line 98)

Add to the `status_style` dict:

```python
"PLANNING": "#FF87AF",
"CODING": "#00D7AF",
"QUESTION": "#FFAF00",
```

### 9. Treat new statuses like RUNNING in agent_detail.py

**File:** `src/sase/ace/tui/widgets/agent_detail.py` (lines 158, 175)

Change `("RUNNING", "WAITING INPUT")` to `("RUNNING", "WAITING INPUT", "PLANNING", "CODING", "QUESTION")` — these are
"active" statuses that show auto-refreshing file panels.

Define a module-level constant to avoid repetition:

```python
_ACTIVE_STATUSES = ("RUNNING", "WAITING INPUT", "PLANNING", "CODING", "QUESTION")
```

### 10. Clean up stale overrides

In `_load_agents()` (step 3), also clean overrides for agents that no longer exist in the loaded list (agent was
killed/dismissed externally).

---

## Files modified (summary)

| File                                                         | Change                                                   |
| ------------------------------------------------------------ | -------------------------------------------------------- |
| `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`   | Add agent identity env vars                              |
| `src/sase/notifications/senders.py`                          | Accept + store agent identity in action_data             |
| `src/sase/main/plan_approve_handler.py`                      | Read env vars, pass to notification sender               |
| `src/sase/main/user_question_handler.py`                     | Read env vars, pass to notification sender               |
| `src/sase/ace/tui/actions/agents/_core.py`                   | Add override dicts, apply in \_load_agents               |
| `src/sase/ace/tui/app.py`                                    | Initialize override dicts                                |
| `src/sase/ace/tui/actions/agents/_notifications.py`          | Detect plan/question notifications in polling            |
| `src/sase/ace/tui/actions/agents/_notification_actions.py`   | Agent matching + status updates on approve/reject/answer |
| `src/sase/ace/tui/widgets/agent_list.py`                     | Status colors for PLANNING/CODING/QUESTION               |
| `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py` | Status colors in detail metadata                         |
| `src/sase/ace/tui/widgets/agent_detail.py`                   | Treat new statuses as active                             |

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
