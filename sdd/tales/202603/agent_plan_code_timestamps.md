---
create_time: 2026-03-27 02:08:34
status: done
prompt: sdd/prompts/202603/agent_plan_code_timestamps.md
---

# Plan: Add PLAN and CODE Timestamps to Agent Metadata Panel

## Problem

The agent metadata panel in the Agents tab of `sase ace` currently shows WAIT, BEGIN, and END timestamps. For agents
that created plans (`.plan` suffix), we need to add two new timestamp entries:

- **PLAN**: The time the planner agent submitted its plan for review (when the plan notification is created)
- **CODE**: The time the coder agent (`.code` follow-up) was launched after plan approval

These should appear on the **parent** `.plan` agent's metadata panel, between BEGIN and END.

## Current Architecture

- **Agent model** (`src/sase/ace/tui/models/agent.py`): `start_time`, `run_start_time`, `stop_time` fields;
  `timestamps_display` property renders WAIT/BEGIN/END
- **Plan flow** (`src/sase/axe/run_agent_exec.py:335-351`): Plan created → `update_meta_suffix(".plan")` →
  `handle_plan_approval()` blocks until user acts
- **Coder launch** (`src/sase/axe/run_agent_exec.py:482-518`): On approval → `create_followup_artifacts()` with `.code`
  suffix, which writes `run_started_at` to the child's `agent_meta.json`
- **Status overrides** (`src/sase/ace/tui/models/agent_loader.py:155-229`): Links parent `.plan` agents to children via
  `parent_timestamp`; already iterates over parent-child relationships
- **Meta loading** (`src/sase/ace/tui/models/_loaders/_artifact_loaders.py:25-105`): `enrich_agent_from_meta()` reads
  `agent_meta.json` and populates Agent fields

## Implementation

### Step 1: Write `plan_submitted_at` to agent_meta.json

**File**: `src/sase/axe/run_agent_exec.py`

Right before calling `handle_plan_approval()` (around line 346), write the plan submission timestamp to the current
agent's `agent_meta.json`. This ensures the timestamp is recorded as soon as the plan is submitted, before the approval
poll loop blocks.

```python
# Write plan submission timestamp to agent_meta.json
from sase.axe.run_agent_helpers import update_meta_field
update_meta_field(current_artifacts_dir, "plan_submitted_at", datetime.now(UTC).isoformat())
```

**File**: `src/sase/axe/run_agent_helpers.py`

Add a small `update_meta_field()` helper that reads agent_meta.json, sets a key, and writes it back (similar to
`update_meta_suffix()` but generic).

### Step 2: Add `plan_time` and `code_time` fields to Agent model

**File**: `src/sase/ace/tui/models/agent.py`

Add two new optional datetime fields to the `Agent` dataclass:

```python
plan_time: datetime | None = None   # When plan was submitted for review
code_time: datetime | None = None   # When coder agent was launched
```

### Step 3: Load `plan_submitted_at` from agent_meta.json

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

In `enrich_agent_from_meta()`, parse the `plan_submitted_at` field and set `agent.plan_time`:

```python
plan_submitted_at = data.get("plan_submitted_at")
if isinstance(plan_submitted_at, str):
    try:
        agent.plan_time = _parse_utc_to_eastern(plan_submitted_at)
    except ValueError:
        pass
```

### Step 4: Propagate `code_time` from child to parent

**File**: `src/sase/ace/tui/models/agent_loader.py`

In `_apply_status_overrides()`, when iterating over follow-up children that match a parent, propagate the `.code`
child's `start_time` (or `run_start_time`) to the parent's `code_time`:

```python
# Inside the existing loop over agents with parent_timestamp
if agent.role_suffix == ".code" and parent:
    parent.code_time = agent.run_start_time or agent.start_time
```

### Step 5: Update `timestamps_display` to show PLAN and CODE

**File**: `src/sase/ace/tui/models/agent.py`

In the `timestamps_display` property, after the BEGIN line and before the END line, conditionally add PLAN and CODE:

```python
if self.plan_time is not None:
    parts.append(_fmt("PLAN", self.plan_time.strftime(fmt)))

if self.code_time is not None:
    parts.append(_fmt("CODE", self.code_time.strftime(fmt)))
```

The tag_width of 5 still works (BEGIN is the longest at 5 chars).

### Step 6: Tests

Add tests for:

- `timestamps_display` with plan_time and code_time set
- `update_meta_field` helper
- Propagation of code_time in `_apply_status_overrides`
