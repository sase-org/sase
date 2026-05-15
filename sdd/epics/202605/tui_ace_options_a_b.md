---
create_time: 2026-05-15 11:26:38
status: done
bead_id: sase-3o
tier: epic
prompt: sdd/prompts/202605/tui_ace_options_a_b.md
---
# TUI ACE Options A/B Optimization Plan

## Goal

Implement the two P0 recommendations from `sdd/research/202605/ace_profile_20260515_105702_next_optimization.md`:

1. Option A: make `_CachedSyntaxRenderable` reuse syntax-highlighted segments across reflow and paint passes when
   width-relevant render options are unchanged.
2. Option B: move post-load merge/fold/finalize preparation out of the Textual UI thread so async agent refresh apply
   continuations stay short.

The work is intentionally split into phases that can be handed to distinct agent instances. Each phase should leave the
repo passing its focused tests and should avoid broad unrelated refactors.

## Phase 1: Lazy Syntax Cache Key

Scope:

- Update `src/sase/ace/tui/util/lazy_syntax.py` so `_render_options_key()` excludes `options.height`, which is not
  width/input state for the syntax output used by ACE prompt/file rendering.
- Increase `_CachedSyntaxRenderable`'s per-renderable option-entry ring from 4 to 8 to reduce width-history churn while
  keeping memory bounded.
- Add focused tests in `tests/ace/tui/util/test_lazy_syntax.py`:
  - same content and same width with different heights hits the cached render once;
  - rendered segments are identical across those heights;
  - different width still produces a distinct render.

Acceptance:

- `pytest tests/ace/tui/util/test_lazy_syntax.py`
- Existing lazy syntax behavior remains unchanged for caps, line ranges, and non-cached `Syntax` returns.

Handoff:

- Later phases can assume prompt-panel cached renderables are less likely to double-render during reflow plus paint.

## Phase 2: Prepared Apply Boundary and Trace Coverage

Scope:

- Introduce explicit pure-data snapshot/result types for post-load agent apply preparation near
  `src/sase/ace/tui/actions/agents/_loading_compute.py`.
- Keep behavior synchronous for this phase, but isolate the code that will move to a worker:
  - incomplete Tier 1 merge after complete history;
  - fold-state filtering;
  - save-unfiltered `_agents_with_children` payload;
  - selection restoration inputs needed by the UI apply step.
- Add timing/debug trace spans around:
  - worker prep;
  - `_apply_loaded_agents_prepared`;
  - incomplete-load merge;
  - fold filtering;
  - final display refresh.
- Add tests that compare current `_apply_loaded_agents_prepared` output against the new prepared boundary for
  representative data.

Acceptance:

- Focused loading/fold tests pass:
  - `pytest tests/test_fold_filtering.py tests/test_agents_tab_query_integration.py tests/test_external_dismissal_merge.py`
- No worker thread is introduced yet, so this phase should be behavior-preserving.

Handoff:

- Later phases should move only the newly isolated pure helper calls into `asyncio.to_thread`, not rewrite the UI
  mutation path.

## Phase 3: Move Incomplete Tier 1 Merge Into Worker

Scope:

- Move `_merge_incomplete_load_after_complete_history()` semantics into the pure preparation helper and call it from
  `_load_agents_async` before returning to the UI-thread apply continuation.
- Snapshot all app-owned state needed by the worker before dispatch:
  - current cached `_agents_with_children`;
  - `_dismissed_agents`;
  - `_agents_seen_complete_history`;
  - `hide_non_run_agents`;
  - `load_state`.
- Keep UI thread responsible for mutating app attributes and widgets.
- Preserve sync `_load_agents()` and direct test entry points by either using the same pure helper inline or retaining
  compatibility shims.

Tests to add or strengthen:

- incomplete Tier 1 load after a complete-history load preserves historical rows;
- newly discovered Tier 1 roots appear before cached history in the same order as incoming Tier 1 rows;
- newly discovered children attach to both new and cached parents;
- dismissed suffix and `(cl_name, suffix)` behavior matches current merge;
- RUNNING vs WORKFLOW and same-PID dedup still reattach children correctly.

Acceptance:

- `pytest tests/test_external_dismissal_merge.py tests/test_fold_filtering.py tests/test_agents_tab_query_integration.py`
- A local timing trace shows `_apply_loaded_agents_prepared` no longer includes the incomplete-load merge cost on the
  async path.

Handoff:

- Fold filtering may still run on the UI thread after this phase; do not combine with Phase 4 unless the phase owner
  explicitly broadens scope.

## Phase 4: Move Fold Filtering Into Worker

Scope:

- Move `filter_agents_by_fold_state()` into the same async worker preparation stage for async loads.
- Snapshot fold state in a pure form rather than passing live `FoldStateManager` if that manager is mutable and
  UI-owned.
- Return both:
  - the folded visible agent list;
  - `fold_counts`;
  - the unfiltered list that should be assigned to `_agents_with_children` when `save_unfiltered=True`.
- Keep query filtering, status overrides, unread reconciliation, group registry GC, and widget refresh on the UI thread
  unless Phase 5 has started.

Tests:

- Fold levels `COLLAPSED`, `EXPANDED`, and `FULLY_EXPANDED` produce the same visible list and counts through the
  prepared path as through `filter_agents_by_fold_state()`.
- Orphan children and hidden-only parents are filtered identically.
- Stale-result protection: if fold state changes while a worker is in flight, the result is discarded or recomputed
  before apply.

Acceptance:

- `pytest tests/test_fold_filtering.py tests/test_agents_tab_query_integration.py`
- Async refresh apply timing shows fold filtering outside `_apply_loaded_agents_prepared`.

Handoff:

- After this phase, async apply should mostly install precomputed lists and perform UI-owned filters/selection/widget
  work.

## Phase 5: Move Remaining Pure Finalize Math Off Thread

Scope:

- Extract and move the remaining pure parts of `finalize_agent_list()` into the preparation stage where safe:
  - structured query evaluation using the already-built `AgentContentSearchIndex`;
  - status override application plan;
  - selection restoration index math;
  - group keys for registry GC.
- Keep these on the UI thread:
  - parsing errors and `notify()`;
  - mutating app dictionaries/sets;
  - unread notification reconciliation;
  - `AgentList`/panel/widget refresh;
  - `current_idx` assignment and focus-restoration calls.
- Add an explicit stale-prep generation token that covers mutable UI inputs used by the worker: selected identity/row,
  fold snapshot, query string/cache identity, status overrides, grouping mode, and current hide flags.

Tests:

- Selection is restored by identity when the selected agent survives.
- Selection falls back to the prior visual row when the selected agent disappears.
- Off-tab `_agents_last_idx` and `_agents_last_identity` remain consistent.
- Query parse failure still warns on the UI thread and does not filter.
- Content-query matching still preserves workflow children.

Acceptance:

- `pytest tests/test_agents_tab_query_integration.py tests/ace/tui/test_loading_callbacks.py`
- No test uses live widgets from worker-prep code.

Handoff:

- This phase should leave `_apply_loaded_agents_prepared` as a short install-and-refresh continuation for async loads.

## Phase 6: End-to-End Verification and Profile Cleanup

Scope:

- Run focused tests from prior phases, then `just install` if needed and `just check`.
- Reprofile with the same scenario as the source note:
  - `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ...`
- Compare against the 2026-05-15 baseline:
  - `_CachedSyntaxRenderable.__rich_console__` should no longer double-render between height-measure and paint for the
    same width;
  - `_apply_loaded_agents_prepared` should be below the target continuation budget, ideally under 50ms on the profiled
    tree.
- Update or add a short research note under `sdd/research/202605/` with before/after numbers and any remaining hot
  paths.

Acceptance:

- `just check`
- Profile note documents remaining risk and whether Options C-G should be reprioritized.

## Cross-Phase Constraints

- Do not mutate memory files without user approval.
- Use the existing Rust core boundary: keep presentation-only TUI code here; do not reimplement shared backend behavior.
- Worker helpers must operate on explicit snapshots and return plain data. They must not read live Textual app
  attributes, query widgets, notify, or mutate app state.
- Preserve last-request-wins refresh coalescing and stale-result behavior.
- Avoid changing visual behavior unless the phase explicitly owns a visual test update.
