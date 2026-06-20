# SASE TUI performance log research - consolidated 2026-06-20

## Scope

This consolidates the two independent research notes created from the same request:

- `sdd/research/202606/tui_log_performance_research_20260620.md`
- `sdd/research/202606/tui_performance_log_analysis_20260620.md`

I verified their claims against the current raw logs and source anchors. No new TUI profiling run was started; this note
mines the logs that already existed under `~/.sase/` plus the prior
`sdd/research/202606/tui_tmux_performance_consolidated_20260616.md` study.

The two reports agreed on the important shape: agent refresh is too broad, navigation paint is over budget, and launch
has avoidable latency. The main ranking conflict was whether broad refresh volume or hard event-loop stalls should be
first. The current logs now contain four stalls, two from the artifact-index maintenance path, so this consolidation
ranks the index/refresh pipeline first.

## Data Read

| Source | Evidence |
| --- | --- |
| `~/.sase/logs/tui_stalls.jsonl` | 4 watchdog stalls on 2026-06-20 |
| `~/.sase/logs/tui.log` | Stall detect/recover lines, 187 lines total |
| `~/.sase/logs/tui_launch_timing.jsonl` | 43 launch timing records |
| `~/.sase/perf/tui_jk.jsonl` | 613 j/k key-to-paint samples |
| `~/.sase/perf/tui_trace.jsonl` | 18,120 trace rows |
| `~/.sase/perf/research_20260616/*` | Isolated tmux baseline from the prior study |
| `~/.sase/agent_name_registry.json` | 29 MB |
| `~/.sase/prompt_history.json` | 32 MB |
| `~/.sase/dismissed_agents.json` | 2.5 MB |

The project TUI perf target is p95 j/k key-to-paint under 16 ms, and the main rule from `memory/tui_perf.md` is to keep
synchronous disk, JSON, subprocess, and index work off the Textual event loop.

## Findings

### 1. The agent-index refresh path causes both hard freezes and repeated broad background work

The highest-severity evidence is now two watchdog stalls from the same stack:

```text
_event_refresh.py / _loading_refresh.py
  -> _loading_disk.py
  -> _loading_apply.py:_apply_loaded_agents_prepared_inner
  -> sync_dismissed_agent_artifact_index
  -> _run_active_tier_maintenance
  -> terminalize_stale_active_agent_artifact_index_rows
  -> rust_terminalize(...)
```

`src/sase/ace/tui/actions/agents/_loading_apply.py` persists dismissed changes and then calls
`sync_dismissed_agent_artifact_index()` from the UI-thread apply continuation. That lifecycle function always runs
active-tier maintenance after the dismissed projection sync, and `terminalize_stale_active_agent_artifact_index_rows()`
calls the Rust scanner under the artifact-index operation lock.

Current stall log:

| Stall class | Count | Stall detector samples | Recovery durations |
| --- | ---: | --- | --- |
| Artifact-index maintenance during agent apply/auto-refresh | 2 | 5.088 s, 5.175 s | 5.897 s, 6.404 s |
| External editor `subprocess.run(...)` sessions | 2 | 5.482 s, 5.001 s | 54.104 s, 43.051 s |

The editor cases are user-initiated and should be classified as suspension rather than generic freezes. The artifact
index cases are ordinary refresh/apply work and violate the event-loop rule directly.

The same pipeline also dominates total time even when work is off-thread:

| Trace span | Calls | Total | Mean | p95 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `agents.load_from_disk` | 112 | 328.7 s | 2935.0 ms | 3195.2 ms | 135,993.0 ms |
| `agents.full_history_refresh` | 1 | 32.2 s | 32,206.2 ms | 32,206.2 ms | 32,206.2 ms |
| `agents.apply_loaded_agents_prepared` | 133 | 27.8 s | 209.0 ms | 191.5 ms | 23,295.5 ms |
| `agents.load_artifact_delta_from_disk` | 22 | 16.6 s | 755.8 ms | 1801.0 ms | 5040.7 ms |

The worst `agents.load_from_disk` row was a normal `auto_refresh`, not explicit full-history:

```text
source=auto_refresh full_history=false data_cost=tier1_broad_load
tier=tier1 artifact_source=artifact_index used_artifact_index=true
duration=135,992.97 ms
```

This matches the 2026-06-16 study: the TUI uses the artifact index, but Tier 1 still returns far too many rows because
old stopped-without-`done.json` records look active. That inflates worker load, apply work, dismissed-set sync, and
render pressure.

### 2. j/k selection logic is fast; paint and settled detail rendering are not

Current `tui_jk.jsonl`:

| Samples | Paint p50 | Paint p95 | Paint p99 | Max | Over 16 ms | Model p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 613 | 26.9 ms | 43.1 ms | 129.4 ms | 1033.5 ms | 94.9% | 0.942 ms |

By tab/action, Agents is worst:

| Tab/action | Samples | Paint p50 | Paint p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| Agents next | 119 | 31.2 ms | 48.9 ms | 142.4 ms |
| Agents prev | 63 | 29.4 ms | 75.9 ms | 1033.5 ms |
| Changespecs next | 194 | 24.4 ms | 33.3 ms | 134.1 ms |
| Changespecs prev | 209 | 25.8 ms | 36.1 ms | 500.2 ms |

The model update is not worth chasing first. The expensive work is after selection, when detail and prompt panels settle:

| Trace span | Calls | Mean | p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| `widget.agent_detail.update_display` | 151 | 94.9 ms | 221.6 ms | 386.7 ms |
| `widget.prompt_panel.update_display` | 151 | 84.2 ms | 181.8 ms | 368.6 ms |
| `agents.refresh_display` | 130 | 36.4 ms | 222.2 ms | 391.7 ms |
| `agents.final_display_refresh` | 144 | 20.6 ms | 60.7 ms | 284.4 ms |

The source already has the right shape for immediate feedback: highlight moves immediately, detail updates are
debounced, and the prompt panel has a `LazySyntaxRenderCache`. The remaining problem is unnecessary body work after the
debounce fires. `AgentDetail.update_display()` still calls into `AgentPromptPanel.update_display()` for the selected
agent, and `AgentPromptPanel.update_display()` resets the markdown cache when identity changes. A j/k sweep across new
agents therefore pays Rich markdown/syntax costs on the UI thread.

One nuance from verification: row patching itself is cheap (`widget.agent_list.patch_agent_row` p95 1.1 ms across 8385
rows), but the default `GroupingMode.BY_STATUS` still records `unsupported_grouping` and falls back in common paths. The
current trace has 329 `unsupported_grouping` events, including 66 full display rebuild fallbacks.

### 3. Launch latency is a real TUI responsiveness problem

The launch path is mostly off-thread/tracked, so it does not explain j/k paint. It does explain why launching from the
TUI can feel sluggish.

Current `tui_launch_timing.jsonl`:

| Operation | Samples | p50 | p95 | Max | Mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tui_agent_launch` | 14 | 1195.7 ms | 4550.6 ms | 4550.6 ms | 1823.2 ms |
| `agent_launch_spawn` | 28 | 205.4 ms | 1763.4 ms | 2214.6 ms | 486.3 ms |
| `tui_agent_launch_fanout` | 1 | 10,828.5 ms | 10,828.5 ms | 10,828.5 ms | 10,828.5 ms |

Dominant stages:

| Stage | Samples | Mean | p50 | p95 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tui_agent_launch.history_write` | 13 | 974.8 ms | 818.5 ms | 1853.9 ms | 1853.9 ms |
| `agent_launch_spawn.linked_repo_resolution` | 28 | 412.1 ms | 118.4 ms | 1662.7 ms | 2182.8 ms |
| `tui_agent_launch.low_level_spawn` | 10 | 716.8 ms | 338.8 ms | 2325.7 ms | 2325.7 ms |

Source verification explains the costs:

- `history_write` calls `add_or_update_prompt()`, which locks, reads, mutates, rewrites, and fsyncs the whole
  `prompt_history.json`; that file is now 32 MB.
- `linked_repo_resolution` runs inside `agent_launch_spawn` before spawn and calls `resolve_linked_repos_for_project()`
  each time. The broader codebase has mtime/size cache patterns, but this resolution path does not appear to use one.

### Secondary observations

- `agents.live_hint_refresh` is already off-thread, coalesced, and navigation-gated, but still costs 14.2 s total
  across 125 calls with p95 339.5 ms. Tighten it after the main refresh/render work.
- `dismissed_agents.json` is 2.5 MB. The dismissed-set path now has a faster `added=` projection route, but it still
  participates in the problematic UI-thread index sync.
- The prior 2026-06-16 recommendation to fix artifact-index active/completed semantics remains important. It should be
  treated as part of the same refresh-pipeline fix, not a competing recommendation.

## How To Validate Fixes

Use the existing instrumentation rather than guessing:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ~/.sase/perf/research_YYYYMMDD/tui_profile.txt
```

Drive Agents j/k bursts, dismiss/restore agents, auto-refresh, manual full-history refresh, prompt editor open/close,
and several launches. Success criteria:

- No `tui_stalls.jsonl` stacks from `sync_dismissed_agent_artifact_index` or `terminalize_stale_active_agent_artifact_index_rows`.
- `agents.apply_loaded_agents_prepared` max in tens of ms, not seconds.
- Normal Tier 1 `agents.load_from_disk` p95 under 1 s, with no multi-second auto-refresh outliers.
- Agents-tab j/k paint p95 moves toward the 16 ms target and has no 100 ms+ spikes.
- `history_write` is near-zero or deferred past visible spawn; warm `linked_repo_resolution` is near-zero.

## Top Three Recommended Changes

### 1. Fix the agent-index refresh pipeline

Move `sync_dismissed_agent_artifact_index()` and active-tier terminalization out of the UI-thread apply continuation.
Run it through a tracked background task or maintenance queue, and gate terminalization so it cannot run on every apply.
At the same time, fix the active/completed semantics for stopped-without-`done.json` rows, pass a conservative Tier 1
`active_limit`, and short-circuit unchanged refresh/apply work by index version, query signature, dismissed-set
signature, and visible-row signature.

This removes the hard freezes and attacks the largest cumulative cost: 328.7 s in `agents.load_from_disk`, a 23.3 s
on-thread apply outlier, and two current artifact-index watchdog stalls.

### 2. Stop rebuilding unchanged detail, prompt, and grouped list content

Keep immediate highlight and detail debouncing, but add content signatures for expensive detail/prompt body renders:
selected identity plus prompt, reply, diff, tool, and file artifact signatures. If the signature is unchanged, update
only cheap header/runtime fields. Move Rich markdown/syntax body rendering off-thread where practical, pre-warm or
expand cache coverage around the cursor, and make default `BY_STATUS` row patch/removal paths avoid full display
fallbacks when the row remains in the same bucket.

This targets the user-visible navigation miss: 94.9% of j/k samples exceed 16 ms, while model p95 is still under 1 ms.

### 3. Cut launch latency from prompt history and linked-repo resolution

Stop rewriting a 32 MB `prompt_history.json` before launch is visible. Prefer append-only, capped JSONL/SQLite, or defer
the history write until after the subprocess is spawned. Add an mtime+size signature cache to
`resolve_linked_repos_for_project()` keyed by project/workspace/config inputs.

This should remove roughly 1-2 s from common TUI launches: `history_write` averages 974.8 ms and
`linked_repo_resolution` averages 412.1 ms with 2.18 s cold spikes.
