---
create_time: 2026-05-14 23:07:46
status: done
prompt: sdd/prompts/202605/diagnose_slow_tui.md
---
# Diagnose and Fix Slow `sase ace` TUI

## Problem

The `sase ace` TUI is reportedly "insanely slow" — keyboard input (especially `j`/`k` navigation in the Agents tab)
feels unresponsive. The slowdown post-dates a rapid burst of "off the UI thread" refactors and the new Claude tool-call
hook collector that landed in the past few days (commits `8c79e37d0` → `db1bd45f0`).

Most of the recent work intentionally _moved_ expensive work off the event loop, but two of the new code paths
introduced fresh **synchronous disk I/O on the UI thread** that runs on every navigation. The new Claude PreToolUse /
PostToolUse hook then continuously perturbs the files those paths inspect, so the cost compounds while Claude agents are
actively executing tools.

## Primary hypothesis (smoking gun)

`AgentToolsPanel._update_display_impl` (in `src/sase/ace/tui/widgets/tools_panel.py:240-275`) was changed in `fbc5deedc`
(sase-3j.3) to call `_max_tool_calls_mtime_ns(agent)` **on the Textual event loop** every time the tools panel updates:

```python
current_mtime = _max_tool_calls_mtime_ns(agent)
file_changed = current_mtime > cache_entry.artifact_mtime_ns
```

That helper calls `discover_related_tool_artifact_dirs(agent, artifacts_dir)` which:

1. Runs `parent.iterdir()` on the agent's artifacts parent directory (`src/sase/ace/tui/tools/reader.py:130-162`).
2. For each sibling directory, opens **two JSON files** (`agent_meta.json` and `done.json`) and parses them
   (`reader.py:467-482`, `_combined_artifact_metadata`).
3. Then `stat()`s a `tool_calls.jsonl` per directory.

`update_display` for the tools panel is invoked from `AgentDetail._update_display_impl` on every debounced detail
refresh — that's every `j`/`k` keystroke once the debounce settles. With dozens of sibling agent runs and many JSON
reads per row, this is a multi-millisecond blocking call on the event loop on every move.

The new SASE Claude PreToolUse/PostToolUse hook (`f50ab2e42`, `8c79e37d0`) writes to `tool_calls.jsonl` after **every
tool call** in every running Claude agent. So whenever Claude is actively working:

- The file mtime advances constantly.
- `file_changed` is `True` more often.
- The tools panel re-spawns its background read worker.
- `read_tool_calls_for_agent` reopens the file and re-parses every line, again walking siblings via
  `discover_related_tool_artifact_dirs`.

The combination is "everything is slow", especially while one or more Claude runs are in flight.

## Secondary hypothesis (file lock contention)

`_append_jsonl` in `src/sase/llm_provider/_tool_calls.py:802-813` takes an exclusive `fcntl.flock()` per write. Each
Claude tool call spawns the `sase_claude_tool_hook` subprocess; with many concurrent Claude agents sharing the same
artifacts root, those subprocesses can serialize on the lock. This doesn't directly block the TUI, but it makes hook
writes burst into clumps that further amplify hypothesis #1.

## Tertiary hypothesis (existing 1-Hz row patch)

`EventActivityMixin._on_countdown_tick` (`src/sase/ace/tui/actions/_event_activity.py:15-56`) fires every second and
calls `_patch_agent_runtime_rows()`, which patches every visible row whose runtime suffix can change. This pre-dates the
regression but compounds with #1: a slow tools-panel update on j/k followed by a 1-second row repaint cycle means the
event loop stays starved.

## What I am _not_ yet changing

Recent refactors that intentionally moved work off-thread (`98b055a3d`, `dafda5c76`, `8df590085`, `7d7f695ca`,
`db1bd45f0`) look correct and are not in scope. We will leave them alone unless trace data implicates them.

## Diagnostic step (do this first)

1. Enable `SASE_TUI_TRACE=1` and run `sase ace` while a Claude agent is actively executing tool calls.
2. Navigate with `j`/`k` for ~20 keystrokes, then quit.
3. Inspect `~/.sase/perf/tui_trace.jsonl` for the slowest spans. We expect `widget.tools_panel.update_display` to
   dominate, with multi-millisecond `duration_ms` on every navigation.
4. As a cheap sanity check, also `wc -l` the agent's `tool_calls.jsonl` to confirm the hook is writing actively, and
   `ls` the artifacts parent to see how many sibling dirs the `discover_related_tool_artifact_dirs` walk has to
   traverse.

If the trace confirms the hypothesis, proceed with the fixes below. If the hot span is somewhere else (e.g.
`widget.prompt_panel.update_display`, `widget.agent_detail.update_display_immediate`, or the 1-Hz tick), pivot to that
finding before writing any code.

## Fix plan (assuming primary hypothesis is confirmed)

### Fix 1 — keep the tools-panel mtime probe off the event loop

Move the freshness check out of `_update_display_impl`'s critical section. Two viable shapes; pick whichever is cleaner
once the surrounding code is read in full:

- **Option A (preferred):** Always paint from the cache immediately when one exists. Schedule the existing `fetch_task`
  worker unconditionally but cheaply — let the _worker_ decide whether to re-read by comparing mtime there (in the
  thread pool). When the worker discovers nothing changed, it returns the cached entries unchanged and the post-callback
  is a no-op visually.
- **Option B:** Cache `(mtime_ns, last_checked_monotonic)` and only call `_max_tool_calls_mtime_ns` when at least N ms
  (e.g. 250 ms) have elapsed since the last probe. This still runs on the event loop but cheaply throttles it.

Either way, the call to `discover_related_tool_artifact_dirs` and its sibling JSON reads must not run on every
keystroke.

### Fix 2 — cheaper freshness check

`_max_tool_calls_mtime_ns` re-walks the parent directory and re-parses sibling `agent_meta.json` / `done.json` every
call just to enumerate candidate dirs. Cache the discovered directory list per agent identity (invalidated by parent-dir
mtime) so the steady-state probe is just N `stat()`s on already-known paths. The metadata-driven discovery only needs to
re-run when the parent mtime advances (new sibling appears).

### Fix 3 — coalesce hook writes a little

Within the TUI process this is optional, but a small win: when the hook-write rate is high, the tools-panel cache
invalidates faster than the worker can re-read. Add a minimum re-read interval (e.g. 500 ms) so back-to-back mtime
advances merge into a single worker run. This sits inside the tools panel; the hook subprocess remains unchanged.

### Out of scope for this change

- Hook-side lock contention (`_tool_calls._append_jsonl`). If the diagnostic shows the lock is genuinely contended in
  real workloads, file a follow-up to switch to per-record append-with-O_APPEND (atomic for <PIPE_BUF writes) and drop
  the explicit lock. Not needed if Fix 1 and Fix 2 land the TUI back to interactive speed.
- The 1-Hz `_on_countdown_tick` row patch. Existing work (`patch_active_runtime_rows`) is already gated by
  `runtime_suffix_ticks`, and prior tales debated this design. Leave alone unless trace data shows it's hot in steady
  state.

## Validation

1. Re-run with `SASE_TUI_TRACE=1` after the fix; the `widget.tools_panel.update_display` span must drop to
   sub-millisecond on the steady path (cache hit, no re-walk).
2. Manual test: navigate with `j`/`k` rapidly while a Claude agent is spamming tool calls. The UI must remain
   responsive.
3. Existing tests in `tests/ace/tui/widgets/test_tools_panel.py` and `tests/ace/tui/tools/test_reader.py` must still
   pass. Add a focused regression test: assert that `tools_panel.update_display` for a warm-cache agent does not call
   `discover_related_tool_artifact_dirs` (or calls it at most once per N ms) by patching the function with a counting
   wrapper.
4. `just check` must pass.

## Files likely to change

- `src/sase/ace/tui/widgets/tools_panel.py` — move/throttle the mtime probe, optionally cache the artifact-dir list.
- `src/sase/ace/tui/tools/reader.py` — possibly add a `discover_related_tool_artifact_dirs` overload that accepts a
  cached result, or a sibling helper that returns `(dirs, parent_mtime_ns)` so the panel can decide whether to re-walk.
- `tests/ace/tui/widgets/test_tools_panel.py` — new regression test.
