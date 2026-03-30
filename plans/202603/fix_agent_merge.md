---
create_time: 2026-03-30 17:45:11
status: done
---

# Fix Agent Merge Bug in Ace TUI Agents Tab

## Problem

Two agents are getting incorrectly "merged" in the `sase ace` Agents tab: a user-run agent and a `#sase/fix_just`
xprompt agent (launched via the `sase_fix_just` chop). The user expects two separate entries but sees them combined.

## Root Cause Analysis

After thorough analysis of the agent loading pipeline (`agent_loader.py`) and dedup pipeline (`_dedup.py`), the most
likely root cause is **PID reuse in `dedup_by_pid()`** — the final safety-net dedup pass.

### How It Happens

1. **Agent A** (chop) launches, gets PID X, creates a RUNNING field entry
2. Agent A finishes or crashes — if the RUNNING field entry isn't cleaned up (crash, race condition), it becomes stale
3. **Agent B** (user) launches — the OS recycles PID X for the new subprocess
4. `_filter_dead_pids()` keeps both entries: the stale entry passes because PID X is alive (it's Agent B's process now)
5. `dedup_by_pid()` sees two agents with the same PID → merges them into one, dropping the other

The critical gap: `dedup_by_pid()` assumes same PID = same agent, but PID reuse breaks this invariant.

### Evidence in Code

In `_dedup.py:dedup_by_pid()` lines 356-369, the fallback `else` branch unconditionally merges agents with the same PID
and same type:

```python
else:
    # Same type — remove the newer one (current agent)
    _merge_agent_fields(existing, agent)
    pid_remove_ids.add(id(agent))
```

There's no check that the two agents actually represent the same work (e.g., same `raw_suffix`/timestamp). Compare this
with the WORKFLOW exemption at lines 355-365 which explicitly checks `raw_suffix != existing.raw_suffix` to avoid
merging follow-up phases — RUNNING agents lack this protection.

### Secondary Hypothesis: Timestamp Collision

`generate_timestamp()` uses second-level precision (`%y%m%d_%H%M%S`). If two agents launch within the same second,
they'd share a `raw_suffix`, causing `dedup_workflow_entries()` and `dedup_running_vs_workflow()` to incorrectly merge
their WORKFLOW entries. This is less likely for a manual launch + chop launch but still a latent bug.

## Proposed Fix

### Phase 1: Harden `dedup_by_pid()` Against PID Reuse

**File**: `src/sase/ace/tui/models/_dedup.py`

Add a `raw_suffix` check to the RUNNING-vs-RUNNING branch of `dedup_by_pid()`, mirroring the existing WORKFLOW
exemption. Two RUNNING agents with the same PID but different `raw_suffix` values are NOT duplicates — they're a stale
entry + a new agent that got the recycled PID.

```python
# Before (current code):
else:
    # Same type — remove the newer one (current agent)
    _merge_agent_fields(existing, agent)
    pid_remove_ids.add(id(agent))

# After:
elif (
    agent.agent_type == AgentType.RUNNING
    and existing.agent_type == AgentType.RUNNING
    and agent.raw_suffix
    and existing.raw_suffix
    and agent.raw_suffix != existing.raw_suffix
):
    # Both RUNNING agents with distinct timestamps — these are
    # separate agents that share a PID due to OS PID recycling.
    # Keep both.
    pass
else:
    # Same type, same or missing suffix — remove the newer one
    _merge_agent_fields(existing, agent)
    pid_remove_ids.add(id(agent))
```

### Phase 2: Add Tests

**File**: `tests/test_agent_loader_dedup_vcs_pid.py`

Add test cases covering:

- Two RUNNING agents with same PID but different `raw_suffix` → both kept (PID reuse)
- Two RUNNING agents with same PID and same `raw_suffix` → merged (true duplicate)
- Two RUNNING agents with same PID, one missing `raw_suffix` → merged (legacy fallback)

### Phase 3: Verify

- Run `just check` to ensure linting and tests pass
- Verify with `sase ace --agent` that existing behavior isn't broken

## Questions for User

Before implementing, I'd like to confirm:

1. The `sase ace` snapshot wasn't attached — could you share it so I can verify the visual symptom?
2. What agent did you run manually? (Same `#sase/fix_just`, or something else?)
3. Was either agent still running when you saw the merge, or were both completed?
