# Debugging `sase ace` Progressive Slowdown

## The Symptom

`sase ace` is fast immediately after launch. Over a long-running session —
especially one in which the user launches one or more agents — it slows to a
crawl. Quitting with `q` and restarting `sase ace` returns it to its initial
fast state.

This is a *degradation-over-time* pattern, qualitatively different from the
steady-state hot-path costs that the prior performance research has already
addressed. Those captures show what is expensive *per frame* averaged over the
session; they do not show **whether per-frame cost is climbing**, which is the
actual question here.

## Why The Existing Tooling Isn't Enough

The repo already has:

- `sase ace --profile` — a single pyinstrument capture aggregated across the
  whole session (`src/sase/main/ace_handler.py:62`). Aggregation hides drift:
  a function that costs 1 ms in the first minute and 50 ms in the tenth shows
  up as "averaged" in the flame tree.
- `SASE_TUI_PERF=1` JK key-to-paint latency log
  (`src/sase/ace/tui/util/perf.py`). Records per-keystroke latency in a rolling
  JSONL, but is scoped to `j`/`k` navigation only.
- The May 15 responsiveness captures
  (`sdd/research/202605/ace_profile_20260515_responsiveness.md`,
  `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md`). These
  diagnose individual stalls (tmux bell, `AgentInfoPanel` countdown rebuild,
  `_save_prompt_history`, etc.) but treat the session as homogeneous.

None of those tools answer the load-bearing question: **what cost is N×
larger at minute 10 than at minute 1?** Until we can answer that, every fix is
a guess.

## Hypothesis Space

A "starts fast, ends slow, fast again after restart" curve usually maps to one
of these classes. Listing them explicitly so the debugging tools can be
matched to the candidate causes:

1. **Unbounded caches.** Textual's `StylesCache`, `_option_render_cache`,
   `_line_cache`, plus SASE's `AgentRenderCache` and `cached_format_agent_option`
   may have no eviction policy. As the keyspace grows (more agents, more
   pseudo-class combinations, more highlighted indices), lookups stay O(1)
   amortized but per-frame work touches more entries.
2. **Memory growth / GC pressure.** Live objects accumulating push the gen-2 GC
   scan longer. Once the working set spills past CPU cache, every Python
   operation gets slower.
3. **Leaked asyncio tasks / `call_later` handles.** Each launched agent may
   register pollers, listeners, or refresh callbacks that aren't released when
   the agent completes. The auto-refresh tick then walks an ever-growing
   subscriber list.
4. **Subprocess / pipe descriptor accumulation.** Each `subprocess.Popen` or
   `asyncio.create_subprocess_exec` for the tmux bell or VCS resolution adds
   pipes; if cleanup is lazy, FD count creeps up and every `epoll_ctl` does
   more work.
5. **Textual DOM growth.** Modals, file panels, or transient widgets that
   mount but never unmount inflate `app.query("*")`. Selector queries then walk
   more nodes per call.
6. **Agent row count growing.** OptionList's per-row patch flushes list-wide
   caches (already noted in
   `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md` §2).
   Cost scales with N rows × tick frequency.
7. **Notification queue / dismissed-agent list.** Every reload re-walks a
   queue that grows with session age.
8. **Prompt-history file growth.** Every keystroke / submit appends. The file
   is re-read on each prompt-bar mount; mtime-cache misses scale with file
   size.
9. **Background pollers proliferating.** A new poller per launched agent that
   keeps polling forever (even after the agent terminates).
10. **Filesystem state**: stale `sase_<N>` workspaces or stat-heavy directory
    scans that grow with the on-disk corpus.

Most of these are invisible to a single pyinstrument snapshot.

## Recommended Debugging Capabilities to Add

The themes below are ordered by *cost to add* relative to *insight produced*.

### 1. Heartbeat Telemetry (Highest Value, Lowest Cost)

Add a 30-second background task to `AceApp`, gated on `SASE_HEARTBEAT=1`, that
appends one JSONL line to `~/.sase/perf/heartbeat.jsonl`:

```json
{
  "ts": "2026-05-15T18:42:03",
  "session_age_s": 612.3,
  "rss_mb": 287.4,
  "vms_mb": 412.1,
  "gc_counts": [711, 12, 3],
  "gc_objects": 184392,
  "asyncio_tasks": 41,
  "asyncio_call_later": 9,
  "dom_widgets": 217,
  "agent_rows": 38,
  "agent_rows_terminal": 22,
  "notification_queue": 14,
  "prompt_history_bytes": 412918,
  "render_p95_ms_30s": 4.1,
  "key_to_paint_p95_ms_30s": 38.0,
  "open_fds": 71
}
```

This single line per 30 s, plotted against `session_age_s`, immediately
reveals **which dimension is growing** during a slow session. Once you know
that, you know which class from the hypothesis list to chase. The cost is one
async task and ~10 stdlib calls per emission; the file is tiny over an hour.

Useful sources for each field:
- `rss_mb`/`vms_mb`/`open_fds`: `psutil.Process()` (optional dep; degrade
  gracefully if absent).
- `gc_counts`: `gc.get_count()`. `gc_objects`: `len(gc.get_objects())` — this
  one is *not* cheap; sample it every 30 s only.
- `asyncio_tasks`: `len(asyncio.all_tasks())`. Augment with a histogram by
  `task.get_name()` periodically.
- `dom_widgets`: `len(self.query("*"))`.
- `agent_rows*`/`notification_queue`: read from existing app state.
- `render_p95_ms_30s`: see "frame-time histogram" below.

This is the single most important capability to add. Everything else
narrows down the hypothesis class once heartbeat tells you which dimension
moves.

### 2. Time-Sliced Profiling (instead of session-aggregated)

The current `--profile` flag captures one aggregate sample. Two ways to make
it time-sliceable:

**Option A — Rolling pyinstrument windows.** Extend `ace_handler.py` so
`--profile` accepts an interval (`--profile=60`): every 60 s, write the
current profiler text and reset. End of session you have `profile_0m.txt`,
`profile_1m.txt`, …, `profile_10m.txt`. Diffing buckets across files surfaces
the growing-cost functions.

**Option B — py-spy / speedscope.** `py-spy record --format speedscope` produces
a file that the speedscope UI lets you scrub by time range. Recommended
workflow:

```bash
# Terminal 1: launch sase ace normally
sase ace

# Terminal 2: attach and record
py-spy record --format speedscope -o /tmp/ace.speedscope --pid $(pgrep -f "sase ace") --duration 900

# Open at https://speedscope.app/ and use the time-range selector
```

speedscope's "time order" view lets you visually compare the first 30 s
flame with the last 30 s flame. This is the cheapest way to *see* which call
trees inflate over time. py-spy attaches without restarting and has near-zero
overhead.

**Option C — viztracer.** Produces a Chrome-trace timeline you can scrub in
`vizviewer`. Higher overhead (~5–10×) but the absolute time axis makes
degradation immediately visible. Use sparingly — e.g., wrap a single
keystroke at t=1m and again at t=10m and compare the two trace files.

### 3. Memory Tracing With tracemalloc Diff

`tracemalloc` is stdlib and supports snapshot diffing — exactly the operation
needed for "what grew over time?":

```python
import tracemalloc
tracemalloc.start(25)  # 25 frames of allocation traceback

# at session start, after warmup:
snap_baseline = tracemalloc.take_snapshot()

# later, on demand (debug keybinding, SIGUSR1, or every N minutes):
snap_now = tracemalloc.take_snapshot()
stats = snap_now.compare_to(snap_baseline, "lineno")
for s in stats[:30]:
    print(s)
```

The output names the file:line that allocated the bytes that are still live
that weren't there at baseline. This is the *direct* answer to leak
location.

Gate via `SASE_TRACEMALLOC=1` because the overhead is ~25–30 % when on. Provide
a debug binding (e.g., `Ctrl+Shift+M`) that triggers a snapshot diff to disk.

For deeper leak hunting, `memray run -o out.bin -m sase ace` produces a
visualization (`memray flamegraph out.bin`) of allocation sites over time —
designed for exactly this question.

### 4. Object-Population Diffing With objgraph

Pure stdlib version:

```python
from collections import Counter
import gc

def type_counts() -> Counter:
    return Counter(type(o).__name__ for o in gc.get_objects())
```

Diff two such counters by subtracting; print the top growers. Run on the same
SIGUSR1 / debug keybinding as the tracemalloc snapshot. The class names alone
often point at the leaking subsystem ("there are now 14 281 `AgentSession`
objects, up from 3").

`objgraph.show_growth(20)` is the same idea pre-packaged, plus
`objgraph.show_backrefs(obj, max_depth=5)` for chasing why something is still
reachable.

### 5. Frame-Time Histogram

The existing `JKPerfTimer` already records key-to-paint for `j`/`k`. Broaden
it to record *every* Textual frame render, not just navigation:

- Hook into the app's render path (or `MessagePump._dispatch_message`) and
  record render duration with `time.perf_counter`.
- Keep a 60-second rolling window. Emit p50/p95/max into the heartbeat row.
- When p95 crosses a threshold (e.g., 50 ms), write a marker line to the
  heartbeat log: `{"event": "p95_spike", "p95_ms": 92.3}`.

You then have a timeline showing exactly when the TUI started feeling slow.
That lets you correlate with what the user did at that moment (e.g., agent #7
launched, or a modal mounted) and with the heartbeat dimensions.

### 6. asyncio Task Accounting

```python
def task_census():
    by_name = Counter()
    for t in asyncio.all_tasks():
        by_name[t.get_name() or repr(t)] += 1
    return by_name
```

Diff at t=1m vs t=10m. If `agent_polling_task` went from 1 to 40, you have a
poller leak. If anonymous coroutines stack up, somebody isn't awaiting.

Also worth instrumenting: `len(loop._scheduled)` if accessible, which counts
queued `call_later` handles. Steadily-rising count is a smoking gun.

### 7. Cache-Size Probes

Add `cache_telemetry()` to the heartbeat collector, returning sizes of the
caches the app owns:

- `cached_format_agent_option.cache_info()` (it's an `functools.lru_cache`-like
  shape — call `cache_info()` and log `currsize`, `hits`, `misses`).
- `AgentRenderCache._cache` length and approximate memory.
- For Textual internals: `widget._styles_cache._cache` length (private but
  knowable). The list of widgets is `app.query("*")`; aggregate the size of
  their styles caches.
- `_CachedSyntaxRenderable` segment store size.

If any of these grow monotonically with no bound, that's your candidate.
Don't be subtle about this — a quick `len(...)` is fine even for "private"
attrs; it's diagnostic, not load-bearing.

### 8. Reproduction Harness

The bottleneck in debugging degradation has historically been the *time
required to reproduce*. The repo already uses Textual's `Pilot` for headless
tests (e.g., `sase ace --agent`). Build a Pilot driver that, in ~2 minutes
headless, simulates the slow-session pattern:

```python
async def test_progressive_slowdown_repro():
    app = AceApp(query="!!!")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        baseline = await measure_paint_p95(pilot, n=50)

        for i in range(30):  # 30 simulated agent launches
            await launch_synthetic_agent(pilot, name=f"a{i}")
            await pilot.pause(0.5)

        # walk the same 50 keys after warmup
        after = await measure_paint_p95(pilot, n=50)

        ratio = after / baseline
        print(f"baseline p95={baseline:.1f}ms, after p95={after:.1f}ms, ratio={ratio:.2f}x")
        assert ratio < 1.5, f"navigation degraded {ratio:.2f}x after 30 agents"
```

Already-existing related work:
`sdd/research/202605/agents_tab_reproduction_harness.md`. Build on top of
that rather than starting from scratch.

Why this matters: without a repro, every fix iteration is a 10-minute
interactive session. With one, it's two minutes headless and you can bisect
fixes.

### 9. Live-Attach Snapshot On Demand

Slowdown often appears mid-session and the user wants to inspect *right then*
without losing state. Two cheap mechanisms:

- **SIGUSR1 handler.** Register `signal.signal(SIGUSR1, _dump_diagnostics)` in
  `AceApp.on_mount`. From another terminal: `kill -USR1 $(pgrep -f "sase ace")`.
  The handler writes `tracemalloc` diff, `objgraph.show_growth`, asyncio task
  census, and cache sizes to `~/.sase/perf/diagnostics_<ts>.txt`.
- **`py-spy dump --pid`.** Out-of-process stack dump of every thread. Zero
  setup, no code changes. Useful when the TUI is actively frozen and you want
  to know what it's doing right now.

### 10. Comparative Snapshots, Not Aggregate Snapshots

Generalization of the principle behind several entries above: in a
degradation hunt, **stop looking at aggregate snapshots**. Always capture
*pairs* (baseline + late) and diff them. The whole question is "what got
bigger?" — that's a diff question, not a snapshot question.

This applies to:
- pyinstrument: capture two ~30 s windows, compare.
- tracemalloc: snapshot, snapshot, `compare_to`.
- `gc.get_objects()` type counts: Counter subtraction.
- Heartbeat: read first row and last row of `heartbeat.jsonl`.

## Recommended Investigation Workflow

Pick up tools in the order that produces actionable signal fastest.

1. **Add heartbeat telemetry (§1).** One PR, one async task. Single source of
   truth for "what's growing?" Once in, every slow session generates a
   diagnosable record without requiring re-running anything.
2. **Run a real slow session.** Use the TUI normally for ~20 minutes, launch
   several agents. Watch heartbeat.
3. **Identify the growing dimension.** Read first and last lines of
   `heartbeat.jsonl`. The dimension(s) that grew non-trivially identify the
   hypothesis class to focus on.
4. **Apply the matching deep-dive tool**:
   - `rss_mb` grew → tracemalloc diff (§3) and/or memray.
   - `asyncio_tasks` grew → task census (§6) with named-task histogram.
   - `dom_widgets` grew → walk the DOM, find the widget class that grew.
   - Cache sizes grew unboundedly (§7) → straightforward fix (add eviction).
   - None grew, but `render_p95_ms` climbed → time-sliced profiling (§2).
5. **Build the Pilot repro (§8)** once you have a working hypothesis. Iterate
   fixes against the repro, then verify against a real session.
6. **Verify with comparative snapshots (§10).** Same 30-second interaction at
   t=0 and t=20m should show similar pyinstrument bucket sizes after the fix.

## Concrete Code-Locality Notes For An Implementer

If/when an implementation plan is written, these locations are the load-
bearing ones:

- **Heartbeat task install point:** `src/sase/ace/tui/app.py` — wherever
  `JKPerfTimer` is constructed today is a good neighbour. Schedule via
  `self.set_interval(30.0, self._emit_heartbeat)` so it goes through Textual's
  loop cleanly.
- **`--profile` extension:** `src/sase/main/ace_handler.py:62` and
  `src/sase/main/parser_ace.py:41`. Adding a `--profile-interval` argument and
  a worker that calls `profiler.reset()` on a timer is a small, isolated
  change.
- **Diagnostic dump signal handler:** wire in
  `src/sase/ace/tui/actions/startup.py` next to existing app-bootstrap hooks.
- **JK timer extension:** `src/sase/ace/tui/util/perf.py`. Add a
  `FrameTimer` peer next to `JKPerfTimer`; reuse the JSONL write path.
- **Pilot repro:** mirror the style of
  `sdd/research/202605/agents_tab_reproduction_harness.md`.

## What Not To Do

- **Don't keep iterating on pyinstrument single-session captures.** The May 15
  research already mined the high-value insights at that resolution; the
  remaining returns are diminishing.
- **Don't optimize speculatively.** Adding cache eviction or weakref-ing
  things without evidence often makes the steady-state hot path slower while
  the actual leak remains.
- **Don't conflate "fast after restart" with "the previous instance was
  leaking Python objects".** It could also be Textual cache state, OS-level
  page-cache effects, or the prompt-history file growing on disk. The
  heartbeat dimensions distinguish these.

## Open Questions

- Does the slowdown correlate with **number of agents currently visible**,
  **number of agents launched in this session (including completed ones)**, or
  **wall-clock session age**? The heartbeat row makes each falsifiable in a
  single session.
- Is the slowdown localized to one tab (e.g., Agents tab) or global? Frame-
  time histogram tagged by `current_tab` answers this.
- Does the slowdown survive a tab switch and switch back? If yes, state isn't
  scoped to per-tab teardown. If no, the leak is per-tab and remounting fixes
  it.
- Does the slowdown survive a `clear` of the agent list (if such an action
  exists)? If clearing rows recovers speed, the cost is per-row; if not, it's
  upstream of row rendering.

## Cross-References

- `sdd/research/202604/tui_profiling_strategies.md` — tool-selection
  background. This document is the time-axis companion.
- `sdd/research/202605/ace_profile_20260515_responsiveness.md` and
  `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md` —
  snapshot-aggregate hot-path captures.
- `sdd/research/202605/agents_tab_reproduction_harness.md` — base for the
  Pilot repro proposed in §8.
- `sdd/research/202605/rebuild_from_scratch_performance.md` — adjacent prior
  art on what "fast" looks like for `sase ace`.
- `src/sase/ace/tui/util/perf.py` — existing perf-telemetry primitive to
  extend.
- `src/sase/main/ace_handler.py:62` — `--profile` flag wiring; the natural
  place to add `--profile-interval`.
