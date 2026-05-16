---
create_time: 2026-05-16 18:15:24
status: done
prompt: sdd/prompts/202605/tui_perf_instrumentation.md
---
# TUI Perf Diagnosis — Instrumentation Improvements (#1, #2)

Implement the first two recommendations from `sdd/research/202605/tui_tmux_perf_diagnosis_20260516.md`. Both are pure
instrumentation/logging changes; behavior of the TUI is otherwise unchanged, only the contents of trace records emitted
under `SASE_TUI_TRACE=1`.

## Motivation

During the research session, the initial pass misdiagnosed the dominant `agents.load_from_disk` span as a missing-index
condition because the span carried no information about which loader path it took. A direct loader probe was needed to
discover the artifact index was actually present and used. Surfacing the load-state fields directly on the span removes
the need for an out-of-band probe next time.

Separately, the trace context only learns `current_tab` once the user switches tabs (because
`set_trace_context(current_tab=...)` is only called from `watch_current_tab`). Startup traces therefore all log
`current_tab=None`, which obscures the very phase the bottleneck lives in.

## Recommendation 1 — Attach `AgentLoadState` fields to the load span

### Where the data lives

The loader returns an `AgentLoadState` dataclass (`src/sase/ace/tui/models/agent_loader.py:75`) with exactly the fields
called out in the research note:

- `tier`: `"tier1" | "tier2"`
- `complete_history`: `bool`
- `artifact_source`: `"artifact_index" | "source_scan"`
- `used_artifact_index`: `bool`
- `index_error`: `str | None`

The span we want to enrich wraps the helper call site at `src/sase/ace/tui/actions/agents/_loading_helpers.py:85`:

```python
with tui_trace("agents.load_from_disk"):
    return _load_agents_from_disk_impl(
        dismissed_agents,
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
    )
```

The state is only known _after_ the inner call returns, so we cannot pass the counters as kwargs at span entry.

### Design choice — make `tui_trace` yield a mutable counters mapping

The minimal, lowest-risk way to attach post-hoc data is to let `tui_trace` yield a mutable dict that callers may update
inside the `with` block. Today the context manager yields `None`, and every existing call site uses bare
`with tui_trace(...):` (verified by grepping all usages under `src/`), so changing the yield type is backward-compatible
— only the one call site that opts in by writing `with tui_trace(...) as counters` is affected.

Concrete shape:

```python
# src/sase/ace/tui/util/trace.py
@contextmanager
def tui_trace(span: str, **counters: Any) -> Generator[dict[str, Any], None, None]:
    if not is_enabled():
        yield {}  # cheap throwaway; callers may write into it harmlessly
        return
    started = time.perf_counter()
    extra: dict[str, Any] = {}
    try:
        yield extra
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        record: dict[str, Any] = {
            "ts": time.time(),
            "span": span,
            "duration_ms": duration_ms,
            "current_tab": _context.get("current_tab"),
        }
        for key, value in _context.items():
            if key == "current_tab":
                continue
            record.setdefault(key, value)
        record.update(counters)
        record.update(extra)  # last writer wins → post-hoc fields override
        _write(record)
```

Then at the load site:

```python
# src/sase/ace/tui/actions/agents/_loading_helpers.py
with tui_trace("agents.load_from_disk") as counters:
    result = _load_agents_from_disk_impl(
        dismissed_agents,
        changespec_snapshot=changespec_snapshot,
        full_history=full_history,
    )
    state = result.load_state
    counters["tier"] = state.tier
    counters["artifact_source"] = state.artifact_source
    counters["complete_history"] = state.complete_history
    counters["used_artifact_index"] = state.used_artifact_index
    counters["index_error"] = state.index_error
    return result
```

Notes:

- We update the mapping _before_ returning, so even on the early-return path the `finally` clause sees the populated
  dict.
- The disabled path still yields a dict (empty); writes into it are silently dropped because the `finally` branch is
  skipped. This keeps the disabled-path cost to one extra small allocation per call, which is acceptable for a load that
  already takes hundreds of ms.

### Alternatives considered (and rejected)

- **Pass a mutable dict in and re-emit a duplicate span.** Doubles the records and forces consumers to dedupe by `ts`.
  Rejected.
- **Add a `tui_trace_emit(span, **counters)` point-event after the load completes.\*\* Loses the duration linkage and
  creates two records for one event. Rejected.
- **Inline the loader call inside the helper and pass the state up via `nonlocal`.** Works but is hostile to readers and
  harder to extend. Rejected in favor of the yielded dict.

## Recommendation 2 — Seed `current_tab` in trace context at startup

### Where to set it

The reactive default is `current_tab: reactive[TabName] = reactive("changespecs")` (`src/sase/ace/tui/app.py:137`), but
the actual initial tab is whatever the constructor was called with (default `"agents"`) and is applied in `__init__` via
`_init_app_state(initial_tab=...)`. The `watch_current_tab` callback only fires when the value _changes_, so the initial
reactive assignment doesn't seed the trace context.

The cleanest seam is `on_mount` in `src/sase/ace/tui/actions/startup.py` (starting at line 105). Tracing is enabled by
an env var read at span emission time, so an unconditional `set_trace_context` call is cheap (one dict write) regardless
of whether tracing is on.

Concrete change near the top of `on_mount`, after `self._mounting = True`:

```python
from ..util.trace import set_trace_context

set_trace_context(current_tab=self.current_tab)
```

This seeds the global trace context to the active tab before any of the post-mount loads (notifications read,
changespecs read, agents/axe background loads) emit their first spans, which is the gap the research analysis cared
about.

### Why not set it in `__init__`?

`set_trace_context` only affects records emitted later, so setting it in `__init__` is also valid. We pick `on_mount`
because (a) it keeps all startup-side-effect wiring in one place, (b) it sits right next to the existing `_mounting`
toggle that gates startup behavior, and (c) tests that construct `AceTUIApp(...)` without mounting (there are several)
won't acquire a sticky global side-effect from instantiation.

### Why not call it from `watch_current_tab` for the initial transition?

`watch_current_tab` short-circuits when `old_tab == new_tab`, and the initial reactive default may or may not match the
requested `initial_tab` depending on construction path. Threading "first call even if equal" logic through there is more
invasive than the one-line seed in `on_mount`.

## Test plan

Both changes are exercised through the existing `tests/ace/tui/test_tui_trace.py` shape; we add focused unit coverage:

1. **`tui_trace` yields a mutable mapping.** New test:

   ```python
   with trace.tui_trace("phase.demo", count=1) as extra:
       extra["tier"] = "tier1"
   row = _records(log)[0]
   assert row["tier"] == "tier1"
   assert row["count"] == 1
   ```

   Also assert that post-hoc fields override kwargs of the same name (last-writer-wins).

2. **Disabled-path still yields a usable mapping.** Test that writing into the yielded object with `SASE_TUI_TRACE`
   unset does not raise and produces no file.

3. **`agents.load_from_disk` span carries load-state fields.** Either a focused unit test against
   `load_agents_from_disk_with_state` with tracing enabled and the loader monkey-patched to return a fake
   `_AgentDiskLoadResult` with a known `AgentLoadState`, or extend an existing loader test if one already wires the
   trace log.

4. **Startup seeds `current_tab` in trace context.** Either:
   - A unit-level test that constructs the app, runs through `on_mount` under Textual's `App.run_test` harness with
     `SASE_TUI_TRACE=1`, and asserts an early span has the expected `current_tab`; or
   - A simpler test that asserts `set_trace_context` is invoked with `current_tab=self.current_tab` near the top of
     `on_mount` (e.g. via a fake `_context` swap in `trace.py`).

`just check` covers ruff + mypy + the full pytest suite and should remain green; no other modules import the changed
yield type.

## Files to change

- `src/sase/ace/tui/util/trace.py` — change `tui_trace` yield type to `dict[str, Any]`; merge `extra` into the emitted
  record after kwargs. Update the docstring to document the new "fill in after the call" pattern.
- `src/sase/ace/tui/actions/agents/_loading_helpers.py` — bind the yielded counters at the `agents.load_from_disk` span
  and populate the five load-state fields after the inner call returns.
- `src/sase/ace/tui/actions/startup.py` — call `set_trace_context(current_tab=self.current_tab)` at the top of
  `on_mount` (after `self._mounting = True`).
- `tests/ace/tui/test_tui_trace.py` — add tests for the yielded mapping (enabled + disabled paths, post-hoc override
  semantics).
- `tests/ace/tui/...` — new or extended test for the load-from-disk span and the startup seed (location depends on which
  test module already exercises the loader / mount path).

## Out of scope

- Recommendations 3–7 in the research doc (Tier-2 reconcile policy, Tier-2 post-processing optimization, Tier-1 latency
  monitoring, span renaming, refresh-key doc fix). These are larger changes and not pure instrumentation.
- Adjusting the disabled-path overhead of `tui_trace` beyond what is necessary to support the new yield contract.
- Renaming `agents.refresh_debounced` (recommendation 6) even though it would have helped during the research; the user
  asked only for #1 and #2.
