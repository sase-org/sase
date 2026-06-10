---
description:
  Read before changing anything that affects TUI performance or responsiveness (navigation, refresh, rendering,
  startup).
---

# TUI Performance Gotchas

Nearly every TUI perf regression has had the same root cause — synchronous work on the Textual event loop — and the
fixes below are established patterns in this codebase. Reuse them; don't invent new paths.

## Rules

1. **Never block the event loop.** No synchronous disk I/O, JSON parsing, subprocess calls, or `time.sleep` inside
   action/message handlers. Push work off-thread with `asyncio.to_thread()` or `run_worker(..., thread=True)` and
   marshal results back with `call_after_refresh()` / `call_later()`. Do UI mutations (unmount/focus) first, then
   schedule the heavy work.
2. **Run slow user-initiated operations as tracked background tasks.** Off-thread is not enough for multi-second work
   (agent launches, kill/dismiss persistence, ChangeSpec actions): route it through `_submit_tracked_task()` /
   `_submit_background_task()` (`src/sase/ace/tui/actions/task_actions.py`) instead of ad hoc
   `call_later(asyncio.to_thread(...))` fire-and-forget coroutines. Tracked tasks appear in the top-right task indicator
   and the Task Queue modal (`t`; live output, `K` kills), dedup duplicate submissions, are counted by the
   quit-confirmation flow so in-flight work isn't silently lost, and leave inspectable success/error records. Follow the
   shape in `LaunchTaskMixin` / `CleanupTaskMixin` (`_launch_tasks.py`, `_cleanup_tasks.py`): optimistic UI stage first,
   synchronous worker body returning a typed outcome, completion effects applied on the UI thread in `on_complete`.
3. **Re-capture UI state after every `await`.** Selection/tab captured before an await is stale by the time results
   land; re-read the current tab and selected identity before applying results, or j/k silently jumps.
4. **Route refreshes through the existing fast path.** Show cached data instantly (`_refilter_agents()`), then schedule
   a background reload (`_schedule_agents_async_refresh()`); coalesce concurrent requests with loading/pending flags
   (last-request-wins). Don't add new refresh code paths.
5. **Prefer selective updates over full rebuilds.** Full agent-list rebuilds are the most expensive UI operation. Use
   `patch_row()` / `try_remove_rows()` (`src/sase/ace/tui/widgets/_agent_list_build.py`); mutate in-memory state
   optimistically and persist off-thread.
6. **Debounce detail panels, never the highlight.** Highlight moves must paint immediately; expensive detail-panel
   updates go through `DetailPanelDebouncer` (`src/sase/ace/tui/util/debounce.py`, 150 ms) so a held j/k key produces
   exactly one final detail paint.
7. **Cache disk reads keyed by mtime; memoize per-keystroke structures.** Don't re-read files or rebuild navigation stop
   lists on every keypress — invalidate only on structure-changing events. Watch cache keys: too-broad keys serve stale
   rows.
8. **Guard programmatic widget updates.** `OptionList` emits `OptionHighlighted` echoes on programmatic
   `highlighted = X` assignments. Set a guard flag and clear it synchronously (`finally:` block) — clearing via
   `call_later` races the queued echo and causes cursor jumps/freezes.
9. **Respect activity gates.** Defer non-urgent refresh work while the user is mid-navigation (`NavigationGate`, 250 ms
   window) or typing in the prompt input.

## Measure, don't guess

Profile before and after — perceived causes are frequently wrong (e.g. an 11.6 s startup that "felt like slow rendering"
was 39% one synchronous artifact-index sync).

- `sase ace --profile [path]` — pyinstrument profile of the event loop.
- `SASE_TUI_PERF=1 sase ace` — per-j/k key-to-paint JSONL at `~/.sase/perf/tui_jk.jsonl` (`SASE_TUI_PERF_PATH`
  overrides). Target: p95 < 16 ms on every tab.
- `SASE_TUI_TRACE=1 sase ace` — hot-path span traces (`src/sase/ace/tui/util/trace.py`).
- Benches (print p50/p95/max tables): `pytest -s -m slow tests/ace/tui/bench_tui_jk.py` and
  `pytest -s -m slow tests/perf/bench_tui_trace.py`.
