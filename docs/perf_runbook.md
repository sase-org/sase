# `sase ace` Performance Runbook

Phase 1 deliverable for the TUI performance overhaul (bead `sase-w.1`, `sdd/epics/202604/tui_perf_overhaul_1.md`). Each
later phase relies on the tracing + benchmark harness described here.

## Trace recorder

`SASE_TUI_TRACE=1` enables `tui_trace(...)` context managers spread across the ChangeSpec / agents / AXE hot paths. Each
entered span emits one JSONL line to:

```text
~/.sase/perf/tui_trace.jsonl
```

Override the destination with `SASE_TUI_TRACE_PATH=/tmp/foo.jsonl`. When the env flag is unset the context managers are
near-zero-cost no-ops.

Each record contains at least:

```text
ts            unix epoch seconds
span          dotted span name (e.g. "agents.refresh_panel_widgets")
duration_ms   wall time inside the span
current_tab   "changespecs" | "agents" | "axe" | null
```

…plus any per-call counters (`count`, `agents`, `panels`, `output_bytes`, …) and any global context fields seeded via
`sase.ace.tui.util.trace.set_trace_context(...)` (the app pushes `current_tab` and `current_idx` automatically).

Spans currently wired (by file):

- `actions/changespec/_display.py` — `changespec.refresh_display`, `changespec.refresh_debounced`
- `actions/changespec/_loading.py` — `changespec.filter`
- `actions/agents/_display.py` — `agents.refresh_display`, `agents.refresh_debounced`, `agents.refresh_panel_widgets`,
  `agents.refresh_panel_highlights`
- `actions/agents/_loading_helpers.py` — `agents.load_from_disk`
- `widgets/changespec_list.py` — `widget.changespec_list.update_list`, `widget.changespec_list.update_highlight`
- `widgets/changespec_detail.py` — `widget.changespec_detail.update_display`
- `widgets/agent_list.py` — `widget.agent_list.update_list`, `widget.agent_list.update_highlight`,
  `widget.agent_list.patch_agent_row`
- `widgets/agent_detail.py` — `widget.agent_detail.update_display`
- `widgets/ancestors_children_panel.py` — `widget.ancestors_children.update_relationships`
- `widgets/prompt_panel/_agent_display.py` — `widget.prompt_panel.update_display`
- `widgets/file_panel/__init__.py` — `widget.file_panel.update_display`
- `widgets/thinking_panel.py` — `widget.thinking_panel.update_display`
- `widgets/axe_dashboard.py` — `widget.axe_dashboard.update_display`

Spans nest cleanly: a single keypress that fires `agents.refresh_debounced` will record one outer span plus inner
`widget.agent_list.update_highlight` and `agents.refresh_panel_highlights` spans.

## Quick capture

```bash
SASE_TUI_TRACE=1 sase ace
# … exercise the path you care about (cold start, query change, j/k burst,
#   auto-refresh, large reply select) …
# Quit with q.

# Inspect:
jq -c 'select(.span | startswith("widget.agent_list."))' \
   ~/.sase/perf/tui_trace.jsonl | head -20
```

## Synthetic-data benchmark harness

The harness lives at `tests/perf/bench_tui_trace.py`. It generates in-memory ChangeSpec / agent fixtures and drives the
TUI through Pilot without touching real `~/.sase` data. Marked `pytest.mark.slow` so it does not run as part of
`just test`.

Run via pytest:

```bash
pytest -s -m slow tests/perf/bench_tui_trace.py
```

Or as a script (writes a baseline numbers file the next phase can diff):

```bash
python -m tests.perf.bench_tui_trace --output ~/.sase/perf/tui_perf_baseline.json
```

Fixture sizes:

```text
ChangeSpecs: 100,  500, 2000   (tests/perf/fixtures.py: CHANGESPEC_SIZES)
Agents:       50,  200, 1000   (tests/perf/fixtures.py: AGENT_SIZES)
Large reply:   1,    5,   20 MB (LARGE_REPLY_SIZES_MB)
```

Scenarios per fixture size:

- cold start
- query change
- 50-key j/k burst
- auto-refresh with no changes
- large-reply select

The per-scenario summary aggregates p50 / p95 / max for every span and key-to-paint action observed during that
scenario.

## Targets per phase gate

The targets below come from `research/202604/sase_perf_research.md` and are restated here so each phase agent has a
single page to check against. A phase is green when the relevant targets are met **without regressing** any other span.

```text
j/k highlight p95             < 16 ms
key-to-paint p95              < 33 ms
debounced detail paint        < 150–250 ms
warm ChangeSpec reload, 1k    < 100 ms
no-change auto-refresh stall  ~0 ms (event-driven path; Phase 7)
large reply first paint       immediate plain render, syntax later/optional
```

Per-phase responsibilities:

- **Phase 2** (ChangeSpec j/k hot path): `widget.changespec_list.update_list` call count drops to zero for j/k
  navigation; `update_highlight` p95 < 16 ms at 500 specs.
- **Phase 3** (data layer): warm ChangeSpec reload < 100 ms at 1k specs; `changespec.filter` p95 should drop materially
  after the snapshot cache and query context land.
- **Phase 4** (agent panel + list): `agents.refresh_panel_highlights` and `widget.agent_list.update_highlight` p95 < 16
  ms at 1k agents.
- **Phase 5** (incremental loader): `agents.load_from_disk` near zero on a no-change auto-refresh.
- **Phase 6** (artifact + render caching): `widget.prompt_panel.update_display` / `widget.file_panel.update_display`
  immediate first paint on the largest reply fixture.
- **Phase 7** (event-driven auto-refresh): no-change auto-refresh shows no agents/changespec spans firing at all.

## Adding a new span

```python
from sase.ace.tui.util.trace import tui_trace

with tui_trace("module.name", count=len(items)):
    ...
```

Names use dotted lowercase. Counters should be ints / strs only — the emitter falls back to `str(...)` for unknown types
via `default=str`, but keeping payloads JSON-friendly speeds downstream `jq` slicing.

When a span boundary forces a refactor (most existing hot paths split into `foo()` → `_foo_impl()` so the wrapping
context manager doesn't fight indentation rules), keep both methods next to each other and let the public name stay the
trace span name.
