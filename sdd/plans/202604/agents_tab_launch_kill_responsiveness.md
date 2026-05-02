---
create_time: 2026-04-24 16:06:11
status: proposed
prompt: sdd/prompts/202604/agents_tab_launch_kill_responsiveness.md
---

# Plan: Make Agents Tab Respond Immediately After Launch/Kill

## Problem

After launching a new agent or killing an agent from the Agents tab, the TUI can remain sluggish before `j/k` and other
keypresses feel responsive again.

Existing async improvements already moved major loader I/O off-thread, but several post-action paths still execute
substantial work on the UI thread.

## What I Found

### 1. Kill path still performs blocking disk work synchronously on the UI thread

`src/sase/ace/tui/actions/agents/_killing.py` does synchronous work in `_do_kill_agent(...)` and its delegates:

- `parse_project_file(...)` + status rewrite for hooks/mentors/comments (`_kill_hook_agent`, `_kill_mentor_agent`,
  `_kill_crs_agent`)
- workspace release lookups and writes for workflows
- artifact cleanup (`delete_agent_artifacts(...)`)
- bundle/dismiss persistence (`_persist_dismissed_agent`, `save_dismissed_agents`)

These operations run before control returns to the event loop.

### 2. Post-load apply phase still does heavy work on the UI thread

`src/sase/ace/tui/actions/agents/_loading.py::_apply_loaded_agents(...)` includes non-trivial processing and filesystem
checks on the main thread after async disk load returns:

- orphaned dismissed-entry cleanup (bundle-file existence checks + globs)
- self-healing artifact deletion for dismissed agents
- full filter/fold/order/search/status pipeline
- full list rebuild (`_refresh_agents_display(list_changed=True)`) each refresh

So even when disk reads are threaded, apply/render can still block interaction.

### 3. Full refresh path eagerly updates detail panels synchronously

`_refresh_agents_display(list_changed=True)` in `src/sase/ace/tui/actions/agents/_display.py` always calls
`_apply_agent_detail_update(...)`, which updates prompt/file/thinking panels immediately. Prompt rendering reads
artifact files and builds rich syntax blocks, adding visible latency right when the user expects navigation
responsiveness.

## Goals

1. Return control to the user immediately (single-frame feel) after launch/kill actions.
2. Keep final state correctness (agent killed/launched, statuses persisted, lists accurate).
3. Ensure heavy consistency work still runs, but off the critical interaction path.
4. Preserve current behavior and data model; optimize scheduling and execution placement.

## Non-Goals

- Reworking artifact format/layout.
- Rewriting agent model semantics.
- Removing all sync code everywhere; only hot launch/kill/refresh paths are targeted.

## Implementation Plan

### Phase 0: Instrument and baseline (must-do first)

Add structured timing around:

- `_do_kill_agent` total + sub-steps
- `_load_agents_async` disk phase (already logged) and `_apply_loaded_agents` phase
- `_refresh_agents_display(list_changed=True)` split into list rebuild vs detail update

Acceptance baseline artifact:

- one profiling capture for “launch agent, then kill agent, repeat 5x” with p50/p95 timings.

### Phase 1: Make kill flow optimistic and non-blocking

Refactor kill into two stages:

1. **Immediate UI stage (main thread, fast):**

- remove killed identity from in-memory lists
- refresh list highlight/index
- show toast
- schedule background persistence task

2. **Background persistence stage (worker thread):**

- process-group kill bookkeeping updates
- project-file parse/update for hook/mentor/comment statuses
- workspace release lookups/writes
- bundle persistence and artifact cleanup
- dismissed set persistence

Design constraints:

- Keep idempotent writes so retries are safe.
- Use a per-agent “kill operation in-flight” guard to avoid duplicate persistence writes.
- On persistence failure, emit non-blocking notification and queue a reconciliation refresh.

### Phase 2: Move non-UI parts of `_apply_loaded_agents` off the event loop

Split `_apply_loaded_agents` into:

- **compute/apply-prep worker step** (pure data transforms + filesystem checks/cleanup decisions)
- **main-thread commit step** (assign app state + update widgets)

Move these off-thread:

- orphan detection and bundle existence checks
- dismissed/self-healing artifact cleanup work
- expensive filtering/grouping/search precomputation

Keep on main thread only:

- state assignment to `self.*`
- tab count updates
- widget update calls

### Phase 3: Decouple list refresh from expensive detail rendering

Change `_refresh_agents_display(list_changed=True)` behavior:

- do immediate list/panel/highlight update
- defer detail panel rendering via short debounce (`call_later`/timer), same strategy as j/k path

Rules:

- if selection changed again before detail refresh fires, cancel prior render.
- do not block list interaction waiting for prompt/file panel repaint.

Expected outcome: list navigation remains responsive even while detail panel catches up.

### Phase 4: Coalesce post-action refresh storms

Strengthen existing refresh coalescing by adding source-aware scheduling:

- kill/launch paths should request “latest-only” refresh token
- if one refresh is in progress, keep at most one follow-up
- avoid immediate redundant list rebuilds when optimistic UI already reflects the action

This reduces repeated apply+render bursts right after action-heavy periods.

### Phase 5: Verification and guardrails

Add/extend tests:

- kill path: optimistic removal happens before persistence completion
- refresh coalescing: multiple rapid launch/kill events trigger bounded full refresh count
- detail render debounce: list updates immediately while detail update can lag safely
- regression tests for status persistence correctness (hook/mentor/comment/workflow agents)

Manual validation script:

1. Launch 5 agents quickly from Agents tab.
2. Kill 5 agents quickly (mix running/workflow/hook if possible).
3. During each burst, spam `j/k` and confirm no delayed key backlog.

## Success Criteria

1. `launch` and `kill` actions return UI control in <50 ms p95 on test machine.
2. `_do_kill_agent` main-thread time reduced by >80% vs baseline.
3. `_apply_loaded_agents` main-thread phase reduced to lightweight commit/render only.
4. No regression in persisted statuses, revive behavior, or dismissed-agent filtering.

## Risks and Mitigations

1. **Race between optimistic UI and background persistence**

- Mitigation: operation IDs + final reconciliation refresh; idempotent writes.

2. **Thread-safety issues in shared state**

- Mitigation: worker returns immutable results; only main thread mutates `self` and widgets.

3. **Temporary mismatch if background persistence fails**

- Mitigation: explicit error notification + retryable reconciliation action.

4. **Over-debouncing detail panel making UI feel stale**

- Mitigation: short debounce only (100–200 ms), immediate refresh on explicit navigation pause.

## Proposed File Targets (for implementation phase)

- `src/sase/ace/tui/actions/agents/_killing.py`
- `src/sase/ace/tui/actions/agents/_dismissing.py`
- `src/sase/ace/tui/actions/agents/_loading.py`
- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/actions/event_handlers.py` (if refresh scheduling adjustments are needed)
- targeted tests under `tests/` for kill/loading/display responsiveness semantics
