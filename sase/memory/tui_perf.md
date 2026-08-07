---
type: long
parent: AGENTS.md
description:
  Read before changing anything that affects TUI performance or responsiveness
  (navigation, refresh, rendering, startup), and before diagnosing TUI freezes or
  stalls.
---

# TUI Performance Gotchas

TUI perf regressions usually come from slow work reaching the UI thread or Textual's
serial app message pump. Reuse these established fixes; don't invent new paths.

## Rules

1. **Never block the event loop.** No synchronous disk I/O, JSON parsing, subprocess
   calls, or `time.sleep` in action/message handlers or render paths. Push work
   off-thread (`asyncio.to_thread()`, `run_worker(..., thread=True)`) and marshal thread
   results back with `call_from_thread`. Do UI mutations (unmount/focus) first, then
   schedule the heavy work.
2. **Off the event loop is NOT off the pump.** Textual serially awaits async
   `call_later` / `call_after_refresh` / `set_timer` / `set_interval` callbacks; any
   slow await, even `asyncio.to_thread()`, blocks key events. Keep pump/timer callbacks
   thin and synchronous; launch slow bodies with `spawn_pump_free_task()`
   (`src/sase/ace/tui/util/pump_tasks.py`) and cancel them at teardown with
   `cancel_pump_free_tasks()`. Preserve coalescing guards (scheduled/running/pending),
   releasing them if spawning fails. After a conversion, re-sweep all four APIs for slow
   async callbacks; the July 2026 epic missed two at phase seams.
3. **Run slow user-initiated operations as tracked background tasks** (agent launches,
   kill/dismiss persistence, ChangeSpec actions): `_submit_tracked_task()` /
   `_submit_background_task()` (`src/sase/ace/tui/actions/task_actions.py`), not
   fire-and-forget coroutines. They appear in the task indicator/Task Queue (`t`), dedup
   submissions, count at quit, and leave records. Shape (see `LaunchTaskMixin` /
   `CleanupTaskMixin`): optimistic UI → sync worker returning a typed outcome →
   UI-thread `on_complete` effects.
4. **Re-capture UI state after every `await`.** Selection/tab captured before an await
   is stale when results land (pump-free tasks interleave); re-read the current tab and
   selected identity before applying, or j/k silently jumps.
5. **Route refreshes through the existing fast path.** Show cached data instantly
   (`_refilter_agents()`), then schedule a background reload
   (`_schedule_agents_async_refresh()`); coalesce concurrent requests with
   loading/pending flags (last-request-wins). Don't add new refresh code paths.
6. **Prefer selective updates over full rebuilds.** Full agent-list rebuilds are the
   most expensive UI operation. Use `patch_row()` / `try_remove_rows()`
   (`src/sase/ace/tui/widgets/_agent_list_build.py`); mutate in-memory state
   optimistically and persist off-thread.
7. **Debounce detail panels, never the highlight.** Highlight moves paint immediately;
   detail-panel updates go through `DetailPanelDebouncer`
   (`src/sase/ace/tui/util/debounce.py`, 150 ms).
8. **Cache disk reads keyed by mtime; render paths never stat/glob.** Don't re-read
   files or rebuild structures per keypress. `current_config_token()` is time-gated and
   model-alias resolution memoized per token — one render-path glob froze the UI for 13
   s. Tests that edit config call `clear_config_cache()`. Over-broad cache keys serve
   stale rows.
9. **Keep startup off data-scaled work.** First paint never waits on O(archive) work:
   detect stale artifact-index schema with cheap metadata, serve the bounded fallback
   scan, rebuild in the background, then coalesce a follow-up refresh. Don't add work
   before the startup stopwatch ends.
10. **Periodic ticks revalidate; recomputes get a longer cadence.** Pollers must not
    network/full-recompute every tick (update checks did when tick interval equaled
    cache TTL). Revalidate cached snapshots on ticks; recompute on a separate, much
    longer interval.
11. **Keystroke paths are read-only and prompt-free.** Completion/typing paths must
    never call side-effectful resolvers (provider `resolve_ref` clones repos and
    allocates project records), spawn subprocesses that can prompt interactively (a git
    credential prompt seizes the tty and freezes the TUI), or take unbounded
    shared-store locks (bound lock waits in Rust core; degrade with a toast).
12. **Guard programmatic widget updates.** `OptionList` emits `OptionHighlighted` echoes
    on programmatic `highlighted = X` assignments. Set a guard flag and clear it
    synchronously (`finally:`) — clearing via `call_later` races the queued echo and
    causes cursor jumps/freezes.
13. **Respect activity gates.** Defer non-urgent refresh work while the user is
    mid-navigation (`NavigationGate`, 250 ms window) or typing in the prompt input.

## Measure, don't guess

Perceived causes are usually wrong; profile before and after.

- **Freeze forensics first:** the always-on watchdog
  (`src/sase/ace/tui/util/stall_watchdog.py`) writes loop/pump stalls with asyncio task
  stacks and recovery rows to `~/.sase/logs/tui_stalls.jsonl`, naming the stuck await.
  Lower `SASE_TUI_STALL_*` / `SASE_TUI_PUMP_STALL_*` thresholds for short verification
  runs.
- `sase ace --profile [path]` — pyinstrument profile of the event loop.
- `SASE_TUI_PERF=1` — per-j/k key-to-paint JSONL at `~/.sase/perf/tui_jk.jsonl`; target
  p95 < 16 ms on every tab.
- `SASE_TUI_TRACE=1` — hot-path span JSONL at `~/.sase/perf/tui_trace.jsonl`
  (`src/sase/ace/tui/util/trace.py`).
- Benches (p50/p95/max tables): `pytest -s -m slow tests/ace/tui/bench_tui_jk.py` and
  `pytest -s -m slow tests/perf/bench_tui_trace.py`. Full capture/compare recipes:
  `docs/perf_runbook.md` and `tests/perf/README.md`.
