---
create_time: 2026-05-28 07:45:15
status: done
prompt: sdd/prompts/202605/starting_waiting_poll.md
---
# Plan: Refresh Hidden STARTING Agents When WAITING Markers Land

## Problem

Agents with deferred starts are represented in the Agents tab as hidden `STARTING` rows until marker enrichment promotes
them to `RUNNING` or `WAITING`. There is already a cheap countdown-tick poll that watches each hidden STARTING agent's
`agent_meta.json` signature and requests a debounced Agents refresh when that file appears or changes.

The race is that `WAITING` is not signaled by `agent_meta.json`; it is signaled by `waiting.json`. If the inotify
watcher misses the `waiting.json` create event, or the watcher has not yet attached to the new timestamp directory, the
current poll can observe a stable `agent_meta.json` forever and never schedule the refresh that would re-run the loader
and make the WAITING row visible.

## Design

Extend the existing STARTING-transition poll rather than adding a new refresh loop. It is already scoped to the Agents
tab, already runs on the one-second countdown tick, already operates only while hidden STARTING rows exist, and already
routes through `request_agents_refresh()` so refreshes are coalesced and navigation-gated.

Track lightweight file signatures for both `agent_meta.json` and `waiting.json` per hidden STARTING agent:

- `agent_meta.json` still detects STARTING to RUNNING transitions and missed early metadata creation.
- `waiting.json` detects STARTING to WAITING transitions and missed waiting marker creation/removal/update events.
- The cache stays keyed by `agent.identity` and is evicted whenever the agent is no longer hidden STARTING.

When either signature first appears after an absent baseline, is already present on first observation, or changes,
request one debounced refresh. The refresh path remains the existing async agent loader, so the UI update happens
through the same apply/finalize/render machinery as manual refresh and watcher-driven refresh.

## Performance Constraints

Keep the poll effectively free in the steady state:

- Do nothing when there are no hidden STARTING agents.
- Avoid reading/parsing JSON in the poll; use `os.stat()` only.
- Add only one extra `stat()` per hidden STARTING agent per second.
- Keep refresh scheduling debounced and coalesced through the existing `request_agents_refresh("starting_poll")` path.
- Preserve the existing navigation gate in `_run_agents_async_refresh()` so a refresh never lands during a `j`/`k`
  burst.

## Tests

Update the existing `tests/ace/tui/test_starting_agent_poll.py` coverage:

- Assert a `waiting.json` marker that appears after an absent baseline triggers a refresh.
- Assert a `waiting.json` marker already present on first observation triggers a refresh.
- Assert unchanged marker signatures do not arm repeated timers.
- Assert fan-out still coalesces to one debounce timer.
- Keep the cache eviction and no-STARTING steady-state tests.

Run the focused tests first, then run the required repository check because code files will change:

```bash
just install
pytest tests/ace/tui/test_starting_agent_poll.py
just check
```
