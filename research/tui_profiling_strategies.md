# Profiling the sase TUI for Performance

## Context

The `sase ace` TUI is built on Textual (asyncio-based Python TUI framework). Known bottlenecks include per-keystroke CSS
selector traversals (`query_one()`), O(n) index computations during j/k navigation, synchronous file I/O on the main
thread, and redundant widget re-renders. The existing performance plan (`sase_plan_tui_nav_perf.md`) identifies specific
optimizations but lacks a systematic profiling workflow to measure before/after impact and catch regressions.

This document evaluates profiling approaches suited to an asyncio Textual app and recommends a strategy.

---

## Approach 1: pyinstrument (Statistical Call-Stack Profiler)

**What it is**: A sampling profiler that captures the call stack every 1ms and presents results as a flame-style tree
showing wall-clock time, not CPU time. This means it naturally captures I/O waits, sleep, and event-loop idle time —
exactly the kind of stalls that make a TUI feel slow.

**How to use with Textual**:

```python
# Option A: Wrap the entire app run
import pyinstrument
profiler = pyinstrument.Profiler()
profiler.start()
app.run()
profiler.stop()
profiler.print()
# or: profiler.open_in_browser()  # interactive HTML flamegraph

# Option B: Profile a specific code path
profiler.start()
self._refresh_agents_display(list_changed=True)
profiler.stop()

# Option C: CLI invocation (zero code changes)
# pyinstrument -m sase ace
```

**Strengths**:

- Very low overhead (~2-5%), safe to run during interactive TUI use
- Wall-clock time is the right metric for responsiveness (captures I/O stalls, not just CPU)
- HTML output with collapsible call trees — easy to share and navigate
- `async` mode automatically handles asyncio: `Profiler(async_mode="enabled")`
- No C extensions required, pure Python fallback available

**Weaknesses**:

- 1ms sampling interval means very fast functions (<1ms) may be missed
- Cannot tell you _how many times_ a function was called — only cumulative time in it
- No line-level granularity (function-level only)

**Verdict**: Best general-purpose starting point. Low friction, captures the "where is wall-clock time going?" question
directly.

---

## Approach 2: py-spy (External Sampling Profiler)

**What it is**: A sampling profiler written in Rust that attaches to a running Python process from the outside, without
modifying or importing anything. Produces speedscope/flamegraph SVG output.

**How to use with Textual**:

```bash
# Record a session while interacting with the TUI
py-spy record -o profile.svg -- python -m sase ace

# Attach to an already-running sase ace process
py-spy record -o profile.svg --pid $(pgrep -f "sase ace")

# Top-like live view of hot functions
py-spy top --pid $(pgrep -f "sase ace")
```

**Strengths**:

- Zero code changes, zero import-time overhead
- Can attach to an already-running TUI session — profile real usage, not synthetic benchmarks
- Very low overhead (runs out-of-process), doesn't interfere with event loop timing
- `py-spy top` gives a live, htop-style view of where time is spent — great for exploratory profiling
- Flamegraph SVGs are visually excellent for identifying hot paths

**Weaknesses**:

- Requires root/`SYS_PTRACE` capability on Linux (or `--nonblocking` flag which drops some accuracy)
- Sampling rate is configurable but still statistical — can miss sub-millisecond functions
- Doesn't directly understand asyncio task boundaries (shows OS thread stacks)
- External tool, not pip-installable (installed via `pip install py-spy` but the binary needs privileges)

**Verdict**: Best for profiling real interactive sessions without altering app behavior. The attach-to-running-process
capability is uniquely valuable for a TUI where startup cost matters differently than steady-state cost.

---

## Approach 3: cProfile / profile (Deterministic Profiler)

**What it is**: Python's built-in deterministic profiler. Instruments every function call/return, so it gives exact call
counts and cumulative time. `cProfile` is the C-accelerated version.

**How to use with Textual**:

```bash
python -m cProfile -o profile.prof -m sase ace
# Then analyze:
python -m pstats profile.prof
# or use snakeviz for a web-based viewer:
snakeviz profile.prof
```

```python
# Programmatic, scoped profiling
import cProfile
pr = cProfile.Profile()
pr.enable()
# ... do the thing ...
pr.disable()
pr.print_stats(sort="cumtime")
```

**Strengths**:

- Built into Python, zero install
- Exact call counts — can identify "this function is called 500 times per refresh" problems
- Deterministic: nothing is missed, every call is recorded
- snakeviz and gprof2dot provide good visualization

**Weaknesses**:

- **High overhead (10-30x slowdown)**: instrumenting every call/return distorts the very timings you're measuring. In a
  TUI where you're trying to measure "how fast does j/k feel?", this is a serious problem — the profiler itself makes
  everything feel slow, and relative timings shift
- Measures CPU time by default, not wall-clock — misses I/O stalls entirely unless you use `profile.Profile` (pure
  Python, even slower)
- Doesn't understand asyncio natively — all coroutines appear as regular function calls, task-switching overhead gets
  attributed to wrong functions
- Massive output for a complex app — the TUI has hundreds of widgets, Textual internals generate thousands of calls

**Verdict**: Useful in narrow, targeted scopes (profile one function in a test harness) but too invasive for profiling
interactive TUI responsiveness. The overhead changes what you're measuring.

---

## Approach 4: Scalene (CPU + Memory + GPU Profiler)

**What it is**: A high-performance sampling profiler that simultaneously tracks CPU time, memory allocation, and even
GPU usage. Reports at line-level granularity with low overhead.

**How to use with Textual**:

```bash
scalene --cpu --memory --- python -m sase ace
# or, profile just a specific module:
scalene --cpu --profile-only sase.ace.tui --- python -m sase ace
```

**Strengths**:

- **Line-level profiling** with low overhead (~15-30%) — much more granular than pyinstrument
- Separates Python time vs. native (C extension) time — useful for identifying whether slowness is in your code or in
  Textual/Rich internals
- Simultaneous memory profiling catches allocation-heavy code paths that may trigger GC pauses
- Web-based UI for results
- `--profile-only` flag lets you focus on your code, filtering out framework noise

**Weaknesses**:

- More overhead than pyinstrument or py-spy (~15-30% vs 2-5%)
- Complex output — CPU + memory + copy info per line can be overwhelming
- Less mature asyncio support than pyinstrument
- The line-level granularity is most useful for tight inner loops; for a TUI, the bottlenecks tend to be at the
  function/call-chain level

**Verdict**: Best when you've already identified a hot module/function and want line-level detail on _where within it_
time is spent. Overkill as a first pass.

---

## Approach 5: line_profiler (Line-Level Deterministic Profiler)

**What it is**: Decorator-based profiler that times every line in decorated functions.

**How to use**:

```python
from line_profiler import profile

@profile
def _refresh_agents_display(self, *, list_changed=False):
    ...

# Run with:
# kernprof -l -v script.py
```

**Strengths**:

- Exact per-line timings for targeted functions
- Very easy to use: just decorate the functions you suspect

**Weaknesses**:

- Must modify source code to add decorators (or use `kernprof` CLI with limitations)
- Only profiles decorated functions — you need to already know which ones to look at
- Significant overhead on decorated functions
- Doesn't understand asyncio coroutines well

**Verdict**: Useful for deep-diving into a single known-hot function after coarse profiling has identified it. Not a
discovery tool.

---

## Approach 6: Textual Devtools + Custom Instrumentation

**What it is**: Textual ships with `textual run --dev` which enables a devtools console for inspecting the widget tree,
CSS, events, and message flow. Combined with lightweight custom timing instrumentation, this can provide TUI-specific
insight that generic profilers miss.

**How to use**:

```bash
# Terminal 1: start devtools console
textual console

# Terminal 2: run app in dev mode
textual run --dev -c python -m sase ace
```

Custom timing decorator for hot paths:

```python
import time
import logging

log = logging.getLogger("sase.perf")

def timed(func):
    """Log wall-clock time for a function call."""
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > 5:  # only log slow calls
            log.warning(f"{func.__qualname__}: {elapsed_ms:.1f}ms")
        return result
    return wrapper
```

Textual message tracing (built-in):

```python
# In AceApp
class AceApp(App):
    def on_event(self, event):
        # Log all events with timing
        ...
```

**Strengths**:

- Textual devtools shows the actual widget tree, CSS cascade, and message queue — profilers can't see this
- Can identify problems like "this widget is receiving 50 redundant Mount messages" that profilers report as time in
  `on_mount()` without explaining _why_
- Custom instrumentation can be made permanent, giving ongoing regression detection
- Low overhead when guarded behind `log.isEnabledFor(DEBUG)` or a flag
- Can measure exactly what the user perceives: time from keypress to screen update

**Weaknesses**:

- Textual devtools is visual/exploratory, not quantitative
- Custom instrumentation requires knowing where to instrument
- Doesn't replace systematic profiling — it complements it

**Verdict**: Essential complement to any profiler. Textual devtools shows _what the framework is doing_ (message
routing, widget lifecycle, CSS recalculation) while profilers show _where time goes_. The custom timing decorator is
especially useful for building a permanent performance dashboard.

---

## Approach 7: Textual Pilot Benchmarks (Automated Performance Tests)

**What it is**: Using Textual's `run_test()` / `Pilot` API (already used in `sase ace --agent`) to build reproducible
performance benchmarks that run headlessly and measure specific interactions.

**How to use**:

```python
import time
import pytest

@pytest.mark.asyncio
async def test_jk_navigation_perf():
    app = AceApp(query="!!!")
    async with app.run_test(size=(120, 40)) as pilot:
        # Setup: populate with agents
        await pilot.pause()

        # Benchmark: 100 j keypresses
        start = time.perf_counter()
        for _ in range(100):
            await pilot.press("j")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 100) * 1000
        assert avg_ms < 16, f"j navigation too slow: {avg_ms:.1f}ms avg (target: <16ms)"

@pytest.mark.asyncio
async def test_tab_switch_perf():
    app = AceApp(query="!!!")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        start = time.perf_counter()
        await pilot.press("tab")
        await pilot.pause()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Tab switch too slow: {elapsed_ms:.1f}ms"
```

**Strengths**:

- Reproducible: runs in CI, catches regressions automatically
- Tests the full stack end-to-end, including Textual's rendering pipeline
- Can set concrete performance budgets (e.g., "j navigation must be <16ms")
- Leverages existing `sase ace --agent` infrastructure
- The 16ms target (60fps) is a meaningful perceptual threshold

**Weaknesses**:

- `run_test()` headless mode has slightly different timing than real terminal rendering
- Setup/teardown overhead means you need to amortize over many operations
- Doesn't tell you _why_ something is slow — just _that_ it's slow
- Need real-ish fixture data to be meaningful

**Verdict**: Not a profiling tool per se, but the essential complement: profilers tell you where time goes, benchmarks
tell you whether your fix actually helped and prevent regressions. Should be part of any performance effort.

---

## Recommended Strategy

A layered approach, using different tools at different stages:

### Layer 1: Establish Baselines with Pilot Benchmarks

Before optimizing anything, write Pilot-based benchmarks for the key interactions: j/k navigation, tab switching, agent
list reload, and query filtering. Run them against the current code to establish baseline numbers. These become your
regression tests going forward.

### Layer 2: Broad Discovery with pyinstrument

Use pyinstrument with `async_mode="enabled"` to profile real TUI sessions. This will reveal the top-level time
distribution — is the bottleneck in Textual's message routing? In `query_one()` calls? In file I/O? In Rich rendering?
The wall-clock flame tree makes this immediately visible.

A practical workflow:

1. Add a `--profile` flag to `sase ace` that starts/stops pyinstrument around the app run
2. Use the TUI normally for 30-60 seconds, exercising the slow paths
3. Exit and review the HTML report

### Layer 3: Deep-Dive with py-spy or Scalene

Once pyinstrument identifies the hot module or function:

- Use **py-spy** if you want to profile a real session without any code changes (great for "is it still slow after my
  fix?" spot checks)
- Use **Scalene** with `--profile-only` if you need line-level detail within a specific module

### Layer 4: Framework-Level Insight with Textual Devtools

When the profiler points to Textual internals (CSS queries, message handling, layout recalculation), switch to
`textual console` + `textual run --dev` to understand _what the framework is doing_. This is especially useful for
diagnosing the `query_one()` overhead identified in the nav perf plan.

### Layer 5: Permanent Instrumentation

Add a lightweight `@timed` decorator (or context manager) to the ~10 hottest functions on the navigation path. Gate it
behind an environment variable (`SASE_PERF=1`) so it's always available but silent by default. This gives you instant
profiling of the hot path without starting up an external tool.

### Summary Table

| Stage           | Tool             | When to Use                           | Overhead   |
| --------------- | ---------------- | ------------------------------------- | ---------- |
| **Baseline**    | Pilot benchmarks | Before & after every change           | N/A (test) |
| **Discovery**   | pyinstrument     | "Where is time going?"                | ~2-5%      |
| **Live attach** | py-spy           | Profile real usage, no code changes   | ~1-2%      |
| **Line-level**  | Scalene          | Deep-dive into a known hot function   | ~15-30%    |
| **Framework**   | Textual devtools | Understanding widget/message overhead | ~0%        |
| **Ongoing**     | Custom `@timed`  | Regression detection in hot path      | ~0%        |

The combination of pyinstrument for discovery + Pilot benchmarks for regression testing covers 80% of the need. The
other tools are reach tools for specific situations.
