---
create_time: 2026-05-14 22:21:47
status: done
prompt: sdd/prompts/202605/async_agent_query_content_search.md
---
# Async Agent-Query Content Search Plan

## Problem

The Agents tab currently routes disk loading through async workers, but content-aware query filtering still does
synchronous file reads during finalization. `finalize_agent_list()` calls `evaluate_agent_query()` with
`AgentContentSearchCache`, and cache misses read prompt/reply/attempt files on the Textual event loop. This can freeze
the UI after an otherwise async refresh, especially on the first content query or when many reply files are changing.

## Goal

Make content-backed agent-query evaluation non-blocking for the TUI event loop while preserving the current query
language semantics, hierarchy preservation, selection restoration, status overrides, grouping cleanup, and display
refresh behavior.

## Design

Keep finalization on the UI thread, but make it consume an I/O-free content haystack index. The finalizer should never
call the file-backed `AgentContentSearchCache.get_haystack()` directly. Instead:

1. Extend `AgentContentSearchCache` with worker-friendly snapshot/index helpers.
   - Keep the existing sync `get_haystack()` behavior for unit tests and non-TUI callers.
   - Add a lightweight content index object implementing `get_haystack(agent)` from an in-memory identity-to-text map.
   - Add helpers to fork/copy cache state for a worker, build a haystack index for a list of agents, and merge the
     worker cache state back on the UI thread. This avoids mutating the same cache dictionaries from the UI thread and
     worker thread at the same time.

2. Add TUI state for the latest prepared query content index.
   - Store the current in-memory index separately from `_agent_content_search_cache`.
   - Use generation/query/list guards so stale worker results from an older query or older agent list do not overwrite
     newer UI state.
   - Treat a missing index as metadata-only content for that render rather than doing disk I/O on the UI thread.

3. Build the index off-thread during async agent refresh.
   - After the loader worker produces `PreparedApplyData`, if an agent search query is active, fork the cache and build
     the haystack index with `asyncio.to_thread()`.
   - Merge the updated cache state and install the resulting index before `_apply_loaded_agents_prepared()` runs
     finalization.
   - If there is no active query, clear the prepared index and prune cache normally after finalization.

4. Make in-memory refiltering non-blocking.
   - `_refilter_agents()` should continue to give immediate feedback, but finalization must use the current prepared
     index or metadata-only matching.
   - When a query is active and cached agents are refiltered without a full load, schedule a small background content
     index refresh for `_agents_with_children`. When it completes, re-run the refilter/finalize path only if the query
     and source-list generation still match.
   - Avoid recursive scheduling when the background result triggers the second refilter.

5. Preserve query semantics.
   - Bare strings and `text:` continue searching metadata plus content when the content index is available.
   - Case-sensitive string matches remain metadata-only, matching current evaluator behavior.
   - Parent match preservation still happens in the finalizer exactly as today.

## Tests

Add focused tests rather than relying only on behavior tests:

1. Unit-test the new content index/cache helpers:
   - Building an index includes prompt/reply/attempt/chat fallback text.
   - The index object serves haystacks without calling file-backed cache reads.
   - Cache state can be forked, populated, and merged.

2. Update/add finalizer integration tests:
   - With a prepared index, a content query filters agents correctly.
   - Without a prepared index, finalization does not call `_agent_content_search_cache.get_haystack()` and falls back to
     metadata-only matching.
   - Hierarchy preservation still works for content-matched parents.

3. Add async/refilter coverage if feasible with the existing fake app pattern:
   - Query edit/refilter schedules content-index refresh instead of doing inline reads.
   - A stale background generation is ignored.

Run targeted pytest for the touched areas first, then `just install` and `just check` per repo instructions.
