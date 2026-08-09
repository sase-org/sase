# `sase ace` Performance Runbook

This runbook explains how to capture and compare performance data for ACE, the
`sase ace` terminal user interface. It started as the Phase 1 deliverable for the TUI
performance overhaul (bead `sase-w.1`, `sdd/epics/202604/tui_perf_overhaul_1.md`), and
later performance phases still rely on the tracing and benchmark harness described here.

## Trace recorder

`SASE_TUI_TRACE=1` enables `tui_trace(...)` context managers spread across the Patch,
agents, and AXE hot paths. Each entered span emits one JSONL line to:

```text
~/.sase/perf/tui_trace.jsonl
```

Override the destination with `SASE_TUI_TRACE_PATH=/tmp/foo.jsonl`. When the env flag is
unset the context managers are near-zero-cost no-ops.

Each record contains at least:

```text
ts            unix epoch seconds
span          dotted span name (e.g. "agents.refresh_panel_widgets")
duration_ms   wall time inside the span
current_tab   "artifacts" | "agents" | "axe" | null
```

…plus any per-call counters (`count`, `agents`, `panels`, `output_bytes`, …) and any
global context fields seeded via `sase.ace.tui.util.trace.set_trace_context(...)` (the
app pushes `current_tab` and `current_idx` automatically).

Point-in-time records emitted by `trace_event(...)` contain `event` instead of
`span`/`duration_ms`. They are used for selection and highlight watcher transitions
where there is no timed block to measure.

Timed spans currently wired (by file):

- `actions/patch/_display.py` — `patch.refresh_display`, `patch.refresh_debounced`,
  `patch.refresh_detail_only`
- `actions/patch/_loading.py` — `patch.filter`
- `actions/agents/_display.py` — `agents.refresh_display`, `agents.refresh_debounced`
- `actions/agents/_display_panels.py` — `agents.refresh_panel_widgets`,
  `agents.refresh_panel_highlights`
- `actions/agents/_loading_helpers.py` — `agents.load_from_disk`
- `actions/agents/_loading_live_hints.py` — `agents.live_hint_refresh`
- `actions/agents/_display_detail_render.py` — `agents.view_hints_refresh`
- `actions/hints/_files.py` — `agents.view_files`, `agents.view_agent_files`,
  `agents.view_hint_bar_mount`
- `widgets/prompt_panel/_agent_display_hints.py` —
  `widget.prompt_panel.update_display_with_hints`
- `widgets/patch_list.py` — `widget.patch_list.update_list`,
  `widget.patch_list.update_highlight`, `widget.patch_list.patch_patch_row`
- `widgets/patch_detail.py` — `widget.patch_detail.update_display`
- `widgets/agent_list.py` — `widget.agent_list.update_list`,
  `widget.agent_list.update_highlight`, `widget.agent_list.patch_agent_row`,
  `widget.agent_list.try_remove_rows`
- `widgets/agent_detail.py` — `widget.agent_detail.update_display`,
  `widget.agent_detail.update_display_immediate`
- `widgets/ancestors_children_panel.py` —
  `widget.ancestors_children.update_relationships`,
  `widget.ancestors_children.update_relationships_from_index`
- `widgets/prompt_panel/_agent_display.py` — `widget.prompt_panel.update_display`,
  `widget.prompt_panel.update_header_only`
- `widgets/file_panel/__init__.py` — `widget.file_panel.update_display`
- `widgets/thinking_panel.py` — `widget.thinking_panel.update_display`
- `widgets/axe_dashboard.py` — `widget.axe_dashboard.update_display`

Spans nest cleanly: a single keypress that fires `agents.refresh_debounced` will record
one outer span plus inner `widget.agent_list.update_highlight` and
`agents.refresh_panel_highlights` spans.

ACE deliberately keeps live-workspace pencil hints off the startup-critical agents
loader. The first load classifies only cheap persisted `diff_path` badges. After that
agents list has applied, `agents.live_hint_refresh` runs VCS probes for active,
non-terminal rows that do not yet have a persisted diff and patches changed rows in
place. During startup investigations, treat `agents.load_from_disk` and
`agents.live_hint_refresh` as separate costs: the former controls time to first
interactive Agents-tab paint, while the latter explains deferred pencil-badge updates.

### Reading a view-hints capture

Pressing `v` on the Agents tab nests four spans, outermost first:

```text
agents.view_files                              whole v keypath (both tabs)
└─ agents.view_agent_files                     Agents-tab branch only
   ├─ widget.prompt_panel.update_display_with_hints    the annotated render
   └─ agents.view_hint_bar_mount               mounting the HintInputBar
```

`agents.view_files` is the keypress → hint-bar-mounted interval: today the bar is
mounted last, so this span is effectively the render cost plus the mount cost.
Subtracting `agents.view_hint_bar_mount` from it gives the part of the wait the user
pays for work that is not the bar appearing.

`agents.view_hints_refresh` is the same annotated render fired again from an Agents-tab
detail repaint or from the detail-header enrichment message, rather than from a
keypress. Seeing it repeatedly with hint mode active is the signal that the document is
being rebuilt on refresh.

Useful counters:

```text
agents.view_files          tab
agents.view_agent_files    family_container, hints, commit_views,
                           header_enrichment_pending, outcome
                           (mounted | refocused | empty | no_agent |
                            detached_container)
agents.view_hints_refresh  family_container, hints, commit_views
update_display_with_hints  family_container, hints, commit_views,
                           tool_call_reports, annotated_chars,
                           header_summary (warm | cold)
```

`annotated_chars` counts every character handed to the hint scanner, summed across
fragments and family members, so it is the size term to divide a duration by.
`header_summary` says whether the render had a warm detail-header summary: a `cold`
render omits the SASE CONTEXT hints entirely and will be rebuilt when the enrichment
worker lands.

Slice one press out of a capture with:

```bash
jq -c 'select(.span | startswith("agents.view_") or . == "widget.prompt_panel.update_display_with_hints")
       | {span, duration_ms, hints, annotated_chars, header_summary, family_container, outcome}' \
   ~/.sase/perf/tui_trace.jsonl | tail -20
```

Trace events currently wired include:

- `selection.current_idx.set`
- `widget.patch_list.watch_highlighted` and `.suppressed`
- `widget.agent_list.watch_highlighted` and `.suppressed`
- `widget.bgcmd_list.watch_highlighted` and `.suppressed`

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

To inspect point events instead of timed spans:

```bash
jq -c 'select(.event)' ~/.sase/perf/tui_trace.jsonl | head -20
```

For key-to-paint timing during j/k navigation, also enable the separate perf recorder:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace
jq -c . ~/.sase/perf/tui_jk.jsonl | head -20
```

Override the key-to-paint path with `SASE_TUI_PERF_PATH=/tmp/tui_jk.jsonl`.

Agents that launch the TUI via `sase ace --tmux` get `SASE_TUI_TRACE=1` and
`SASE_TUI_PERF=1` injected automatically; export the variable to `0` before invoking to
opt out.

## Freeze and hitch capture

ACE's always-on watchdog writes event-loop and Textual message-pump diagnostics to
`~/.sase/logs/tui_stalls.jsonl`. There are two independent severity tiers:

- `tui_hitch` / `tui_pump_hitch` fire after 1.5 seconds by default. These are compact
  records containing the current tab and selection, the last action, keypress age, and
  the main-thread stack. Recovery rows use the corresponding `*_recovered` event and
  include the episode duration. Hitch records deliberately omit full asyncio-task and
  worker thread dumps, and are rate-limited; `suppressed_count` reports episodes omitted
  since the previous admitted record.
- `tui_stall` / `tui_pump_stall` retain the existing 5-second threshold and richer
  task/thread diagnostics. A long freeze can produce both a hitch and a stall because
  the two state machines are independent.

Lower both tiers for a short verification soak with:

```bash
SASE_TUI_HITCH_THRESHOLD_SECONDS=0.25 \
SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS=0.25 \
SASE_TUI_STALL_THRESHOLD_SECONDS=0.75 \
SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS=0.75 \
SASE_TUI_STALL_POLL_INTERVAL=0.02 \
SASE_TUI_PUMP_STALL_POLL_INTERVAL=0.02 \
SASE_TUI_STALL_PATH=/tmp/sase-tui-soak.jsonl \
sase ace
```

Exercise startup typing, launch and cleanup bursts, prompt-history and revive-agent
modal opens, tab switching during agent churn, and refreshes while the artifact or
dismissed-bundle indexes are contended. A fixed path should stay interactive and produce
no hitch/stall rows. Inspect any records in chronological order:

```bash
jq -c '{event, stall_seconds, duration_seconds, current_tab, current_idx,
        last_action, last_keypress_age_s, suppressed_count, main_thread_stack}' \
  /tmp/sase-tui-soak.jsonl
```

Read `main_thread_stack` from its final frame upward to find the blocking call. For a
pump-only event, the loop may still be running while one Textual message pump is
awaiting slow work; a loop event means the event loop itself stopped servicing the
watchdog beacon. Disable the compact tiers independently with `SASE_TUI_HITCH_DISABLE=1`
and `SASE_TUI_PUMP_HITCH_DISABLE=1`; the existing stall-tier disable flags remain
`SASE_TUI_STALL_DISABLE=1` and `SASE_TUI_PUMP_STALL_DISABLE=1`.

The persistent TUI diagnostic JSONL files under `~/.sase/logs/`—stall, git-operation,
launch-timing, external-tool, and agent-load records—rotate independently before
appending a record would make a non-empty file exceed 2 MiB. Each keeps one `.1`
generation. Set `SASE_TUI_TELEMETRY_MAX_BYTES` to another per-file byte limit, or `0`
for no size rotation. This bound is separate from the opt-in trace files under
`~/.sase/perf/`.

## Synthetic-data benchmark harness

The harness lives at `tests/perf/bench_tui_trace.py`. It generates in-memory Patch and
agent fixtures, then drives the TUI through Textual Pilot without touching real
`~/.sase` data. It is marked `pytest.mark.slow`, so it does not run as part of
`just test`.

For the Admin Center home-first path, use the focused Textual Pilot benchmark:

```bash
pytest -s -m slow tests/ace/tui/bench_admin_center_open.py
```

It reports `#` dispatch-to-paint p50/p95/max values for empty and populated
project/config stores. Treat zero mounted concrete panes and comparable results across
fixture sizes as the hard acceptance criteria; use the timing table for before/after
comparison rather than adding a unit-test wall-clock threshold.

Run via pytest:

```bash
pytest -s -m slow tests/perf/bench_tui_trace.py
```

Or as a script (writes a baseline numbers file the next phase can diff):

```bash
python -m tests.perf.bench_tui_trace --output ~/.sase/perf/tui_perf_baseline.json
```

The script also accepts explicit trace and key-to-paint output paths:

```bash
python -m tests.perf.bench_tui_trace \
  --output ~/.sase/perf/tui_perf_baseline.json \
  --trace-path ~/.sase/perf/tui_trace.jsonl \
  --perf-path ~/.sase/perf/tui_jk.jsonl
```

Fixture sizes:

```text
Patches: 100,  500, 2000   (tests/perf/fixtures.py: legacy-named CHANGESPEC_SIZES)
Agents:       50,  200, 1000   (tests/perf/fixtures.py: AGENT_SIZES)
Large reply:   1,    5,   20 MB (LARGE_REPLY_SIZES_MB)
```

Scenarios per fixture size:

- cold start
- query change
- repeated query edits
- 50-key j/k burst
- auto-refresh with no changes
- large-reply select

The per-scenario summary records wall-clock times, then aggregates p50 / p95 / max for
every trace span and key-to-paint action observed during that scenario.

### View-hints scenarios and committed baseline

The Agents-tab `v` keypath has its own scenario set, run separately because it needs
disk-backed fixtures — the hint render reads `raw_xprompt.md`, `*_prompt.md`, and
`live_reply.md` from a real artifacts dir:

```text
large_reply_first_press           v on a plain agent with a 100 KB reply, cold header summary
large_reply_repeat_press          v again on the same row after the bar is torn down
family_container_press            v on a 5-member family container at the default metadata level;
                                  conversation content is full under the shared hint cap
family_container_unfolded_press   the same row at FoldLevel.FULLY_EXPANDED; foldable metadata grows,
                                  while conversation visibility and the shared hint cap stay unchanged
hint_mode_auto_refresh            an Agents-tab refresh tick while hint mode is active
```

Spans are sliced per step rather than pooled, so the plain-agent and family-container
costs can be compared independently. Each step also carries a `hint_counters` block
(`annotated_chars`, `hints`, `commit_views`, `header_summary`, `family_container`) so a
duration change can be attributed to the document actually getting smaller rather than
to a quieter machine.

Run just these scenarios and print the table:

```bash
pytest -s -m slow tests/perf/bench_tui_trace.py::test_view_hints_scenario
```

Regenerate the committed baseline (5 runs, median per step and span, plus every raw
run):

```bash
python -m tests.perf.bench_tui_trace --view-hints-baseline
# writes tests/perf/baselines/view_hints_baseline.json
```

Compare against `tests/perf/baselines/view_hints_baseline.json` rather than a transient
capture. Two caveats when reading it:

- `wall_ms` measures key dispatch through Pilot settle, so it carries unrelated repaint
  work and is much larger and much noisier than the spans. Compare the per-step `spans`
  table, not `wall_ms`.
- An `agents.view_hints_refresh` span can appear inside a press step: a detail repaint
  often lands inside that step's settle window. That is real behavior, not bookkeeping
  noise.

Run the regression floor after changing this path:

```bash
just view-hints-perf-check
```

The floor compares traced spans against the committed baseline and ignores wall-clock
Pilot settle time. It also checks that warm repeat presses and unchanged auto-refreshes
do not rescan annotated text, and that family rows stay within the shared hint scan cap
at both metadata levels. If long output is capped, ACE shows a dim notice in the detail
panel; hints are not generated past that notice. The committed baseline remains the
synchronous pre-optimization reference and is not rewritten merely because conversation
sections became fold-inert.

## Targets per phase gate

The targets below come from `sdd/research/202604/sase_perf_research.md` and are restated
here so each phase agent has a single page to check against. A phase is green when the
relevant targets are met **without regressing** any other span.

```text
j/k highlight p95             < 16 ms
key-to-paint p95              < 33 ms
debounced detail paint        < 150–250 ms
warm Patch reload, 1k    < 100 ms
no-change auto-refresh stall  ~0 ms (event-driven path; Phase 7)
large reply first paint       immediate plain render, syntax later/optional
```

Per-phase responsibilities:

- **Phase 2** (Patch j/k hot path): `widget.patch_list.update_list` call count drops to
  zero for j/k navigation; `update_highlight` p95 < 16 ms at 500 patches.
- **Phase 3** (data layer): warm Patch reload < 100 ms at 1k specs; `patch.filter` p95
  should drop materially after the snapshot cache and query context land.
- **Phase 4** (agent panel + list): `agents.refresh_panel_highlights` and
  `widget.agent_list.update_highlight` p95 < 16 ms at 1k agents.
- **Phase 5** (incremental loader): `agents.load_from_disk` near zero on a no-change
  auto-refresh.
- **Phase 6** (artifact + render caching): `widget.prompt_panel.update_display` /
  `widget.file_panel.update_display` immediate first paint on the largest reply fixture.
- **Phase 7** (event-driven auto-refresh): no-change auto-refresh shows no agents/patch
  spans firing at all.

## Adding a new span

```python
from sase.ace.tui.util.trace import tui_trace

with tui_trace("module.name", count=len(items)):
    ...
```

Names use dotted lowercase. Counters should be ints / strs only — the emitter falls back
to `str(...)` for unknown types via `default=str`, but keeping payloads JSON-friendly
speeds downstream `jq` slicing.

When a span boundary forces a refactor (most existing hot paths split into `foo()` →
`_foo_impl()` so the wrapping context manager doesn't fight indentation rules), keep
both methods next to each other and let the public name stay the trace span name.
