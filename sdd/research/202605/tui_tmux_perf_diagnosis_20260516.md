# `sase ace` TUI Slowness — tmux-driven perf diagnosis (2026-05-16)

## Question

Why does the `sase ace` TUI feel slow? Reproduce by launching with
`sase ace --tmux`, drive keypresses through `tmux send-keys`, and read the
JSONL traces saved under `~/.sase/perf/` to localize the bottleneck.

## Methodology

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
   - 10× `j`, then `r` (manual refresh)
   - 15× `k`, return to Agents tab, 20× `j`, 20× `k`
   - `q` to exit
4. `tmux capture-pane -p -t sase:7` confirmed the TUI was redrawing and
   selection was advancing.
5. Parsed the resulting `tui_trace.jsonl` (1,313 records) and
   `tui_jk.jsonl` (143 j/k samples) with a small Python script — code
   embedded inline in the analysis below for reproducibility.

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
|          5 |  260 ms  | post-`r` refresh        |
|          6 |  231 ms  | auto-refresh            |

## Diagnosis

**Primary bottleneck: `agents.load_from_disk` is wildly variable, with a
single 3.3 s outlier during startup and a sustained ~250–800 ms cost on
every later refresh.** Even though
`AceApp._load_agents_async` offloads this call via
`asyncio.to_thread` (`src/sase/ace/tui/actions/agents/_loading_disk.py:232`),
the work itself goes through `load_tiered_agents` →
`_artifact_snapshot_for_tui_load`
(`src/sase/ace/tui/models/agent_loader.py:171`), which scans the artifact
index or falls through to `_scan_artifacts_for_loader`. With the
artifact-index path returning `None`/erroring on this machine it falls
through to a source scan, which is the 3.3 s outlier.

Implications:

1. **Startup is dominated by a single 3.3 s blocking load.** The Agents
   tab is the default landing tab, so first paint on the agents list
   waits behind this. Even though it's in a worker thread, the GIL and
   the `agents.worker_prep` (33–42 ms on the main thread) that immediately
   follows mean the user sees a multi-second freeze before keypresses
   register.
2. **Recurring auto/manual refresh re-pays this cost.** Three more loads
   in the 100 s capture window cost 773 ms, 260 ms, and 231 ms — every
   `r` or 10 s auto-refresh tick spends another quarter-to-three-quarters
   of a second in disk-bound work. During those intervals, j/k paints
   double in latency (cluster of 25–35 ms paints from t=6–10 s and t=21 s
   coincides with loads 1 and 3).
3. **j/k itself is structurally cheap.** Model updates are sub-ms; the
   debounced refresh path averages 2.8 ms. The latency the user perceives
   on the Agents tab is the *load*, not the navigation.
4. **`agents.refresh_debounced` fires 81 times in 31 s** of active key
   activity (median gap 86 ms). This is much higher than the debounce
   window should produce — even if each call is cheap (~2.8 ms), the
   churn is suspicious and worth a follow-up audit.

The Tier 1 artifact index is supposed to keep refresh cost bounded
(`_TIER1_RECENT_COMPLETED_LIMIT = 200`,
`agent_loader.py:67`). Either:

- the index is missing/stale on this machine and we keep falling through
  to `_scan_artifacts_for_loader`, or
- the index query itself is the slow piece.

`load_state.artifact_source` is captured per load but isn't surfaced in
the trace record — adding it as a counter on the
`tui_trace("agents.load_from_disk", ...)` span would tell us which
branch is firing without more instrumentation.

## Recommendations

1. **Surface `tier` / `artifact_source` / `complete_history` on the
   `agents.load_from_disk` span** so future captures can immediately
   distinguish "index hit" from "source scan fallback" without re-running.
2. **Cap the startup load.** Either (a) defer the full load until after
   first paint and show a "loading…" agents list, or (b) treat the
   persistent artifact index as authoritative for the initial paint and
   reconcile in the background. Today the user waits for a synchronous-
   feeling 3.3 s before the Agents tab is interactive.
3. **Investigate the index-fallthrough.** If
   `default_agent_artifact_index_path()` doesn't exist or
   `query_agent_artifact_index` is raising, every load pays full
   source-scan cost. Logging the `index_error` field of `AgentLoadState`
   on the trace span (recommendation 1) would expose this.
4. **Audit `agents.refresh_debounced` cadence.** 81 fires in 31 s with a
   86 ms median gap suggests the debounce isn't actually coalescing
   work; each j/k may be re-arming the timer without amortizing the
   refresh. Even though each call is cheap, the wakeup churn shows up
   in tail-paint latency (the 76 ms and 118 ms paint outliers occurred
   during dense refresh activity).
5. **Repeat the capture once on a freshly indexed home dir** (or with
   `SASE_TUI_TRACE_PATH` pointing at a clean file) to confirm whether the
   3.3 s outlier reproduces. If it does, profile inside the worker
   thread with `pyinstrument` via `sase ace --profile`.

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
# … additional k / tab / r / quit sequences …

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

## Baseline data preserved

- `~/.sase/perf/tui_trace.research_baseline.jsonl` (pre-session, 8 911 records)
- `~/.sase/perf/tui_jk.research_baseline.jsonl` (pre-session, 358 records)
- `~/.sase/perf/tui_trace.jsonl` (this session, 1 313 records)
- `~/.sase/perf/tui_jk.jsonl` (this session, 143 records)
