---
create_time: 2026-05-10 11:24:36
status: done
prompt: sdd/prompts/202605/fix_bulk_revive_refresh.md
---
# Fix bulk revive: revived agents must appear on the agents tab

## Background

A user marked agents `e8` and `e8.1` on the agents tab and pressed `R` to bulk-revive them. The toast read "Revived 2
agents", but the agents tab list did not visibly update — the revived agents never appeared until the user manually
refreshed.

The disk-side revive succeeded (dismissed set updated, artifacts restored), but the TUI failed to re-render the agents
list/buckets. The toast lies: it says success, the data is changed, but the UI is stale.

## Root cause

In `src/sase/ace/tui/actions/agents/_revive.py`, `_do_revive_agents()` (lines 353-423) ends with:

```python
self.notify(f"Revived {count} agent{'s' if count != 1 else ''}")
self._load_agents()
if self.current_tab == "agents":
    revive_candidates = [a for a in valid_agents if not a.is_workflow_child]
    if not revive_candidates:
        revive_candidates = valid_agents
    for agent in revive_candidates:
        if self._select_revived_agent(agent):
            self._refresh_agents_display(list_changed=True)
            break
```

Two facts establish the bug:

1. `_load_agents()` (`src/sase/ace/tui/actions/agents/_loading.py:140-168`) only updates `self._agents` data; it does
   NOT call `_refresh_agents_display()` itself. The on-screen list, group headers, and bucket counts come from
   `_refresh_agents_display(...)`, not from `_load_agents()` alone.
2. `_select_revived_agent(agent)` (`_revive.py:72-120`) returns `False` whenever the revived agent's `identity` /
   `raw_suffix` is not found in `self._agents`. `_load_agents()` runs the active search query through
   `_finalize_agent_list()` (`src/sase/ace/tui/actions/agents/_loading_finalize.py:119-195`, especially the query filter
   at lines 162-191), so any active query that doesn't match the revived agent excludes it from `self._agents`.

Combined consequence: when the user has an active query (or any other state that filters out the revived agent), every
iteration of the loop returns `False`, the `if … break` body never runs, and `_refresh_agents_display(...)` is never
called. The UI stays stale.

A second contributor is `e8.1`: the bulk path filters `revive_candidates` to non-workflow-children at lines 415-417, so
when the user marks both `e8` and `e8.1`, only `e8` is tried for selection. If `e8` is filtered out of `self._agents`,
no refresh happens at all — and the filter on workflow children is fine for _selection_ (we don't want to focus a phase
child) but should never gate the _refresh_.

The single-agent path `_do_revive_agent()` (lines 350-351) has the same conditional-refresh defect:

```python
if self.current_tab == "agents" and self._select_revived_agent(agent):
    self._refresh_agents_display(list_changed=True)
```

It usually works because the user's view typically already includes the single agent they just selected from the modal —
but the same latent bug exists, and it should be fixed for consistency.

## Fix

Decouple "refresh the agents tab" from "focus the revived agent".

The refresh must happen unconditionally after `_load_agents()` whenever the agents tab is active. Selection (focus) is a
best-effort follow-up that may legitimately fail (e.g., the agent was filtered out by the active query) and that failure
must not suppress the refresh.

### Bulk path (`_do_revive_agents`, lines 414-423)

```python
self._load_agents()
if self.current_tab == "agents":
    self._refresh_agents_display(list_changed=True)
    revive_candidates = [a for a in valid_agents if not a.is_workflow_child]
    if not revive_candidates:
        revive_candidates = valid_agents
    for agent in revive_candidates:
        if self._select_revived_agent(agent):
            break
```

### Single path (`_do_revive_agent`, lines 350-351)

```python
if self.current_tab == "agents":
    self._refresh_agents_display(list_changed=True)
    self._select_revived_agent(agent)
```

`_select_revived_agent` returning `False` is harmless — it just means we could not focus the revived row, which is the
right outcome when the row was filtered out by the active query.

## Out of scope

- **Auto-clearing the search query on revive.** That's a separate UX decision. The current fix preserves "filter is
  sticky" semantics but makes the UI honest about the new state — bucket counts update immediately, and revived agents
  appear as soon as the user clears the query.
- **Making `_load_agents()` always refresh the display.** That would broaden the change to many call sites; the targeted
  revive fix is safer.

## Files to change

- `src/sase/ace/tui/actions/agents/_revive.py`
  - Lines 350-351 (single revive): unconditional refresh + best-effort selection.
  - Lines 414-423 (bulk revive): unconditional refresh + best-effort selection loop.

## Test plan

- Manual: with an active query that excludes `e8` and `e8.1`, mark both, press `R`, confirm toast. Confirm bucket counts
  update immediately (pre-fix: counts stayed stale until manual refresh). Clear the query and confirm both agents are
  visible.
- Manual: with no active query, bulk-revive `e8` + `e8.1` and confirm both appear in the list and one of them is
  focused.
- Manual: single-revive an agent that doesn't match the active query — confirm the agents tab list/buckets update
  immediately even though the revived row is not focused.
- `just check` (lint + tests).

## Risk

Low. The change only adds a refresh call and removes a conditional that gated the existing refresh.
`_refresh_agents_display(list_changed=True)` is idempotent rendering — it is already the function called at line 422
today, just guarded incorrectly.
