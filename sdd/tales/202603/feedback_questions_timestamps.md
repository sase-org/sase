---
create_time: 2026-03-27 08:22:24
status: done
prompt: sdd/prompts/202603/feedback_questions_timestamps.md
---

# Plan: Add FEEDBACK and QUESTIONS Timestamps to Agent Metadata Panel

## Summary

Add `feedback_time` and `questions_time` fields to the Agent model and display them as FBACK/QUEST lines in
`timestamps_display`, following the exact pattern established by PLAN/CODE timestamps in commit 3f5f2fa.

## Design Decisions

- **Tag names**: FBACK (5 chars) and QUEST (5 chars) — fits existing `tag_width = 5`.
- **Display order**: WAIT → BEGIN → PLAN → FBACK → QUEST → CODE → END. FBACK comes after PLAN because feedback is a
  response to a plan submission. QUEST can happen before or after PLAN, but placing it after FBACK keeps all
  plan-related milestones grouped. CODE comes last since it's the final phase before END.
- **Multiple rounds**: Like `plan_submitted_at`, each field records the latest timestamp only (gets overwritten on
  subsequent rounds). The individual follow-up agents (`.2`, `.3`, `.q`) still have their own start_time for per-round
  tracking.
- **Propagation**: `feedback_time` is recorded on the current (parent) agent when the user gives feedback, so no
  child→parent propagation needed (unlike `code_time`). For `questions_time`, we record it on the current artifacts dir
  before spawning the `.q` follow-up, same as `plan_submitted_at`.

## Changes

### 1. Record timestamps in `run_agent_exec.py`

**File**: `src/sase/axe/run_agent_exec.py`

At the feedback branch (line 372, `if plan_result.action == "feedback"`), add after line 375:

```python
from datetime import UTC, datetime as _dt
update_meta_field(
    current_artifacts_dir,
    "feedback_submitted_at",
    _dt.now(UTC).isoformat(),
)
```

At the questions branch (line 530, `elif q_data`), add after `update_meta_suffix()` call (line 536):

```python
from datetime import UTC, datetime as _dt
update_meta_field(
    current_artifacts_dir,
    "questions_submitted_at",
    _dt.now(UTC).isoformat(),
)
```

### 2. Add model fields in `agent.py`

**File**: `src/sase/ace/tui/models/agent.py`

Add two new fields after `code_time` (line 161):

```python
# When feedback was submitted on the plan
feedback_time: datetime | None = None
# When the agent submitted questions for user review
questions_time: datetime | None = None
```

Add FBACK and QUEST to `timestamps_display` (between PLAN and CODE blocks):

```python
if self.feedback_time is not None:
    parts.append(_fmt("FBACK", self.feedback_time.strftime(fmt)))

if self.questions_time is not None:
    parts.append(_fmt("QUEST", self.questions_time.strftime(fmt)))
```

Add both to `_DATETIME_FIELDS` set in `from_bundle_dict`:

```python
_DATETIME_FIELDS = {"run_start_time", "stop_time", "plan_time", "code_time", "feedback_time", "questions_time"}
```

### 3. Parse from agent_meta.json in `_artifact_loaders.py`

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

Add parsing blocks after the `plan_submitted_at` block (after line 74):

```python
# Parse feedback_submitted_at (when feedback was given on the plan)
feedback_submitted_at = data.get("feedback_submitted_at")
if isinstance(feedback_submitted_at, str):
    try:
        agent.feedback_time = _parse_utc_to_eastern(feedback_submitted_at)
    except ValueError:
        pass

# Parse questions_submitted_at (when agent submitted questions)
questions_submitted_at = data.get("questions_submitted_at")
if isinstance(questions_submitted_at, str):
    try:
        agent.questions_time = _parse_utc_to_eastern(questions_submitted_at)
    except ValueError:
        pass
```

### 4. Tests

**File**: `tests/test_agent_model.py`

- Update `test_timestamps_display_with_plan_and_code` to include feedback_time and questions_time, verifying tag order:
  WAIT → BEGIN → PLAN → FBACK → QUEST → CODE → END
- Add `test_timestamps_display_feedback_only` — shows FBACK without QUEST
- Add `test_timestamps_display_questions_only` — shows QUEST without FBACK
- Add `test_bundle_round_trip_feedback_and_questions_time` — verify serialization round-trip

**File**: `tests/test_agent_loader.py`

- No new tests needed — feedback_time and questions_time don't propagate from children (they're recorded directly on the
  parent agent's artifacts dir).

**File**: `tests/test_axe_run_agent_helpers.py`

- No new tests needed — we reuse the existing `update_meta_field()` function which is already tested.
