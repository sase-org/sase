---
create_time: 2026-04-30 15:36:51
status: done
prompt: sdd/prompts/202604/always_show_by_date_hour_headers.md
---
# Always Show BY_DATE Hour Headers

## Problem

The Agents tab's `group: by date` mode already computes an hour bucket from each agent's display anchor:

- running/non-terminal agents use `start_time`
- terminal agents use `stop_time`, falling back to `start_time`
- workflow children inherit the parent's anchor

However, the tree builder currently emits the hour banner only when at least two agents share the same
`(date bucket, hour)` key. That singleton suppression makes a lone `13:00` agent render directly under `Today`, while
neighboring hours with multiple agents get explicit `HH:00` headers. The requested behavior is to always show an hour
header whenever a BY_DATE bucket contains an agent with a real started/stopped hour, even if that hour has only one
agent.

## Scope

Change only the Agents-tab BY_DATE grouping tree/key enumeration behavior. Preserve:

- date bucket ordering (`Today`, `Yesterday`, `This Week`, `Earlier`)
- newest-first hour ordering
- workflow child adjacency and inherited parent hour
- terminal-agent stop-time anchoring
- name-root singleton suppression in STANDARD and BY_STATUS modes
- the existing `(no time)` fallback behavior unless tests show it must be treated as a real hour

## Implementation Plan

1. Update `src/sase/ace/tui/models/agent_groups/_tree.py` so BY_DATE hour banners are emitted for every real hour
   bucket, not only buckets with two or more agents.
2. Mirror the same predicate in `enumerate_group_keys()` so folding, navigation, jump hints, and bulk actions see the
   same visible hour banner keys as `build_agent_tree()`.
3. Keep the predicate explicit so `(no time)` is not accidentally promoted into a singleton hour header. Multi-agent
   `(no time)` grouping can remain as today if already covered by existing tests.
4. Update focused tests in `tests/ace/tui/models/test_agent_groups_grouping_mode_hour.py` from the old
   singleton-suppression expectation to the new "singleton real hour emits banner" contract.
5. Adjust broader BY_DATE tree tests that asserted no L1 banners when agents were in distinct hours; those assertions
   should now distinguish "no name-root banners" from "hour banners are present".
6. Run the targeted agent grouping test files first. Because repo memory requires it after changes, run `just install`
   if needed and then `just check` before final response.

## Risks

The main risk is stale assumptions in navigation/folding tests that treat BY_DATE as mostly flat. Using one shared
predicate for tree building and key enumeration should keep visible rows, fold keys, and jump hints consistent.
