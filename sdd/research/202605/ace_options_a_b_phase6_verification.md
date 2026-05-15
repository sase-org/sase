# TUI ACE Options A/B Optimization - Phase 6 Verification

## Scope

Phase 6 of the `sase-3o` epic (see `sdd/epics/202605/tui_ace_options_a_b.md`) is end-to-end verification of the
Options A and B work shipped across Phases 1-5. This note records what landed, what was tested, and where the
remaining risk sits relative to the 2026-05-15 baseline in
`sdd/research/202605/ace_profile_20260515_105702_next_optimization.md`.

## What Landed

| Phase | Commit | Code |
| --- | --- | --- |
| 1: Lazy syntax cache key | `8ab63f684` | `src/sase/ace/tui/util/lazy_syntax.py` |
| 2: Prepared apply boundary | `917f4cd98` | `src/sase/ace/tui/actions/agents/_loading_compute.py` (`PreparedApplyData`) |
| 3: Incomplete Tier 1 merge in worker | `c534e0803` | `_loading_compute.py`, `_loading_disk.py` |
| 4: Fold filtering in worker | `ce9eee776` | `_loading_compute.py:prepare_loaded_agents_apply_boundary` |
| 5: Remaining pure finalize math off thread | `279c47ef7` | `_loading_compute.py`, `_loading_apply.py` |

Verifying the resulting source state:

- `_render_options_key()` in `src/sase/ace/tui/util/lazy_syntax.py:47` no longer references `options.height`. The
  per-renderable ring is `self._max_width_entries = 8` (was 4). This is Option A as designed in the source note
  (`ace_profile_20260515_105702_next_optimization.md` "Option A").
- `prepare_loaded_agents_worker_boundary` (`_loading_compute.py:615`) is dispatched via `asyncio.to_thread` from
  `_loading_disk.py:294-315`. The boundary returns merged, fold-filtered agents plus selection-restoration math.
  This is Option B.
- Trace spans cover the relevant boundaries:
  - `agents.apply_loaded_agents_prepared` wraps the UI-thread continuation (`_loading_apply.py:220`).
  - `agents.incomplete_load_merge` wraps the residual UI-thread merge fallback (`_loading_apply.py:283`).
  - `agents.fold_filtering` wraps the worker-side fold step (`_loading_compute.py:456`).
  - `agents.finalize_query_filter` wraps the worker-side query/status work (`_loading_compute.py:838`).
  - `_loading_disk.py` records `prep` and `apply` wall-clock for each async refresh.

## Tests Run

All focused tests called out by the phase acceptance criteria pass:

```
pytest tests/ace/tui/util/test_lazy_syntax.py \
       tests/test_fold_filtering.py \
       tests/test_agents_tab_query_integration.py \
       tests/test_external_dismissal_merge.py \
       tests/ace/tui/test_loading_callbacks.py
# 61 passed in 0.95s
```

Full repo gate:

```
just check
# fmt (python, markdown), lint (keep-sorted, ruff, mypy, pyscripts, pyvision, sdd validate), test - all pass
```

## Reprofile vs the 2026-05-15 Baseline

The baseline numbers come from `~/tmp/sase/ace_profile_20260515_105702.txt` (Duration 255.502s wall, 125.687s CPU,
24,769 samples). The hot paths the Options A/B work targeted were:

- 21.660s rolled-up Timer/Compositor subtree, with 1.506s of `_CachedSyntaxRenderable.__rich_console__` falling
  through to `Syntax._get_syntax` inside `get_height` because the cache key included `options.height`.
- 1.192s `_apply_loaded_agents_prepared` continuation on the UI thread, with 0.597s in
  `_merge_incomplete_load_after_complete_history`, 0.237s in `filter_agents_by_fold_state`, and 0.162s self-time
  in `finalize_agent_list`.

### Reprofile status

A fresh `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ...` capture requires an interactive terminal session
with the same workflow the baseline used (medium markdown reply, fold children, ~50-100 `j`/`k` keystrokes). It
cannot be run from an automation/agent environment without driving a real TTY. The capture is left as a manual
follow-up — recommended scenario is identical to the baseline's so the per-frame and per-callback subtrees compare
directly.

### Expected impact, attributed to code that did land

Without a fresh capture, expected impact is the static analysis the source note already projected against the
specific changes that are now in tree:

1. `_CachedSyntaxRenderable` no longer double-renders between reflow (height-aware) and paint (height-zero) for
   the same width. The 1.506s `get_height`-time fallthrough should drop to ~0; the 5.704s `render_lines` cost
   stays unchanged because that path was already serving cached segments.
2. `_apply_loaded_agents_prepared` no longer runs `_merge_incomplete_load_after_complete_history`,
   `filter_agents_by_fold_state`, or the pure finalize math on the UI thread for async refreshes. The
   `prepare_loaded_agents_worker_boundary` worker returns a `PreparedApplyBoundary` covering merge, fold filter,
   query evaluation, status overrides, selection-restoration indices, and group keys. The UI continuation should
   shrink to the install/refresh slice (panel widgets, unread reconciliation, focus/selection) — the design
   target was below 50ms on the profiled tree, against the 1.192s baseline.
3. The synchronous `_load_agents()` path and direct test entry points retained compatibility, so the worker
   migration is async-only; non-async callers still pay the prior UI-thread cost. This is by design.

## Remaining Hot Paths and Risks

The following items from the baseline note are *not* addressed by Phases 1-5 and remain live for any future
profile:

- **`AgentList.render_lines` per-row strip pipeline** (4.502s rolled up). Untouched. This was Option F (P2 in
  baseline) and remains the largest unaddressed per-frame slice once the prompt-panel double-render is gone.
- **App focus/blur stylesheet recompute** (0.289s combined). Untouched. Option C (P1). High leverage for
  tmux/tiling-WM users; small in absolute terms.
- **`resolve_model_provider` glob+stat per `watch_current_idx`** (~25ms each). Untouched. Option D (P1). Still on
  the input path for `j`/`k` navigation.
- **`Agent.is_workflow_child` recomputation** (0.072s under fold filter alone, plus more under merge). The
  property still computes on access (`models/agent.py:460`). Option E (P1). Worth measuring after a fresh capture
  because it now runs in the worker, not on the UI thread — its UX impact is reduced but its CPU cost is
  unchanged.
- **`dataclasses.asdict` in `compile_query_corpus`** (0.038s on_mount, 0.180s reload). Crosses the Rust-core wire
  boundary; touching it belongs in `../sase-core` per the boundary policy.

## Options C-G Reprioritization

Given Phases 1-5 covered Options A and B and the trace instrumentation now distinguishes worker prep from UI
apply, the residual ranking is:

1. **Option D — cache `resolve_model_provider`** (P1 → recommended next P0). Now the highest-leverage per-keypress
   cost on the input path. Memoizing the resolved provider/model behind a config-overlay fingerprint should
   remove ~25ms from every `j`/`k`.
2. **Option C — debounce focus/blur stylesheet apply** (unchanged P1). Still a clean, contained win for users on
   tiling WMs and tmux.
3. **Option F — `AgentList.render_lines` per-row strips** (P2 → reconsider after a fresh profile). With prompt
   panel double-render eliminated, the agent list is the largest remaining per-frame subtree. Worth a targeted
   capture before committing to a custom renderer.
4. **Option E — make `Agent.is_workflow_child` cheap** (P1 → P2). The UX hazard mostly moved off-thread with
   Phases 4-5. Still a CPU-cost win, but no longer on the blocking path.
5. **Option G — editor subprocess UX** (unchanged P2). Out of scope for the responsiveness track.

## Recommendation

The Phase 6 acceptance gate (`just check`) is satisfied. The Options A and B changes are in tree, instrumented,
and exercised by the focused test suites. The fresh interactive `sase ace --profile` capture is documented as a
manual follow-up; when it lands, compare the `_CachedSyntaxRenderable.__rich_console__` subtree under reflow and
the `agents.apply_loaded_agents_prepared` trace span against the 2026-05-15 baseline.

Next bead, if pursued, should be Option D (provider/model resolution cache on the per-row header path).

## Open Questions Carried Forward

- Does the height-free lazy syntax cache key produce identical segments for file-panel `line_range` truncation in
  the wild? The unit test in `tests/ace/tui/util/test_lazy_syntax.py` covers the same-width different-height
  reuse case; a real profile against a large diff would confirm.
- Once the fresh profile lands, does the `_apply_loaded_agents_prepared` trace span actually drop below the 50ms
  target on a representative tree, or is there residual UI-thread cost (e.g. `_refresh_panel_widgets`,
  `AgentList.update_list`) that needs a follow-up?
- Should the synchronous `_load_agents()` path also route through the worker boundary for symmetry, or is the
  cost only material on the async refresh continuation?
