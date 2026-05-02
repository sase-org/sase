---
create_time: 2026-04-27 11:13:25
status: done
prompt: sdd/prompts/202604/agents_tab_done_sort_by_stop_time.md
---
# Plan: Sort done agents by completion time in `sase ace` Agents tab

## Problem

In the **Agents** tab of `sase ace`, when grouping by date (`BY_DATE`, the user's current view per their snapshot),
every agent is sorted by `start_time` — including terminal ones (`DONE`, `PLAN DONE`, `EPIC CREATED`). The user expects
terminal agents to be sorted by their **completion time**, so a recently-finished agent floats to the top of the done
segment regardless of when it started, while running agents continue to be sorted by `start_time` (newest-first).

The user's snapshot shows seven `PLAN DONE` agents whose displayed order tracks their start-order suffixes (`bg`, `be`,
`bd`, `bc`, `bb`, `aw`) rather than the order in which they actually finished — a direct consequence of the bug.

## Root cause

`src/sase/ace/tui/models/agent_groups.py:356-387` — `_walk_anchors()` builds the per-agent sort anchor used under
`BY_DATE`:

```python
if target.start_time is None:
    anchor = float("inf")
else:
    anchor = -target.start_time.timestamp()   # always start_time
```

This anchor is consumed by `_walk_order()` at the same file lines `408-426` (slot `anchors[i][0]` on line 423). It does
not consult `agent.status` or `agent.stop_time`, so terminal agents tiebreak on start-time identically to running ones.

Supporting facts already in the codebase:

- The "Done" status set is centralized: `_status_bucket_for()` (`agent_groups.py:142-163`) returns `"Done"` for
  `{"DONE", "PLAN DONE", "EPIC CREATED"}`.
- `Agent.stop_time: datetime | None` already exists and is populated (`src/sase/ace/tui/models/agent.py:243`, also
  referenced at `:83-86`, `:545-546`, `:571`).
- The bug is only visible under `BY_DATE` because non-`BY_DATE` modes return a constant `(0.0, 0)` anchor
  (`agent_groups.py:372`) and rely on input order. The user is in `BY_DATE`, matching the report.

## Approach

**Single-file change** to `_walk_anchors()` in `src/sase/ace/tui/models/agent_groups.py`:

1. Extract the terminal-status set (`{"DONE", "PLAN DONE", "EPIC CREATED"}`) into a module-level constant (e.g.
   `_TERMINAL_STATUSES`) near `_status_bucket_for()` so both functions share one source of truth. Update
   `_status_bucket_for()` to reference the constant.
2. In `_walk_anchors()`, after resolving `target` (the parent for workflow children — keep the existing logic):
   - If `target.status in _TERMINAL_STATUSES`, prefer `target.stop_time`.
   - Fall back to `target.start_time` when `stop_time is None` (e.g. `done.json` not yet written).
   - If both are missing, keep the existing `+inf` sentinel so the agent sorts last in its bucket.
   - Continue to negate the timestamp so newer-completed agents sort first within the Done segment, matching today's
     newest-first semantics for running agents.
3. The `is_child` slot of the tuple is unchanged. Workflow children still inherit the parent's anchor — but the parent's
   status now decides start-vs-stop, which is the right behavior (a finished workflow's children should cluster with the
   workflow's completion time).

No changes are needed in `_walk_order()`, `agent_list.py`, or any other call site: the anchor's _meaning_ changes but
its _type_ (`tuple[float, int]`) and contract do not.

## Why this is the minimal/correct change

- One file, one function modified (plus a small constant lift).
- Reuses the existing terminal-status definition rather than duplicating it.
- Preserves workflow-child anchor inheritance (the parent-lookup path is untouched).
- `Agent.stop_time` already exists and is populated; no model changes required.
- Doesn't touch non-`BY_DATE` modes, which don't time-sort within a group today and aren't part of the bug report.

## Tests

Co-locate with the existing `BY_DATE` tests in `tests/ace/tui/models/test_agent_groups_grouping_mode.py` (the only file
under `tests/ace/tui/models/` that exercises `GroupingMode.BY_DATE`). Use the existing `_agent()` helper from
`_agent_groups_helpers.py`.

New cases:

1. **Done segment sorts by stop_time, not start_time.** Two `DONE` agents in the same date bucket where start vs. stop
   order is inverted: A starts earlier but stops later; B starts later but stops earlier. Assert A precedes B in the
   rendered tree (newest completion first).
2. **Mixed running + done.** One `RUNNING` agent and one `DONE` agent in the same date bucket. Confirm the running
   agent's anchor is its `start_time` and the done agent's anchor is its `stop_time`, with the resulting order matching
   newest-first by whichever timestamp applies.
3. **Done agent missing `stop_time` falls back to `start_time`.** `DONE` with `stop_time=None` should still sort (using
   `start_time`) and not crash.
4. **Workflow child inherits parent's stop_time.** Parent is `DONE` (workflow finished); child's anchor tracks the
   parent's `stop_time`, not the parent's `start_time`. The child still sorts immediately after the parent (the existing
   `is_child` invariant).
5. **Regression coverage.** The existing `BY_DATE` ordering tests in `test_agent_groups_grouping_mode.py` continue to
   pass; if any of them conflate start- and stop-time for terminal agents, update the fixture to set both timestamps
   explicitly.

## Verification

- `just install && just check` from the workspace.
- Optional manual smoke: launch `sase ace`, switch the Agents tab to group-by-date, and confirm the Done segment
  reorders when an older-started agent finishes after a newer-started one.

## Out of scope

- Non-`BY_DATE` grouping (`STANDARD`, `BY_STATUS`) — they don't time-sort within a group today and the bug report
  doesn't request it.
- How `stop_time` itself is sourced (`agent.py`).
- The "duration" rendering in `agent_list.py` — that's display, not sort order.

## Files involved

- Edit: `src/sase/ace/tui/models/agent_groups.py` — extract `_TERMINAL_STATUSES`; modify `_walk_anchors()`.
- Tests: `tests/ace/tui/models/test_agent_groups_grouping_mode.py` — add the cases above.
