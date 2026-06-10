---
create_time: 2026-06-10 09:04:08
status: done
prompt: sdd/prompts/202606/tui_perf_memory_migration.md
---
# Migrate `memory/long/tui_jk_baseline.md` → `memory/long/tui_perf.md`

## Context

`memory/long/tui_jk_baseline.md` is a narrow, dated artifact: it records the Phase-1 j/k key-to-paint baseline numbers
from 2026-04-26 (bead sase-u.1) plus phase-specific bench coverage gaps for an epic that has since played out. Since
then, a long series of TUI performance work has landed (instant j/k navigation, fast startup, non-blocking launches,
fast dismiss/kill, debounced detail panels, selective row updates, refresh coalescing), and the _general lessons_ from
that work are what future agents actually need before touching TUI code — not a stale latency table.

This plan replaces the baseline file with a concise `memory/long/tui_perf.md` that captures the recurring performance
gotchas, the established fix patterns in this codebase, and the measurement tooling.

## Research performed

- Read `memory/long/tui_jk_baseline.md` via `sase memory read` (audited).
- Surveyed ~30 perf-related tales in `sdd/tales/` (e.g. `tui_fold_perf.md`, `faster_agents_nav.md`,
  `fix_jk_nav_race.md`, `nonblocking_agent_launch.md`, `fast_dismiss.md`, `prompt_input_lag.md`, `ace_startup_perf.md`,
  `instant_planning_status_refresh.md`).
- Mined prior sase chat transcripts for TUI perf diagnoses (e.g. `sase-gh-main-260608_132237` "full agent refreshes are
  incredibly slow", `sase-tmp_260609_193632` "why block the TUI on launch?", the 260427 laggy-TUI diagnosis, the
  fast_ace_tui_startup implementation chat `sase-ace_run-260609_200405`).
- Surveyed the current perf infrastructure in code: `src/sase/ace/tui/util/perf.py` (`SASE_TUI_PERF`),
  `src/sase/ace/tui/util/trace.py` (`SASE_TUI_TRACE`), `src/sase/ace/tui/util/debounce.py` (`DetailPanelDebouncer`),
  `src/sase/ace/tui/widgets/_agent_list_build.py` (`patch_row` / `try_remove_rows`), `sase ace --profile`, and the
  benches `tests/ace/tui/bench_tui_jk.py` + `tests/perf/bench_tui_trace.py`.

The same handful of root causes recur across all of it: synchronous I/O on the Textual event loop, full rebuilds where a
selective update would do, missing debounce on detail panels, per-keystroke recomputation, stale-state races around
`await`, and guessing at bottlenecks instead of profiling.

## Proposed content of `memory/long/tui_perf.md`

```markdown
# TUI Performance Gotchas

Read this before changing anything that affects `sase ace` TUI responsiveness (navigation, refresh, rendering, startup).
Nearly every TUI perf regression has had the same root cause — synchronous work on the Textual event loop — and the
fixes below are established patterns in this codebase. Reuse them; don't invent new paths.

## Rules

1. **Never block the event loop.** No synchronous disk I/O, JSON parsing, subprocess calls, or `time.sleep` inside
   action/message handlers. Push work off-thread with `asyncio.to_thread()` or `run_worker(..., thread=True)` and
   marshal results back with `call_after_refresh()` / `call_later()`. Do UI mutations (unmount/focus) first, then
   schedule the heavy work.
2. **Re-capture UI state after every `await`.** Selection/tab captured before an await is stale by the time results
   land; re-read the current tab and selected identity before applying results, or j/k silently jumps.
3. **Route refreshes through the existing fast path.** Show cached data instantly (`_refilter_agents()`), then schedule
   a background reload (`_schedule_agents_async_refresh()`); coalesce concurrent requests with loading/pending flags
   (last-request-wins). Don't add new refresh code paths.
4. **Prefer selective updates over full rebuilds.** Full agent-list rebuilds are the most expensive UI operation. Use
   `patch_row()` / `try_remove_rows()` (`src/sase/ace/tui/widgets/_agent_list_build.py`); mutate in-memory state
   optimistically and persist off-thread.
5. **Debounce detail panels, never the highlight.** Highlight moves must paint immediately; expensive detail-panel
   updates go through `DetailPanelDebouncer` (`src/sase/ace/tui/util/debounce.py`, 150 ms) so a held j/k key produces
   exactly one final detail paint.
6. **Cache disk reads keyed by mtime; memoize per-keystroke structures.** Don't re-read files or rebuild navigation stop
   lists on every keypress — invalidate only on structure-changing events. Watch cache keys: too-broad keys serve stale
   rows.
7. **Guard programmatic widget updates.** `OptionList` emits `OptionHighlighted` echoes on programmatic
   `highlighted = X` assignments. Set a guard flag and clear it synchronously (`finally:` block) — clearing via
   `call_later` races the queued echo and causes cursor jumps/freezes.
8. **Respect activity gates.** Defer non-urgent refresh work while the user is mid-navigation (`NavigationGate`, 250 ms
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
```

The dated baseline table and the phase-2..5 bench-coverage-gap notes from the old file are intentionally dropped: the
numbers are regenerable on demand from `tests/ace/tui/bench_tui_jk.py`, and the history is preserved in git and in
`sdd/tales/202604/instant_jk_navigation.md`.

## File changes

1. **Add `memory/long/tui_perf.md`** with the content above.
2. **Delete `memory/long/tui_jk_baseline.md`.**
3. **Update `AGENTS.md`** (Tier 2 section, line ~26): replace the `tui_jk_baseline.md` entry with:

   ```
   **`memory/long/tui_perf.md`**
   Read before changing anything that could affect TUI performance or responsiveness (navigation, refresh,
   rendering, startup).
   ```

   (Entries remain alphabetically ordered. Per repo policy, memory files are only modified with user approval — approval
   of this plan is that approval.)

4. **Update the skill source example** in `src/sase/xprompts/skills/sase_memory_read.md` (line 29), which currently
   demonstrates `sase memory read long/tui_jk_baseline.md`, to reference `long/tui_perf.md` instead. Then regenerate per
   the generated-skills contract: `sase init-skills --force` followed by `chezmoi apply`.

Deliberately untouched: the historical `sase_plan_*.md` archives and `sdd/` tales/research that mention
`tui_jk_baseline` — they are records of past work, not live references. No `src/` or `tests/` code references the memory
file path.

## Verification

- `sase memory read long/tui_perf.md -r "verify migrated memory file resolves"` succeeds; reading the old path fails.
- `sase memory init -c` reports no memory drift.
- Generated `sase_memory_read` skill files no longer mention `tui_jk_baseline`.
- `just install && just check` passes (required since `AGENTS.md` and a skill source change).
