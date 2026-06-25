---
create_time: 2026-06-25 07:01:12
status: done
prompt: sdd/prompts/202606/agent_detail_header_offthread_diff.md
---
# Plan: Move agent detail-header live diff off the Textual event loop

## Problem & context

The ACE TUI hard-freezes for up to the watchdog's 5 s threshold during normal Agents-tab navigation. The consolidated
research (`sdd/research/202606/tui_slowdown_consolidated_20260625.md`) traced every non-editor watchdog stall on
2026-06-25 to one synchronous chain:

```
DetailMixin._fire_debounced_detail_update
  -> AgentDetail.update_display
  -> AgentPromptPanel.update_display
  -> build_detail_header_summary          # runs ON the event loop
  -> agent_delta_entries -> get_agent_diff
  -> provider.diff_with_untracked -> subprocess.run   # git diff / ls-files
```

`build_detail_header_summary(agent)` is invoked synchronously from `AgentPromptPanel._update_display_impl` (in
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py`). On a live diff cache miss it shells out to `git` with
a 10 s timeout, blocking the event loop and tripping the watchdog. The same function also does the agent's artifact
listing (`agent_artifact_paths`, thousands of `os.path.exists` stats) and disk-backed context loads (memory reads, skill
uses, opened-workspace markers) on the event loop.

This violates the project's top TUI-perf rule ("never block the event loop; no synchronous subprocess/disk I/O in
handlers"; see `memory/tui_perf.md`). The research's **Phase 1** is the recommended, narrowest fix and is exactly what
the user is asking for: move the expensive header enrichment — above all the live `git diff` — into a generation-gated
background worker, and render only cached, event-loop-safe state synchronously.

## Goal

After this change, selecting or navigating to an agent never runs `git diff` / `diff_with_untracked` / `subprocess.run`
/ `agent_artifact_paths` on the Textual event loop. The header paints immediately from cheap cached state; the Deltas /
Artifacts / Context sections fill in a frame or two later when the worker completes, and stale worker results never
repaint after the selection moves on.

This is a presentation-layer concern (Textual widget orchestration and an in-process cache), so it stays in this repo.
It does not cross the Rust core boundary: the underlying `diff_with_untracked` and artifact-index calls are unchanged —
we only change _which thread_ invokes them.

## Key discovery that makes this clean

`build_header_text(agent, summary=None)` already renders the full header **without** the expensive sections: xprompts,
deltas, artifacts, and the memory/skill/opened-workspace context blocks are all guarded by
`if not cheap and summary is not None`, and the `Bead:` row falls back to the O(1), event-loop-safe
`cached_bead_display(agent)`. So "no summary yet" is already a cheap, correct render — the expensive sections are simply
omitted until enrichment lands. No new placeholder text is required.

We also already have three established worker patterns in the same widget to mirror:

- **Bead** (`start_agent_bead_display_resolve` in `_agent_display_async.py`): three-state cache + `should_resolve_*`
  gate + off-thread resolve + re-render via `_update_display_impl` when `is_current`.
- **Linked deltas** (`start_agent_linked_delta_refresh`, same file): cached accessor read synchronously, expensive
  compute off-thread, re-render + `LinkedDeltasRefreshed` message on completion.
- **Workflow detail** (`start_workflow_detail_render` in `_workflow_display.py`): computes a whole renderable off-thread
  and applies `worker.result` when current; already called with explicit `generation`/`is_current` from both
  `AgentDetail` and the zoom modal.

The fix is to add a fourth worker of the same shape for the detail-header summary, and the synchronous render reads a
cached summary instead of building one inline.

## Design

### 1. Detail-header enrichment worker (primary change)

Add an `AgentPromptPanel` worker that computes the entire `_DetailHeaderSummary` off-thread, mirroring the linked-delta
/ workflow-detail workers in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py`:

- `start_agent_detail_header_enrichment(agent, *, generation, attempt_view_mode, attempt_pinned_number, is_current)` —
  explicit params like `start_workflow_detail_render` (so both the main panel and the zoom modal can drive it). Guard on
  `getattr(self, "run_worker", None)` so mixin-only test doubles (e.g. the `_FakePanel` in
  `test_agent_display_header_only.py`) don't crash. Apply the same supersede/cancel discipline the linked-delta worker
  uses: an in-flight request for the _same_ identity/view just updates the stored request; a different identity cancels
  the running worker.
- The worker body runs `build_detail_header_summary(agent)` — this is where the `git diff` subprocess, artifact listing,
  and context disk reads now execute, off the event loop.
- `_apply_agent_detail_header_enrichment_result(worker, state)` runs on the event loop via the existing
  `on_worker_state_changed` MRO chain (extend the chain in `_agent_display_async.py`, which already fans out to the bead
  and linked-delta appliers). On `WorkerState.SUCCESS` **and** `is_current(...)`: store `worker.result` in a panel-level
  summary cache keyed by `agent.identity` (with a monotonic timestamp), then call `self._update_display_impl(agent)` to
  repaint. Because the result is applied on the event loop, the cache is only ever written there — no cross-thread cache
  mutation, no extra lock.

### 2. Synchronous render reads cached summary

In `AgentPromptPanel._update_display_impl` (`_agent_display_render.py`), replace the inline
`summary = build_detail_header_summary(agent)` with a cached lookup:

- **Fresh hit** (entry exists and is younger than the diff TTL): pass it to `build_header_text` and
  `publish_opened_workspaces_cache`.
- **Stale hit** (older than `DIFF_CACHE_TTL_SECONDS` = 1.0 s, the live-diff cache's own TTL): render the stale summary
  immediately (no flicker) _and_ start a refresh worker — the "show cached instantly, refresh in background" rule.
- **Miss**: render with `summary=None` (expensive sections omitted) and start the worker.

Add a thin `_start_agent_detail_header_enrichment_from_context(agent)` wrapper (reads
`self._agent_detail_render_context`, gated on `attempt_pinned_number is None` since pinned attempts show archived data,
not live diff) and call it from `AgentDisplayMixin.update_display` next to the existing bead/linked-delta starts. Add a
matching `_cancel_agent_detail_header_enrichment_worker_for_selection_change(agent)` and call it from
`update_header_only` alongside the two existing cancels.

Bound the summary cache (small LRU, e.g. matching the bead cache's 256-entry ceiling) and clear it in `show_empty()`.

### 3. Zoom modal parity (regression guard)

`zoom_panel_modal.py::_refresh_metadata` renders a _separate_ `AgentPromptPanel` and, for non-workflow agents, calls
`panel.update_display(agent)` **without** setting a render context — so today its bead/linked-delta from-context
starters already no-op there, and it relies on the now-removed synchronous summary build. To avoid regressing the zoom
metadata view (it would otherwise lose Deltas / Artifacts and never refresh), set the render context in that else-branch
(mirroring the `is_current`/generation the workflow branch already builds) before `panel.update_display(agent)`. This
brings the zoom panel to parity and lets all three workers run there uniformly — a strict improvement.

### 4. Hints path

`update_display_with_hints` (`_agent_display_hints.py`) also calls `build_detail_header_summary` synchronously. It is a
one-shot, user-initiated `f`-key render with no incremental re-render hook, and by the time hints are requested the
detail panel is already showing (diff cache warm). Have it prefer the panel's cached summary and fall back to a
synchronous build only on a miss, so the common case is cheap while hint correctness (full data in one pass) is
preserved. Call this out as an intentional, scoped decision.

## Regression checks

Model new tests on the existing async-worker tests (`test_agent_display_bead_metadata.py`,
`test_agent_display_header_only.py`):

1. **No event-loop subprocess/disk.** Driving `AgentPromptPanel.update_display` on a mixin-only panel must not
   synchronously call `get_agent_diff` / `diff_with_untracked` / `subprocess.run` / `agent_artifact_paths`; assert those
   run only from the worker.
2. **Stale results don't repaint.** With `is_current` returning False (selection advanced / generation bumped), a
   completed worker must not repaint.
3. **Cold → enriched.** A cold render omits the Deltas / Artifacts sections; after the worker completes and re-renders,
   the sections appear (mirrors the bead cold→confirmed test).
4. **TTL reuse.** Re-selecting the same identity within the TTL reuses the cached summary (no second
   `build_detail_header_summary`).
5. **Test migration.** Audit tests that call `panel.update_display(agent)` and assert deltas/artifacts appear
   synchronously (e.g. in `test_agent_deltas.py`, `test_agent_display_artifact_metadata.py`); convert them to build the
   summary directly or to pump the worker. Bounded, known cost.
6. **Manual / bench.** Re-run a tmux navigation burst and confirm no new `~/.sase/logs/tui_stalls.jsonl` stack contains
   `get_agent_diff` / `diff_with_untracked` / `agent_artifact_paths`; confirm the zoom metadata panel still shows
   Deltas/Artifacts; check key-to-paint with `SASE_TUI_PERF=1` and `pytest -s -m slow tests/ace/tui/bench_tui_jk.py`.

Run `just check` before handing back.

## Out of scope

Phases 2–4 of the research (watcher-path classifier broad-load fix, broad-load cost reduction, editor-wait
classification) are deliberately excluded. This plan is the research's recommended _first_ step — the narrowest fix for
the only non-editor 5 s freezes — and leaves those as clear follow-ons.

## Files in play

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py` — new worker, cancel helper, applier,
  `on_worker_state_changed` chaining.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py` — cached summary lookup in `_update_display_impl`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` — start/cancel wiring in `update_display` /
  `update_header_only`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — summary cache type/helpers (the summary builder
  itself is unchanged; it just runs in the worker).
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — render context for the non-workflow metadata branch.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py` — prefer cached summary.
- Tests under `tests/ace/tui/widgets/` — new worker tests + migration.
