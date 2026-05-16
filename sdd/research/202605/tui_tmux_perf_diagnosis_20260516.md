# `sase ace` TUI Slowness — tmux-driven perf diagnosis (2026-05-16)

## Question

Why does the `sase ace` TUI feel slow? Reproduce by launching with
`sase ace --tmux`, drive keypresses through `tmux send-keys`, and read the
JSONL traces saved under `~/.sase/perf/` to localize the bottleneck.

## Methodology

### Original tmux capture

1. Saved a baseline copy of existing perf files, then truncated
   `~/.sase/perf/tui_trace.jsonl` and `~/.sase/perf/tui_jk.jsonl` so the
   capture would be scoped to this session.
2. Launched the TUI with both tracers turned on:
   ```bash
   SASE_TUI_PERF=1 SASE_TUI_TRACE=1 sase ace --tmux
   ```
   Output: `sase_tmux_window=sase_tmux_1`, `sase_tmux_session=sase`,
   `sase_tmux_pid=1735083`.
3. Drove the TUI from outside via `tmux send-keys -t sase:7`:
   - 25× `j`, 25× `k` on the Agents tab (slow cadence, ~80 ms between keys)
   - 15× `j`, 15× `k` on the Agents tab (fast cadence, ~40 ms)
   - Tab switches `1` → `2` → `3` → `2`
   - 10× `j`, then `r` (intended as manual refresh; follow-up found this
     is actually `run_workflow`)
   - 15× `k`, return to Agents tab, 20× `j`, 20× `k`
   - `q` to exit
4. `tmux capture-pane -p -t sase:7` confirmed the TUI was redrawing and
   selection was advancing.
5. Parsed the resulting `tui_trace.jsonl` (1,313 records) and
   `tui_jk.jsonl` (143 j/k samples) with a small Python script — code
   embedded inline in the analysis below for reproducibility.

### Follow-up validation

The first pass correctly found the slow span, but it inferred the wrong branch
inside the loader. I ran a second scoped capture and direct loader probes to
close that gap:

1. Preserved the prior perf files under
   `~/.sase/perf/research_20260516/`, then cleared the default trace/perf
   files.
2. Launched `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --tmux`.
   Output: `sase_tmux_window=sase_tmux_1`, `sase_tmux_session=sase`,
   `sase_tmux_pid=1787024`.
3. Let startup settle, drove 30x `j` and 30x `k`, then attempted the prior
   "manual refresh" sequence.
4. Parsed the new 665 trace records and 60 valid j/k samples.
5. Ran direct loader probes from the same installed `sase` environment to
   inspect `AgentLoadState`, artifact index presence, record counts, and a
   `cProfile` breakdown for Tier 1 vs Tier 2.

One caveat: the attempted `r` key sequence was not a refresh. The configured
global refresh key is `y` (`src/sase/default_config.yml:68`); `r` is
`run_workflow` (`src/sase/default_config.yml:55`). In the second capture, it
focused the prompt and later `j` keys typed into the prompt instead of
navigating. The 60 j/k samples before that are still valid navigation samples.

## Raw signal

### Key-to-paint (`tui_jk.jsonl`, 143 samples)

| action | tab          |   n |  p50 |  p95 |   max | mean |
|--------|--------------|----:|-----:|-----:|------:|-----:|
| next   | agents       |  40 | 18.8 | 26.6 |  29.8 | 18.6 |
| prev   | agents       |  38 | 16.9 | 30.4 |  76.0 | 19.5 |
| next   | changespecs  |  30 | 11.7 | 32.6 | 118.7 | 15.8 |
| prev   | changespecs  |  35 | 11.6 | 22.8 |  36.5 | 13.0 |

- Model-update time (`model_ms`) is negligible across the board: p50 0.09 ms,
  p95 0.23 ms, max 0.31 ms. State mutation is **not** the slow part.
- `paint_ms` p50 ≈ 15 ms is acceptable, but the tail is heavy: one
  118 ms paint and a 76 ms paint stand out, and Agents-tab navigation has
  a consistent cluster of 25–30 ms paints.

### Follow-up key-to-paint (`tui_jk.jsonl`, 60 valid samples)

| action | tab    |  n |  p50 |  p95 |  max | mean |
|--------|--------|---:|-----:|-----:|-----:|-----:|
| next   | agents | 30 | 19.5 | 23.2 | 23.5 | 18.4 |
| prev   | agents | 30 | 16.1 | 26.7 | 53.5 | 16.3 |

This reinforces the original conclusion that j/k mutation is not the slow
piece: `model_ms` stayed below 0.4 ms, with most samples below 0.1 ms. With no
agent load overlapping, paints were usually in the 10-23 ms range.

### Trace spans (`tui_trace.jsonl`, top by total wall time)

| span                                       |   n |   sum (ms) |   mean |   max  |
|--------------------------------------------|----:|-----------:|-------:|-------:|
| **agents.load_from_disk**                  |   6 | **5 293**  | **882** | **3 346** |
| agents.refresh_debounced                   |  81 |    227.6  |   2.81 |   12.3 |
| agents.worker_prep                         |   4 |    134.2  |  33.54 |   42.0 |
| agents.refresh_panel_highlights            |  81 |     87.4  |   1.08 |    1.8 |
| widget.agent_detail.update_display_immediate |  81 |    66.3  |   0.82 |    9.7 |
| changespec.refresh_debounced               |  67 |     61.5  |   0.92 |    1.6 |
| widget.prompt_panel.update_header_only     |  81 |     54.9  |   0.68 |    9.6 |
| agents.update_info_panel                   | 120 |     50.1  |   0.42 |    1.1 |

### `agents.load_from_disk` durations (every occurrence)

| occurrence | duration |  context                |
|-----------:|---------:|-------------------------|
|          1 |  436 ms  | startup, current_tab=None |
|          2 | **3 346 ms** | startup, current_idx=3   |
|          3 |  247 ms  | startup, current_idx=3   |
|          4 |  773 ms  | after tab switch to axe |
|          5 |  260 ms  | post-`r` sequence, likely confounded |
|          6 |  231 ms  | auto-refresh            |

### Follow-up trace spans (`tui_trace.jsonl`, 665 records)

| span                                       |   n | sum (ms) | mean | max |
|--------------------------------------------|----:|---------:|-----:|----:|
| **agents.load_from_disk**                  |   3 | **3 416** | **1 139** | **2 848** |
| agents.refresh_debounced                   |  62 |    179.8 |  2.9 | 22.0 |
| agents.worker_prep                         |   3 |     91.3 | 30.4 | 38.8 |
| agents.refresh_panel_highlights            |  62 |     67.3 |  1.1 |  2.9 |
| widget.agent_detail.update_display_immediate | 62 |   58.6 |  0.9 | 17.8 |
| agents.apply_loaded_agents_prepared        |   3 |     56.1 | 18.7 | 36.6 |

The second capture's three `agents.load_from_disk` spans:

| t+ | duration | inferred load |
|---:|---------:|---------------|
| 0.58 s | 335 ms | Tier 1 startup load |
| 3.68 s | 2 848 ms | Tier 2 full-history reconcile |
| 10.61 s | 233 ms | later Tier 1 refresh |

The timing lines up with the code path in
`src/sase/ace/tui/actions/agents/_loading_apply.py:316`: after an incomplete
Tier 1 load, `_apply_loaded_agents_prepared_inner` sets
`_agents_refresh_pending_full_history = True`, and
`_run_agents_async_refresh` schedules one follow-up full-history pass.

### Direct loader probe

The artifact index exists and is used:

- Index path: `~/.sase/agent_artifact_index.sqlite`
- Size: 78,692,352 bytes
- Tier 1 state:
  `AgentLoadState(tier='tier1', complete_history=False, artifact_source='artifact_index', used_artifact_index=True, index_error=None)`
- Tier 2 state:
  `AgentLoadState(tier='tier2', complete_history=True, artifact_source='source_scan', used_artifact_index=False, index_error=None)`

Measured directly from the installed `sase` Python environment:

| operation | wall time | records / agents | source |
|-----------|----------:|-----------------:|--------|
| Tier 1 snapshot | 164-227 ms | 400 records | artifact index |
| Tier 1 full loader | 233-472 ms | 32 agents | artifact index + Python post-processing |
| Tier 2 snapshot | 2 049-2 236 ms | 11 883 records | source scan |
| Tier 2 full loader | 2 714-3 525 ms | 96 agents | source scan + Python post-processing |

Tier 2 scan stats on this home dir:

- `projects_visited=23`
- `artifact_dirs_visited=11883`
- `marker_files_parsed=25704`
- `prompt_step_markers_parsed=9058`
- `json_decode_errors=11`

`cProfile` split for one Tier 2 load:

- 1.41 s in Rust `sase_core_rs.scan_agent_artifacts`
- 0.51-0.58 s converting 11,883 wire records back into Python dataclasses
- 1.08 s in `load_workflow_agent_steps_from_snapshot`, dominated by
  `_build_workflow_agent_steps_for_record` and meta enrichment
- 0.30 s in roughly 27k `posix.stat` calls during Python post-processing

## Diagnosis

**Primary bottleneck: `agents.load_from_disk` is doing an intentional Tier 2
full-history source scan shortly after startup, not falling through because the
Tier 1 index is broken.** The original capture correctly identified
`agents.load_from_disk` as the dominant span, but the follow-up probe shows the
index exists and Tier 1 uses it successfully. The multi-second outlier is the
full-history reconcile scheduled after the first incomplete Tier 1 paint.

Implications:

1. **Startup interactivity is harmed by the Tier 2 reconcile.** Tier 1
   itself is bounded but still costs ~230-470 ms end to end on this home
   dir. Then the follow-up Tier 2 scan walks 11,883 artifacts and can take
   2.7-3.5 s. It runs in a worker thread, but it still competes for CPU/GIL
   during Python wire conversion and post-processing, and it is followed by
   15-39 ms of `agents.worker_prep` and up to 36 ms of apply/finalize work on
   the UI side.
2. **Later refreshes mostly repay Tier 1, not Tier 2.** The 230-260 ms
   refreshes in both captures are consistent with index-backed Tier 1 loads.
   The 773 ms span in the first capture could be a heavier Tier 1 pass under
   contention or a different state mix, but the direct probe does not support
   the "missing index" explanation.
3. **j/k itself is structurally cheap.** Model updates are sub-ms; the
   debounced refresh path averages 2.8 ms. The latency the user perceives
   on the Agents tab is the *load*, not the navigation.
4. **`agents.refresh_debounced` is a misleading span name.** It fires once
   per selection change by design (`watch_current_idx` calls
   `_refresh_agents_display_debounced`). The immediate work updates list
   highlight, info panel, and prompt header; only the expensive detail update
   is actually debounced. So 81 fires in 31 s mostly means "81 navigation
   selections happened", not that the agent disk refresh debounce failed.
5. **The trace context is missing the initial tab.** In both captures,
   `current_tab` stayed `None` until a tab switch because `set_trace_context`
   is only called from `watch_current_tab`. Startup and same-tab traces are
   harder to analyze than they need to be.

## Recommendations

1. **Surface `tier` / `artifact_source` / `complete_history` /
   `used_artifact_index` / `index_error` on `agents.load_from_disk`.** This is
   still the highest-leverage instrumentation change. It would have prevented
   the initial false inference that the index was missing.
2. **Set trace context for the initial tab during app initialization or mount.**
   Current traces say `current_tab=None` until the user switches tabs, which
   obscures startup analysis.
3. **Make Tier 2 reconcile less disruptive.** Options:
   - delay the full-history reconcile until after an idle window;
   - only run it after an explicit action that needs historical rows;
   - make the reconcile incremental, e.g. load older history in chunks;
   - make the artifact index authoritative enough that routine startup does
     not need a full source scan.
4. **Optimize the Tier 2 Python post-processing path.** The source scan itself
   is only part of the cost. Wire conversion, workflow-step construction,
   meta enrichment, and repeated `stat` calls account for another
   ~1.5-2.0 s in the profiled Tier 2 load.
5. **Keep Tier 1 bounded and monitor index query latency.** Tier 1 is working,
   but 230-470 ms is still noticeable if it lands near navigation. The index
   query itself costs ~130-170 ms; Python enrichment and running-field loading
   add the rest.
6. **Do not treat `agents.refresh_debounced` count as evidence of a broken disk
   refresh debounce.** If this span remains useful, consider renaming it to
   something like `agents.selection_refresh_immediate` and adding a separate
   trace around the actual detail debouncer callback.
7. **Use `y`, not `r`, for manual refresh in future captures.** `r` starts the
   workflow path and can focus the prompt, which invalidates later j/k samples.

## Reproducer (for future captures)

```bash
# 1. Snapshot existing perf data
cp ~/.sase/perf/tui_trace.jsonl ~/.sase/perf/tui_trace.research_baseline.jsonl
cp ~/.sase/perf/tui_jk.jsonl    ~/.sase/perf/tui_jk.research_baseline.jsonl
: > ~/.sase/perf/tui_trace.jsonl
: > ~/.sase/perf/tui_jk.jsonl

# 2. Launch TUI in tmux with tracers on
SASE_TUI_PERF=1 SASE_TUI_TRACE=1 sase ace --tmux
# -> sase_tmux_window=sase_tmux_<N>, sase_tmux_session=<S>, sase_tmux_pid=<P>

# 3. Drive it from another shell
for i in $(seq 1 25); do tmux send-keys -t <S>:<N> j; sleep 0.08; done
# ... additional k / tab sequences ...
# Manual refresh is y, not r.
tmux send-keys -t <S>:<N> y

# 4. Analyze
python3 - <<'PY'
import json, statistics
from collections import defaultdict
jk = [json.loads(l) for l in open('/home/bryan/.sase/perf/tui_jk.jsonl')]
trace = [json.loads(l) for l in open('/home/bryan/.sase/perf/tui_trace.jsonl')]
# group / summarize as desired
PY
```

## Pointers to the relevant code

- `src/sase/ace/tui/util/trace.py` — span tracer, gated by `SASE_TUI_TRACE=1`
- `src/sase/ace/tui/util/perf.py` — j/k key-to-paint timer, gated by `SASE_TUI_PERF=1`
- `src/sase/ace/tui/actions/agents/_loading_helpers.py:85` — `agents.load_from_disk` span
- `src/sase/ace/tui/actions/agents/_loading_disk.py:210` — async load wrapper that offloads via `asyncio.to_thread`
- `src/sase/ace/tui/models/agent_loader.py:171` — `_artifact_snapshot_for_tui_load`, the actual heavy lifter
- `src/sase/ace/tui/models/agent_loader.py:121` — `_query_artifact_index_for_loader`, the fast Tier 1 path
- `src/sase/ace/tui/models/agent_loader.py:67` — `_TIER1_RECENT_COMPLETED_LIMIT = 200`
- `src/sase/ace/tui/actions/agents/_loading_apply.py:316` — incomplete Tier 1 apply schedules a full-history reconcile
- `src/sase/ace/tui/actions/agents/_loading_refresh.py:89` — async refresh runner and navigation gate
- `src/sase/default_config.yml:68` — refresh key is `y`; `r` is `run_workflow`

## Baseline data preserved

- `~/.sase/perf/tui_trace.research_baseline.jsonl` (pre-session, 8 911 records)
- `~/.sase/perf/tui_jk.research_baseline.jsonl` (pre-session, 358 records)
- `~/.sase/perf/tui_trace.jsonl` (original session at the time of the
  first report, 1 313 records)
- `~/.sase/perf/tui_jk.jsonl` (original session at the time of the first
  report, 143 records)
- `~/.sase/perf/research_20260516/tui_trace.before_gap_research.jsonl`
  (preserved before the follow-up capture)
- `~/.sase/perf/research_20260516/tui_jk.before_gap_research.jsonl`
  (preserved before the follow-up capture)
- `~/.sase/perf/tui_trace.jsonl` (follow-up session, 665 records)
- `~/.sase/perf/tui_jk.jsonl` (follow-up session, 60 valid j/k navigation samples)
