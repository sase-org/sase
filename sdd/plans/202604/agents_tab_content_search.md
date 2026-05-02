---
create_time: 2026-04-23 17:30:12
status: done
prompt: sdd/prompts/202604/agents_tab_content_search.md
---
# Plan: Content-Aware `/` Search on `sase ace` Agents Tab

## Problem / Motivation

On the Agents tab of the `sase ace` TUI, pressing `/` opens a query modal (`QueryEditModal`) that filters the agent
list. Today that filter does a case-insensitive substring match against only four metadata fields — `cl_name`,
`display_name`, `agent_name`, and `status` — in `_finalize_agent_list()` at
`src/sase/ace/tui/actions/agents/_loading.py:393-420`.

That is mostly useless in practice. When the user has dozens of agents running concurrently, they rarely remember the
exact CL name; what they remember is the _substance_ of the conversation — the question they asked, a phrase in the
reply, an error message the agent emitted. The `/` query should search that content, not just the labels next to it.

## Goal

Make the `/` query on the Agents tab treat each agent's **prompt and reply content** as first-class searchable text, so
that queries like `/connection timeout` or `/flaky test` surface the agents whose transcripts mention those phrases —
not just agents whose status or name happens to contain them.

Existing metadata matches (name, status, etc.) keep working, and parent-of-matching-child hierarchy preservation
continues to work (workflow children with matching content keep their parent visible).

## Scope: What Counts as "Prompts and Replies"

For each displayed agent, the haystack is the concatenation of:

1. **Raw xprompt content** — `get_raw_xprompt_content()` on the Agent (the question the user asked, after xprompt
   expansion).
2. **Reply content** — whichever of these is available, in this priority:
   - `get_live_reply_content()` for RUNNING agents
   - `get_response_content()` for DONE agents with a `response_path`
   - `get_chat_response_content()` as a fallback for agents killed before a full reply was written
3. **Attempt history replies** — for each `AttemptRecord` in `agent.attempt_history`, the attempt's reply via
   `AttemptRecord.get_reply_content()`. This means a query matches if it appears in any prior failed attempt, not just
   the current/final attempt.

Workflow children (`agent.is_workflow_child`) get searched against _their own_ content — the existing parent-matching
fallback is preserved so that if a child matches, its parent stays visible.

Fields like `workspace_num`, `model`, timestamps, etc. are intentionally **not** added to the haystack. Those are better
served by structured filters if we ever want them; right now the point is free-text search over conversation content.

## Non-Goals

- No change to the ChangeSpecs tab's query language or search UI.
- No change to the `QueryEditModal` itself — still a plain substring query, still case-insensitive.
- No regex, boolean operators, or field-scoped queries (`prompt:foo`, `reply:bar`). Potentially worth doing later, but
  not part of this change.
- No new UI for showing _where_ in a transcript a match occurred (no "jump to match" affordance). A match just keeps the
  agent in the list; the user opens the agent detail to see the content.

## Key Design Decisions

### 1. Lazy-load content, only when a query is active

Today, prompt/reply content is only read from disk when the detail panel renders a selected agent. We must preserve that
property: when the `/` query is empty (the default), the filter does **zero** additional file I/O. Only when
`self._agent_search_query` is non-empty do we read transcript content for filtering.

This keeps the common case (no filter) free and confines the cost to the explicit search case.

### 2. Cache content by `(path, mtime)`

The Agents tab has a periodic auto-refresh (`_load_agents()` runs on a timer). With a non-empty query, we'd otherwise
re-read every transcript on every refresh. To avoid that, introduce a tiny cache keyed by `(path, mtime_ns)` →
lowercased content.

- If a file's mtime hasn't changed, reuse the cached lowercased string.
- RUNNING agents' `live_reply.md` grows over time; mtime changes trigger a re-read, which is correct.
- DONE agents' response files don't change; they're read once and stay cached.
- Pruning: clear cache entries whose agents are no longer in `self._agents` (bounded memory). Simple mark-and-sweep at
  the end of each load cycle.

Cache lives on the `AceApp` instance (e.g., `self._agent_content_search_cache: AgentContentSearchCache`), so it persists
across refreshes but dies with the app.

### 3. Cap per-file read size

For pathological cases (an agent with a 5 MB reply), cap the amount of text the cache stores per file — e.g., the first
512 KB. In practice live replies are far smaller; the cap is a safety rail, not a feature. Document this in a comment
where it's applied.

### 4. Degrade gracefully on missing files / IO errors

`get_raw_xprompt_content()`, `get_live_reply_content()`, etc. already tolerate missing files (they return empty strings
or `None`). The cache should treat read errors as "empty haystack for this path" without surfacing an exception to the
UI. The existing metadata-fields match still fires, so a name/status match still works even if the transcript can't be
read.

### 5. Keep the filter location unchanged

The filter stays inside `_finalize_agent_list()` in `_loading.py`. The current block (lines ~393-420) grows a small
amount: the per-agent predicate gets a new disjunct that checks cached content. The parent-preservation set
(`matching_parent_names`) is built using the same expanded predicate.

Keeping it in one place preserves the invariant that filtering happens after fold filtering and before panel-index
assignment.

### 6. No async / threading for v1

Reading N small files on a filter refresh is fast enough for realistic N (tens to low hundreds of agents, KB-sized
transcripts). If profiling later shows hitches, we can offload to a worker — but that's a follow-up, not a prerequisite.

## High-Level Implementation Outline

1. **New helper module** `src/sase/ace/tui/models/agent_content_search.py` with:
   - `AgentContentSearchCache` class
   - `get_haystack(agent: Agent) -> str` method: returns the concatenated, lowercased content for the agent (prompt +
     reply + attempt replies), using the `(path, mtime_ns)` cache internally.
   - `prune(active_agents: Iterable[Agent])` method: drop cache entries for paths no longer in use.
   - Internal helpers to enumerate the relevant paths for an agent (xprompt path, live/final reply path, chat response
     path, each attempt's `live_reply_path`).

2. **Wire the cache into `AceApp`**:
   - Instantiate once in `AceApp.__init__` (or next to other agent-tab state).
   - Pass it (or access it via `self`) from `_finalize_agent_list()`.

3. **Modify the search block in `_finalize_agent_list()`**:
   - When `self._agent_search_query` is non-empty, compute `query_lower` once.
   - For each agent, build a match predicate that tests (a) the four existing metadata fields and (b) the cached
     haystack from `AgentContentSearchCache.get_haystack(agent)`.
   - Use the same predicate to build `matching_parent_names` and the final filtered list.
   - After filtering, call `cache.prune(self._agents)` so entries for no-longer-visible agents get released.

4. **Minor UX touch (optional, worth doing)**: in `AgentInfoPanel.update_search_query()`, when the query is non-empty,
   the existing "filter: X" chip is fine — no textual change needed. However, if content search returns zero matches,
   the list is just empty; the existing "Agents: 0/Y" count already communicates this. Skip adding new UI for v1.

5. **Tests** (new file under `tests/` mirroring the existing agents-tab test layout):
   - Unit tests for `AgentContentSearchCache`:
     - Reads file, caches by `(path, mtime_ns)`.
     - Re-read triggers on mtime change.
     - Missing file → empty string, no exception.
     - Size cap is honored.
     - `prune()` drops inactive paths.
   - Filter-level test: construct a fake `Agent` with a temp `artifacts_dir` containing a `raw_xprompt.md` and
     `live_reply.md`; assert that a query matching content inside those files keeps the agent in the filtered list, and
     a non-matching query drops it.
   - Regression test: empty query → no extra file I/O (can assert via a spy/mock on the cache method count, or via
     `monkeypatch` on `open`).

## Risks & Mitigations

| Risk                                                                            | Mitigation                                                                                                                                                              |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auto-refresh stalls on large transcripts under an active query                  | `(path, mtime_ns)` cache means files only re-read when they change. Size cap bounds worst case.                                                                         |
| Memory growth from caching many agents' replies                                 | `prune()` called each filter cycle keeps cache bounded to currently-loaded agents.                                                                                      |
| Users expect highlighting of the match inside the transcript                    | Explicitly out of scope; document in the plan. The agent detail panel already renders the full content — users can `/` in a terminal scrollback or use the detail view. |
| Content search makes zero-match queries look indistinguishable from "no agents" | Existing "Agents: 0/Y" count plus the "filter: …" chip in `AgentInfoPanel` already communicate this clearly. No new UI required.                                        |
| Attempt history reply paths are structured differently from the main reply path | `AttemptRecord` already exposes `live_reply_path` and a `get_reply_content()` helper (see `models/agent.py:50-131`). Use those, don't re-derive paths.                  |

## Files Touched (expected)

- **New:** `src/sase/ace/tui/models/agent_content_search.py`
- **New tests** under `tests/ace/tui/` (mirroring existing structure)
- **Modified:** `src/sase/ace/tui/actions/agents/_loading.py` (the filter block in `_finalize_agent_list()`)
- **Modified:** `src/sase/ace/tui/app.py` (instantiate the cache, pass it through or store it on the app)

No changes to `bindings.py`, `base.py` action dispatch, `QueryEditModal`, or the widgets themselves.

## Validation Plan

- `just check` (lint + type + test) must pass.
- Manual smoke test: run `sase ace`, switch to Agents tab, press `/`, enter a phrase that appears only in a reply (not
  in any name/status), confirm the expected agent is retained and others are filtered out. Repeat with a phrase that
  appears only in an attempt's reply to confirm attempt history is searched. Confirm empty-query case still displays all
  agents and does not noticeably slow down on auto-refresh.
