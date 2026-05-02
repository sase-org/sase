---
create_time: 2026-04-21 16:30:38
status: done
prompt: sdd/prompts/202604/question_status_override.md
---

# Fix: Agents with Unanswered Questions Incorrectly Show DONE Instead of QUESTION

## Problem

In the `sase ace` TUI, an agent that has asked a user question via `/sase_questions` but whose question was never
answered (typically because the agent process was killed during polling) is displayed with status `DONE` instead of
`QUESTION`. The agent's QUEST timestamp is still rendered in the metadata panel, but the status badge is wrong.

Concrete example from the snapshot:

```
✘ [agent] protect (DONE) (6 steps) @k
  ...
  Timestamps: BEGIN | 2026-04-21 16:04:27
              QUEST | 2026-04-21 16:17:04
  AGENT CHAT: No response file found.
```

The agent is clearly waiting on user input (it emitted a QUEST timestamp and has no response file), yet the status shows
DONE.

## Root Cause

There are two places that could promote an agent to `QUESTION` status:

1. **Notification-based override** in `src/sase/ace/tui/actions/agents/_notifications.py`
   (`_apply_notification_status_overrides`). This path explicitly short-circuits for DONE/FAILED agents at lines
   117-118:

   ```python
   # Skip finished agents — overrides don't apply
   if agent.status in ("DONE", "FAILED"):
       break
   ```

2. **Workflow-relationship overrides** in `src/sase/ace/tui/models/agent_loader.py` (`_apply_status_overrides`). This
   function has DONE → PLAN APPROVED / PLAN DONE / PLANNING transitions, but **no DONE → QUESTION transition**.

When `/sase_questions` is invoked, the sequence is:

1. `handle_questions_marker` (`src/sase/axe/run_agent_exec_plan.py:421`) writes `questions_submitted_at` to
   `agent_meta.json` — this populates `agent.questions_times` and renders the QUEST timestamp in the metadata panel.
2. `handle_questions_flow` (`src/sase/axe/run_agent_helpers.py:385`) polls for `question_response.json`.
3. The `.q` follow-up artifact directory is **only created AFTER** `handle_questions_flow` returns a response
   (`create_followup_artifacts` is called after `if response is None: return "killed"`).
4. If the process is killed during polling (SIGTERM, user closes session, crash), `handle_questions_flow` returns
   `None`, the loop exits with `"killed"`, and `done.json` is written to the agent's main artifact directory.

Net result: the agent has `questions_submitted_at` in its meta, no `.q` follow-up child, and `done.json` on disk — so
the TUI classifies it as DONE with no override path available.

## Proposed Fix

Add a new DONE → QUESTION override to `_apply_status_overrides` in `src/sase/ace/tui/models/agent_loader.py`. The signal
for "unanswered question" is:

- `agent.questions_times` is non-empty (the agent definitely submitted at least one question).
- `agent.raw_suffix` is not in `parents_with_followup` (no `.q` follow-up child exists — the `.q` follow-up is created
  strictly after a response is received, so its absence means the question was never answered).

This mirrors the existing DONE→PLAN_DONE / DONE→PLANNING patterns in the same function and is purely file-based (no
notification dependency).

### Code change sketch (agent_loader.py)

Insert after the DONE → PLANNING block (currently ending around line 283) and update the module docstring to document
the new transition:

```python
# Override DONE → QUESTION for agents whose last question was never answered.
# Indicator: questions_submitted_at was written to agent_meta.json (populating
# questions_times) but no follow-up was spawned. The .q follow-up is created
# only AFTER a response is received, so its absence means the polling loop
# was killed before the user answered.
for agent in agents:
    if (
        agent.status == "DONE"
        and agent.questions_times
        and agent.raw_suffix
        and agent.raw_suffix not in parents_with_followup
    ):
        agent.status = "QUESTION"
```

Placement matters: putting this block **after** the DONE → PLAN DONE / DONE → PLANNING blocks ensures QUESTION wins when
both could apply (a pending question is more actionable than "plan done"). In practice a `.plan` agent with an
unanswered question is rare, but ordering makes the behavior explicit.

### Interactions verified

- **DISMISSABLE_STATUSES** (`src/sase/ace/tui/actions/agents/_loading_helpers.py:15`) = {DONE, FAILED, PLAN COMMITTED,
  PLAN DONE}. After the override, status is `QUESTION`, which is not dismissable — the footer will render the agent as
  actionable, consistent with other QUESTION agents.
- **Override clearing** in `src/sase/ace/tui/actions/agents/_loading.py:352-357` clears `_agent_status_overrides`
  entries when status is dismissable. Since we flip DONE→QUESTION in the file-based path (runs in `load_all_agents`
  before `_finalize_agent_list`), the clearing check sees QUESTION and leaves any coexisting notification override
  intact.
- **Notification system** (`_apply_notification_status_overrides`) still skips DONE/FAILED agents. With the file-based
  override running first, the agent is already QUESTION by the time notifications are considered, so the notification
  path becomes a no-op for this case.
- **`_is_feedback_suffix`** excludes `.q` (it only matches purely-numeric suffixes like `.2`, `.3`), so `.q` children
  are correctly registered in `parents_with_followup`.

## Files to Modify

- **`src/sase/ace/tui/models/agent_loader.py`**
  - Add the new DONE → QUESTION override block in `_apply_status_overrides`.
  - Update the function docstring to list the new transition.

- **`tests/test_agent_loader.py`**
  - Positive test: agent with `status="DONE"`, non-empty `questions_times`, non-empty `raw_suffix`, and no child with
    matching `parent_timestamp` → `_apply_status_overrides` flips status to `"QUESTION"`.
  - Negative test: same setup but with a `.q` child whose `parent_timestamp` equals the parent's `raw_suffix` → status
    stays `"DONE"`.
  - Negative test: agent with `status="DONE"` and empty `questions_times` → status stays `"DONE"`.

## Validation

- `just check` (lint + mypy + pytest with coverage).
- Manual TUI sanity check is out of scope (requires an active agent with an unanswered question); the new unit tests
  give enough confidence.

## Out of Scope

- Not modifying `_apply_notification_status_overrides` — the file-based override runs first and takes precedence for
  DONE agents; the notification path continues to handle RUNNING-agent QUESTION overrides.
- Not adding a new `questions_answered_at` timestamp field — follow-up presence is a simpler, equivalent signal with no
  new file-format churn.
- Not changing the metadata panel rendering — the QUEST timestamp is already rendered correctly; only the status badge
  changes.
- No commit / branch / PR creation — the user will commit themselves.
