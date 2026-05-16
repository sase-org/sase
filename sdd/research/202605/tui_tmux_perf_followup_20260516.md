# `sase ace` TUI Perf — Follow-up Profile & Single Most-Impactful Recommendation (2026-05-16)

## Question

After the 2026-05-16 diagnosis ([tui_tmux_perf_diagnosis_20260516.md](./tui_tmux_perf_diagnosis_20260516.md))
identified the post-startup Tier 2 reconcile as the dominant span, what is the single
most-impactful change to make `sase ace` feel faster? Re-run the tmux-driven profile, break
down the Tier 2 cost with `cProfile`, and pick one change.

## TL;DR

**Stop firing the Tier 2 full-history reconcile unconditionally at startup.** It is fired
once per launch as soon as Tier 1 returns "incomplete history", scans ~12 k artifacts on
this home dir, takes ~2.5–3.0 s of wall time, and produces 3,244 historic agents of which
~32 are actually rendered in the default view. Making the reconcile lazy (on demand /
on idle) eliminates the single biggest startup span and the dominant entry on every
trace-spans-by-total-time table since the start of this perf push.

The hot path is one boolean check in
[`_loading_apply.py:316`](../../../src/sase/ace/tui/actions/agents/_loading_apply.py)
and one auto-schedule in
[`_loading_refresh.py:88`](../../../src/sase/ace/tui/actions/agents/_loading_refresh.py).
Rough order of magnitude: ~2.7 s removed from the post-startup TTI on this home dir,
without changing the visible state for default Agents-tab navigation.

## Methodology

### Capture

1. Snapshotted `~/.sase/perf/tui_trace.jsonl` and `~/.sase/perf/tui_jk.jsonl` to
   `~/.sase/perf/research_20260516c/*.before.jsonl`, truncated the live files.
2. Launched the TUI in a fresh tmux window:
   ```bash
   SASE_TUI_PERF=1 SASE_TUI_TRACE=1 sase ace --tmux
   ```
   Output: `sase_tmux_window=sase_tmux_1`, `sase_tmux_session=sase`,
   `sase_tmux_pid=2064104`.
3. Drove the TUI through `tmux send-keys -t sase:sase_tmux_1`:
   - 25× `j`, 25× `k` at ~80 ms cadence on Agents;
   - 15× `j`, 15× `k` at ~40 ms cadence on Agents;
   - Tab cycle `1 → 2 → 3 → 2`;
   - 20× `j` / 20× `k` on Agents;
   - `y` (the actual refresh key — see the prior research doc, not `r`);
   - 30× `j` / 30× `k` on Agents;
   - `q` to exit.
4. Resulting files: 1,234 trace records, 180 j/k samples
   (preserved under `~/.sase/perf/research_20260516c/`).

### Followup probes

Direct loader probes were run from the same installed `sase` Python
(`~/.local/share/uv/tools/sase/bin/python`) to attribute load durations to
tiers and to cProfile a Tier 2 call. The installed tree is the editable
`~/projects/github/sase-org/sase` repo, **not** the `sase_10` workspace where
this research lives; the workspace has the new `AgentLoadState`-on-span
instrumentation queued for the next commit/push, but it was not yet picked
up by the running TUI. Loads were therefore attributed by duration matched
against direct probes (see the table in the next section).

### Independent verification pass

A second pass on the same day repeated the tmux run after reinstalling the
`sase_10` workspace into its local `.venv` and then falling back to the
known-running installed TUI for the tmux portion:

- `sase_10` workspace: `39e1bd026`
- installed TUI used by `/home/bryan/.local/bin/sase`: `~/projects/github/sase-org/sase`
  at `a832adaca`
- capture directory: `~/.sase/perf/research_20260516d/`
- result: 1,188 trace records, 179 j/k samples

The local `.venv` TUI could not be used for the full tmux capture because it
started without the external workspace-provider plugin set needed for the
GitHub-backed `~/.sase/projects/sase/sase.gp` entry and exited during
startup at `get_change_label(...)`. The local workspace still worked for
direct loader probes, so the verification split was:

- use the installed TUI to validate user-visible tmux timing;
- use the current workspace `.venv` to validate the tiered loader state and
  cProfile shape after the new instrumentation landed.

## Raw signal

### Top trace spans (`tui_trace.jsonl`, 1,234 records)

| span                                       |   n |   sum (ms) |     mean |      max |
|--------------------------------------------|----:|-----------:|---------:|---------:|
| **agents.load_from_disk**                  |   3 | **3 542.4**| **1 180.8** | **2 936.1** |
| agents.refresh_debounced                   |  80 |      234.4 |     2.93 |     10.6 |
| changespec.refresh_debounced               | 101 |      101.6 |     1.01 |     14.5 |
| agents.refresh_panel_highlights            |  80 |       96.1 |     1.20 |      8.2 |
| changespec.refresh_display                 |   5 |       92.6 |    18.52 |     34.8 |
| agents.worker_prep                         |   3 |       77.1 |    25.71 |     40.5 |
| widget.agent_detail.update_display_immediate |  80 |     60.1 |     0.75 |      1.5 |
| widget.prompt_panel.update_header_only     |  80 |       46.6 |     0.58 |      1.1 |
| agents.update_info_panel                   | 114 |       46.1 |     0.40 |      0.7 |

`agents.load_from_disk` accounts for **~78 % of the total spanned wall time** in this
session (3,542 ms of ~4,500 ms across the top‑20 spans). Nothing else is in the same
order of magnitude.

### Second tmux capture (`research_20260516d`, 1,188 records)

The independent run reproduced the same shape with slightly lower absolute times:

| span                                       |   n |   sum (ms) |  mean |     max |
|--------------------------------------------|----:|-----------:|------:|--------:|
| **agents.load_from_disk**                  |   3 | **3 404.9**| **1 135.0** | **2 881.9** |
| agents.refresh_debounced                   |  81 |      201.0 |  2.48 |     4.2 |
| changespec.refresh_debounced               | 100 |       84.3 |  0.84 |     1.2 |
| agents.refresh_panel_highlights            |  81 |       83.9 |  1.04 |     2.5 |
| changespec.refresh_display                 |   5 |       79.3 | 15.86 |    20.0 |
| agents.worker_prep                         |   3 |       75.4 | 25.12 |    27.0 |
| widget.agent_detail.update_display_immediate | 80 |      50.7 |  0.63 |     1.2 |
| agents.update_info_panel                   | 104 |       44.3 |  0.43 |     1.5 |

The three load spans were again:

| # |   t+    |   dur     | attribution |
|---|--------:|----------:|-------------|
| 1 |  0.59 s |  300.4 ms | Tier 1 startup |
| 2 |  3.72 s | **2 881.9 ms** | Tier 2 auto-scheduled reconcile |
| 3 | 10.66 s |  222.6 ms | Tier 1 refresh after `y` |

The second run strengthens the conclusion: the multi-second outlier recurs at
the same post-startup offset, while the rest of the UI spans remain
sub-100 ms in aggregate categories.

### Three `agents.load_from_disk` occurrences

| # |   t+    |   dur     | attribution (from direct probe match) |
|---|--------:|----------:|----------------------------------------|
| 1 |  0.60 s |  334.8 ms | **Tier 1** startup (artifact_index, complete=False, 407 agents) |
| 2 |  3.77 s | **2 936.1 ms** | **Tier 2** auto-scheduled reconcile (source_scan, complete=True, 3,244 agents) |
| 3 | 10.66 s |  271.5 ms | Tier 1 refresh after the `y` keypress |

The Tier 2 reconcile begins ~3.2 s after the Tier 1 result is applied, runs in a worker
thread (`asyncio.to_thread`), and is followed by ~18 ms `worker_prep` + ~17 ms
`apply_loaded_agents_prepared` on the UI thread. The reconcile is fired
unconditionally — see "Where the unconditional schedule lives" below.

### Key-to-paint (`tui_jk.jsonl`, 180 samples)

| action | tab          |   n |  p50 |  p95 |   max | mean |
|--------|--------------|----:|-----:|-----:|------:|-----:|
| next   | agents       |  40 | 18.3 | 34.5 |  77.2 | 21.6 |
| prev   | agents       |  40 | 16.8 | 41.9 |  44.5 | 19.2 |
| next   | changespecs  |  50 | 11.0 | 25.3 |  56.5 | 12.1 |
| prev   | changespecs  |  50 | 11.3 | 15.0 |  22.7 | 11.2 |

- `model_ms` p50 < 0.15 ms across the board — state mutation is not the slow part.
- Agents-tab paints are consistently ~6 ms slower than changespecs-tab paints and have a
  noticeably heavier tail (max 77 ms vs 56 ms). The two worst Agents samples land in the
  first j/k burst, consistent with the Tier 2 reconcile worker contending for CPU/GIL
  with the UI render path.

Second-pass key-to-paint was a bit cleaner on Agents but still had the same
basic profile:

| action | tab          |   n |  p50 |  p95 |  max | mean |
|--------|--------------|----:|-----:|-----:|-----:|-----:|
| next   | agents       |  40 | 17.4 | 29.6 | 46.8 | 18.0 |
| prev   | agents       |  39 | 18.1 | 27.0 | 27.4 | 18.3 |
| next   | changespecs  |  50 | 11.1 | 27.3 | 78.0 | 12.4 |
| prev   | changespecs  |  50 | 11.4 | 18.8 | 27.9 | 11.9 |

This means the recommendation should not lean too hard on any single j/k
outlier. The robust finding is the load-span distribution: a repeatable
~2.9 s Tier 2 span appears in both captures, while key-to-paint tails vary
with what else the terminal/event loop is doing.

### Direct loader probe (this home dir)

```
tier1_a   322.4ms  tier=tier1 complete=False src=artifact_index used_idx=True idx_err=None n_agents=407
tier1_b   281.2ms  tier=tier1 complete=False src=artifact_index used_idx=True idx_err=None n_agents=407
tier2_a  2745.8ms  tier=tier2 complete=True  src=source_scan    used_idx=False idx_err=None n_agents=3244
tier2_b  2491.2ms  tier=tier2 complete=True  src=source_scan    used_idx=False idx_err=None n_agents=3244
```

The artifact index at `~/.sase/agent_artifact_index.sqlite` exists, works, and is used.
The Tier 2 cost is intentional source-scan work, not a fallback.

Current-workspace loader probe after `just install` reproduced the tier
metadata directly:

```
load_tiered_agents(False)   307.4ms  tier=tier1 complete=False src=artifact_index used_idx=True  n_agents=32
load_tiered_agents(False)   249.5ms  tier=tier1 complete=False src=artifact_index used_idx=True  n_agents=32
load_tiered_agents(True)   2834.4ms  tier=tier2 complete=True  src=source_scan    used_idx=False n_agents=158
load_tiered_agents(True)   2453.0ms  tier=tier2 complete=True  src=source_scan    used_idx=False n_agents=158
```

The `n_agents` value above is after the current dedup/sort path, not the raw
wire/post-processing count. The raw Tier 2 snapshot still contains 11,899
records and `_load_agents_from_all_sources(...)` still builds 3,244 agent
objects plus 9,122 workflow-step entries before later pruning. The important
ratio is stable: Tier 2 costs roughly 8-11x Tier 1 on this home directory.

### Tier 2 cProfile breakdown

Total Tier 2 wall time: **~3.2 s** (cProfile overhead inflates the natural ~2.7 s).

| segment                                          | wall (ms) | share | source |
|--------------------------------------------------|----------:|------:|--------|
| Rust `sase_core_rs.scan_agent_artifacts`         | **1 457** | 45 %  | `built-in method sase_core_rs.scan_agent_artifacts` |
| Wire dict → dataclass conversion                 |       553 | 17 %  | `agent_scan_wire_conversion._record_from_dict` × 11,899 |
| `_build_workflow_agent_steps_for_record`         |       915 | 29 %  | `_workflow_snapshot_loaders.py:236` × 1,706 |
| `enrich_agent_from_meta` (inside post-processing) |       751 | 23 %  | `_meta_enrichment.py:99` × 9,121 |
| `posix.stat` (Python fs probes)                  |       230 |  7 %  | × 27,523 calls |
| `posix.exists` / pathlib `__fspath__` / `__str__` |       ~440 | 14 %  | × tens of thousands |

(Segments overlap because Python post-processing includes both the workflow-step build
and the meta enrichment; the percentages don't sum to 100 %.)

Two-call manual split confirmed:

- `_artifact_snapshot_for_tui_load(full_history=True)` ≈ **1.89 s** (~76 %)
- `_load_agents_from_all_sources(...)` (post-processing) ≈ **0.59 s** (~24 %)

So even if the Rust scan were free, the Python post-processing alone is ~0.6 s for the
3,244-agent Tier 2 result — still an order of magnitude above the ~70 ms target for a
non-blocking startup.

The current-workspace split was similar:

- `_artifact_snapshot_for_tui_load(full_history=True)` ≈ **1.79 s**
- `_load_agents_from_all_sources(...)` over that snapshot ≈ **0.56 s**
- cProfile total for `load_tiered_agents(full_history=True)` ≈ **3.25 s**
- `sase_core_rs.scan_agent_artifacts` ≈ **1.43 s**
- `_build_workflow_agent_steps_for_record` ≈ **1.03 s** cumulative
- `enrich_agent_from_meta` ≈ **0.87 s** cumulative
- `_record_from_dict` over 11,899 records ≈ **0.63 s** cumulative
- `posix.stat` count remained high: 27,540 calls, ≈ **0.23 s**

### What the reconcile produces vs. what the UI shows

- Tier 1 produces 407 wire records → 32 visible agents in the default Agents tab view.
- Tier 2 produces 11,899 wire records → 3,244 agents → still 32 visible after the same
  fold/filter pipeline because the additional historic agents fold into project groups
  that the UI hides by default.

The user paid 2.7 s of CPU + GIL contention to load ~3,200 agents that are not on screen
and are not exercised by the navigation samples that follow.

## Diagnosis

The 2026-05-16 diagnosis was correct: `agents.load_from_disk` dominates, and within that
span the multi-second outlier is the auto-scheduled Tier 2 reconcile. This follow-up
adds three things:

1. **The reconcile cost is structural, not accidental.** ~45 % of it is the Rust scan
   reading every `agent_artifact_dir`/`meta.json`/`done.json`, ~24 % is unavoidable
   dataclass construction from the resulting wire format, and ~30 % is workflow-step /
   meta enrichment over the full history. Each piece is reasonably efficient — the
   problem is that the work itself is unnecessary at startup for most sessions.
2. **It is fired unconditionally.** The schedule is gated only on
   `load_state.needs_full_history_reconcile`, which is `True` whenever
   `complete_history is False`, which is `True` whenever the home dir has more than
   `_TIER1_RECENT_COMPLETED_LIMIT = 200` completed agents in the index. On any
   established user's home dir that condition is permanent.
3. **The current profiling harness still has attribution friction.** The new
   `AgentLoadState` fields solve load attribution once the running TUI points at the
   instrumented workspace, but `sase ace --tmux` currently force-passes only
   `SASE_TUI_TRACE` and `SASE_TUI_PERF`; it does not force-pass `SASE_TUI_TRACE_PATH`
   or `SASE_TUI_PERF_PATH`. Unless those variables are already in the tmux server
   environment, captures share the default live files and need explicit snapshot /
   truncate / restore handling.

### Where the unconditional schedule lives

```python
# src/sase/ace/tui/actions/agents/_loading_apply.py:316
if (
    load_state is not None
    and load_state.needs_full_history_reconcile
    and not getattr(self, "_agents_refresh_pending_full_history", False)
    and not getattr(self, "_agents_refresh_scheduled_full_history", False)
):
    self._agents_refresh_pending = True
    self._agents_refresh_pending_full_history = True
```

```python
# src/sase/ace/tui/models/agent_loader.py:85
@property
def needs_full_history_reconcile(self) -> bool:
    return not self.complete_history
```

```python
# src/sase/ace/tui/models/agent_loader.py:67
_TIER1_RECENT_COMPLETED_LIMIT = 200
```

So the schedule is "always" for any home dir with > 200 completed agents.

## Most impactful change

**Defer the Tier 2 reconcile until something actually needs the older agents.** Concretely,
swap the unconditional auto-schedule in `_loading_apply.py:316` for a lazy-trigger model:

- Do not schedule a Tier 2 reconcile from `_apply_loaded_agents_prepared_inner`.
  Mark instead a sticky `_agents_history_is_partial = True` flag (or reuse the existing
  `_agents_seen_complete_history` toggle in the inverse direction).
- Schedule the reconcile once, on **first arrival of any trigger that needs historic
  data**, e.g. any of:
  - the user expands a fold whose child range would extend past the Tier 1 window;
  - the user enters a query/filter (`/`) and the filter targets fields not in the
    Tier 1 snapshot (project, name suffix, status=DONE older than the window, etc.);
  - the user pages `G` / scrolls past the last visible Tier 1 row;
  - a long idle window passes (e.g. 30 s with no keypress and no pending refresh),
    so users who never need history pay the cost in the background, far from any
    input that could feel laggy.
- Keep the Tier 1 auto-refresh path unchanged (the periodic `y` / auto-refresh that
  ran at t+10.66 s and re-issued a 271 ms Tier 1 load is what users actually need).

Why this is the single most-impactful change available:

- **It removes the dominant span**. The 2.9 s Tier 2 reconcile is ~78 % of the total
  spanned wall time in this session. No other change available — including optimizing
  any single line in the Rust scan or the Python post-processing — can match the impact
  of not running the work at all.
- **It is a localized change**. The decision lives in two Python files
  (`_loading_apply.py` and `_loading_refresh.py`); no Rust changes, no wire-format
  changes, no cross-repo coordination. The existing `_agents_refresh_pending_full_history`
  / `_agents_refresh_scheduled_full_history` flags already model "I want a Tier 2 pass
  scheduled"; the change is mostly about *when* to set them.
- **It is low-risk for default behavior**. The captured session confirmed the visible
  agent list is identical between Tier 1 and Tier 2 for the default view (32 agents
  either way). Users only see new rows when they expand a fold or scroll into the
  history, which are exactly the trigger conditions above.
- **It pays back compounding cost**. The reconcile also drags ~17 ms of `worker_prep`
  and ~17 ms of `apply_loaded_agents_prepared` onto the UI thread, and it competes for
  GIL/CPU with the early j/k burst (the two worst paints in this session were 77 ms
  and 71 ms, both during the Tier 2 window). Skipping the reconcile removes those
  follow-on costs too.

Implementation nuance from the verification pass: do not implement the lazy trigger as
"raise the Tier 1 limit until complete". The current direct probes show Tier 1 is only
fast because it stays index-backed and bounded. The right state model is "partial
history is known and acceptable for default navigation", with a one-shot full-history
load only when a user action crosses the known Tier 1 boundary or when an explicit idle
policy chooses to prefetch it.

### Acceptance test sketch

After the change, a fresh tmux capture with the same drive script should show:

- exactly one `agents.load_from_disk` span in the first 10 s (the Tier 1 startup load,
  ~300 ms), plus the auto-refresh ~270 ms span at t+10 s;
- no span ≥ 1 s in the trace unless an explicit history-needing action is sent;
- Agents-tab `paint_ms` p95 ≤ 35 ms with no >60 ms outliers in the early navigation
  window (the current capture has two >70 ms outliers right in the Tier 2 contention
  window).

### Honorable mentions (not the chosen change)

- **Cache `_artifact_snapshot_for_tui_load(full_history=True)` on disk and incrementally
  update.** Could amortize the 1.5 s Rust scan, but the post-processing still costs
  ~0.6 s, and incremental invalidation is invasive. Not as cheap or as impactful as
  deferral.
- **Reduce per-record `pathlib.Path` churn and `posix.stat` count in
  `_meta_enrichment.py` / `_workflow_snapshot_loaders.py`.** Likely worth another
  ~150–300 ms once the structural fix is in, but it doesn't move the headline number
  while the reconcile still runs at startup.
- **Optimize the artifact-index-fed Tier 1 path itself (130–170 ms today).** Even
  cutting it in half (~80 ms saved) is small compared to deleting the entire Tier 2
  reconcile.
- **Lift the `_TIER1_RECENT_COMPLETED_LIMIT = 200` cap.** Treats the symptom (the
  "history is incomplete" boolean), not the cause (running a full Tier 2 scan for it).
  Larger Tier 1 windows also raise the Tier 1 cost linearly.

## Pointers to the relevant code

- `src/sase/ace/tui/models/agent_loader.py:67` — `_TIER1_RECENT_COMPLETED_LIMIT = 200`
- `src/sase/ace/tui/models/agent_loader.py:85` — `AgentLoadState.needs_full_history_reconcile`
- `src/sase/ace/tui/models/agent_loader.py:121` — `_query_artifact_index_for_loader` (Tier 1)
- `src/sase/ace/tui/models/agent_loader.py:171` — `_artifact_snapshot_for_tui_load` (Tier 2)
- `src/sase/ace/tui/models/_loaders/_workflow_snapshot_loaders.py:236` — biggest
  per-record post-processing cost during Tier 2
- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py:99` — second biggest per-record cost
- `src/sase/core/agent_scan_wire_conversion.py:105` — `_record_from_dict`, the wire conversion hot loop
- `src/sase/ace/tui/actions/agents/_loading_apply.py:316` — **the unconditional schedule
  to remove / gate**
- `src/sase/ace/tui/actions/agents/_loading_refresh.py:84` — `_schedule_agents_async_refresh`
- `src/sase/ace/tui/util/trace.py` — span tracer (`SASE_TUI_TRACE=1`)
- `src/sase/ace/tui/util/perf.py` — j/k key-to-paint timer (`SASE_TUI_PERF=1`)

## Notes for next capture

- The new `AgentLoadState`-on-span instrumentation queued in the `sase_10` workspace
  (`tier`, `artifact_source`, `complete_history`, `used_artifact_index`, `index_error`)
  was **not** picked up by the running TUI in this session; the editable install points
  to a different repo. Push or sync those commits before the next capture so future
  traces include the load-state fields and the initial-tab seed directly, removing the
  need for the duration-matching trick used here.
- If using `sase ace --tmux` with custom output files, either add
  `SASE_TUI_TRACE_PATH` / `SASE_TUI_PERF_PATH` to the tmux server environment first or
  extend `_profiling_env_args()` to pass those paths explicitly. Otherwise the launched
  window writes to `~/.sase/perf/tui_trace.jsonl` and `~/.sase/perf/tui_jk.jsonl`.
- A bare `just install` of `sase_10` was not enough to run the full TUI against this
  home directory because the external GitHub workspace provider was not present in that
  `.venv`; the TUI exited during startup while rendering a GitHub-backed ChangeSpec.
  Direct loader probes still worked in the local `.venv`.
- Use `y` for manual refresh; `r` is `run_workflow` and focuses the prompt.
- The `tui_jk.jsonl` records do not currently include a `t0`-aligned wall timestamp;
  cross-referencing j/k outliers with trace spans requires aligning on the first
  trace record's `ts`.

## Files preserved

- `~/.sase/perf/research_20260516c/tui_trace.before.jsonl` (pre-session, 1,026 records)
- `~/.sase/perf/research_20260516c/tui_jk.before.jsonl` (pre-session, 142 records)
- `~/.sase/perf/research_20260516c/tui_trace.session.jsonl` (this session, 1,234 records)
- `~/.sase/perf/research_20260516c/tui_jk.session.jsonl` (this session, 180 records)
- `~/.sase/perf/research_20260516d/tui_trace.before_global.jsonl` (pre-second-session snapshot)
- `~/.sase/perf/research_20260516d/tui_jk.before_global.jsonl` (pre-second-session snapshot)
- `~/.sase/perf/research_20260516d/tui_trace.session_global.jsonl` (second session, 1,188 records)
- `~/.sase/perf/research_20260516d/tui_jk.session_global.jsonl` (second session, 179 records)
