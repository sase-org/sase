# SASE TUI performance log research - 2026-06-20

## Scope

This note digs through local SASE TUI logs and perf artifacts to identify the highest-leverage ways to improve
interactive TUI performance. It focuses on evidence from:

- `~/.sase/perf/tui_jk.jsonl`
- `~/.sase/perf/tui_trace.jsonl`
- `~/.sase/perf/tui_jk.prev.jsonl`
- `~/.sase/perf/tui_trace.prev.jsonl`
- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_jk.jsonl`
- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_trace.jsonl`
- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_profile.txt`
- `~/.sase/perf/agent_launch_tui_20260601_104107/*_trace.jsonl`
- `~/.sase/perf/agent_launch_tui_20260601_104107/*_profile.txt`
- `~/.sase/logs/tui_stalls.jsonl`
- `~/.sase/logs/tui_launch_timing.jsonl`
- `~/.sase/logs/tui.log`
- Prior consolidation: `sdd/research/202606/tui_tmux_performance_consolidated_20260616.md`

Per the project TUI performance guidance, the target for j/k key-to-paint latency is p95 under 16 ms. The same guidance
also says every TUI regression should first be checked for synchronous work on the Textual event loop.

## Summary

The logs show three different performance classes:

1. The TUI frequently misses the j/k paint target even when model mutation is sub-millisecond. Current `tui_jk.jsonl`
   has p95 paint at 43.1 ms, and the 2026-06-16 isolated tmux run had p95 at 51.1 ms.
2. Agent refreshes are the largest repeated background cost. Current `tui_trace.jsonl` has 112
   `agents.load_from_disk` spans totaling 328.7 s, with normal Tier 1 broad loads commonly in the 2-3 s range and one
   normal auto-refresh outlier at 136.0 s.
3. There are still real event-loop stalls. `tui_stalls.jsonl` recorded three 5s+ stalls on 2026-06-20: one from
   synchronous artifact-index maintenance during agent apply, and two from blocking external editor subprocesses.

The top recommendation is still to shrink and quiet the agent refresh path. That is the largest total cost and it feeds
the downstream rendering hitches. The second recommendation is to make the default Agents view patch-friendly and skip
unchanged detail/render work. The third is to remove or explicitly classify the remaining event-loop blocking paths.

## Key measurements

### j/k paint latency

The model-side part of j/k is not the issue. Paint latency is.

| artifact | samples | paint p50 | paint p95 | paint p99 | max | over 16 ms | model p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `~/.sase/perf/tui_jk.jsonl` | 613 | 26.9 ms | 43.1 ms | 127.7 ms | 1033.5 ms | 94.9% | 0.9 ms |
| `~/.sase/perf/tui_jk.prev.jsonl` | 804 | 20.9 ms | 120.4 ms | 2281.8 ms | 5222.8 ms | 54.1% | 0.4 ms |
| `research_20260616/..._jk.jsonl` | 220 | 24.4 ms | 51.1 ms | 146.8 ms | 214.1 ms | 99.5% | 0.1 ms |

Current by-tab detail:

| tab/action | samples | paint p50 | paint p95 | max |
| --- | ---: | ---: | ---: | ---: |
| Changespecs prev | 209 | 25.8 ms | 36.1 ms | 500.2 ms |
| Changespecs next | 194 | 24.5 ms | 33.1 ms | 134.1 ms |
| Agents next | 119 | 31.2 ms | 46.5 ms | 142.4 ms |
| Agents prev | 63 | 29.4 ms | 74.9 ms | 1033.5 ms |
| AXE next | 16 | 33.2 ms | 45.8 ms | 61.7 ms |
| AXE prev | 12 | 31.5 ms | 74.1 ms | 115.5 ms |

Interpretation: the selection model is fast; paint and continuation work after selection dominate. The old "optimize the
j/k handler itself" path is unlikely to help.

### Agent refresh cost

Current trace totals:

| span | calls | total | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `agents.load_from_disk` | 112 | 328.7 s | 3162.1 ms | 135993.0 ms |
| `agents.full_history_refresh` | 1 | 32.2 s | 32206.2 ms | 32206.2 ms |
| `agents.apply_loaded_agents_prepared` | 133 | 27.8 s | 176.3 ms | 23295.5 ms |
| `agents.load_artifact_delta_from_disk` | 22 | 16.6 s | 1798.5 ms | 5040.7 ms |
| `agents.worker_prep` | 111 | 6.3 s | 126.3 ms | 234.3 ms |

The most important outlier in `~/.sase/perf/tui_trace.jsonl` was not explicit full-history:

```text
2026-06-16 08:00:06 agents.load_from_disk 135992.97 ms
source=auto_refresh full_history=false data_cost=tier1_broad_load
tier=tier1 artifact_source=artifact_index used_artifact_index=true
```

The normal Tier 1 path also repeatedly landed in the 2-3 s range:

- 2026-06-15 21:31:24 startup: 2238.6 ms
- 2026-06-15 21:33:38 startup: 2294.5 ms
- 2026-06-15 21:34:59 auto-refresh: 3402.2 ms
- 2026-06-19 09:42:44 auto-refresh: 4973.4 ms
- 2026-06-19 09:43:02 starting poll: 4562.0 ms

The 2026-06-16 isolated trace shows the same pattern at smaller scale:

| span | calls | total | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `agents.load_from_disk` | 11 | 28.2 s | 5788.5 ms | 8823.7 ms |
| `agents.full_history_refresh` | 1 | 14.5 s | 14533.4 ms | 14533.4 ms |
| `agents.apply_loaded_agents_prepared` | 17 | 1.6 s | 282.4 ms | 1197.3 ms |

Interpretation: moving disk work off the event loop is necessary but no longer sufficient. The worker path is still too
broad, and refresh completion still hands enough work back to the UI thread to cause visible hitches.

### Detail and rendering cost

Current trace totals:

| span | calls | total | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `widget.agent_detail.update_display` | 151 | 14.3 s | 221.1 ms | 386.7 ms |
| `widget.prompt_panel.update_display` | 151 | 12.7 s | 181.7 ms | 368.6 ms |
| `agents.refresh_display` | 130 | 4.7 s | 221.5 ms | 391.7 ms |
| `agents.final_display_refresh` | 144 | 3.0 s | 59.5 ms | 284.4 ms |
| `agents.refresh_panel_widgets` | 121 | 2.4 s | 51.7 ms | 283.3 ms |
| `widget.agent_list.update_list` | 345 | 2.1 s | 8.9 ms | 275.7 ms |

The June 16 profile also shows expensive render/compositor work:

- `AgentPromptPanel.render_lines`: 4.080 s cumulative inside `Compositor._get_renders`.
- `AgentList.render_lines`: 4.993 s cumulative in the fanout launch profile and 1.709 s in the single-launch profile.
- Rich/Textual style and link metadata rendering is prominent under `AgentList._get_option_render`.

The trace shows default grouping blocking patch paths:

| artifact | row patch fallback reason | count |
| --- | --- | ---: |
| current trace | `unsupported_grouping` | 329 |
| June 16 isolated trace | `unsupported_grouping` | 93 |

The source matches the trace: `src/sase/ace/tui/actions/agents/_display_panel_patches.py` explicitly returns
`unsupported_grouping` for `GroupingMode.BY_STATUS`, even when the row's status bucket did not change. Since status
grouping is the default user-facing view, this leaves common update paths more expensive than they need to be.

Interpretation: after the refresh set is reduced, the next bottleneck is unnecessary rendering. The TUI already has
debounced detail updates and lazy syntax caches, but unchanged selected content and default grouped rows still trigger
too much work.

### Event-loop stalls

`~/.sase/logs/tui_stalls.jsonl` has three stalls, all on 2026-06-20:

| time | stall | stack signature | user context |
| --- | ---: | --- | --- |
| 15:58:51 | 5.088 s | `_loading_apply.py` -> `sync_dismissed_agent_artifact_index` -> `rust_terminalize` | Agents tab, last action `launch` |
| 17:02:16 | 5.482 s | `_notification_modals.py` -> `subprocess.run([editor, plan_file])` | Agents tab |
| 17:07:41 | 5.001 s | `_prompt_bar_requests.py` -> `_open_editor_for_agent_prompt` -> `subprocess.run(cmd)` | Agents tab |

`~/.sase/logs/tui.log` then reports recovery after 5.897 s, 54.104 s, and 43.051 s respectively. The two editor cases
may be intentionally suspended terminal-editor sessions, but they still block the Textual loop and show up as TUI
stalls. The index-maintenance case is more concerning because it is ordinary agent apply work.

The source path for the index case is `src/sase/ace/tui/actions/agents/_loading_apply.py`: when dismissed changes are
persisted, `_apply_loaded_agents_prepared_inner()` calls `save_dismissed_agents()` and then
`sync_dismissed_agent_artifact_index()` from the UI-thread continuation.

Interpretation: the project rule "never block the event loop" is still violated in a few places. These are not the most
frequent costs, but they produce the worst user-visible freezes.

### Launch action latency

`~/.sase/logs/tui_launch_timing.jsonl` has 27 launch records:

| operation | samples | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `agent_launch_spawn` | 19 | 205.4 ms | 1387.4 ms | 2214.6 ms |
| `tui_agent_launch` | 8 | 1171.2 ms | 3199.3 ms | 3665.0 ms |

Dominant stages:

| operation | stage | samples | total | p50 | p95 | max |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `tui_agent_launch` | `history_write` | 8 | 6774.5 ms | 696.3 ms | 1488.4 ms | 1539.9 ms |
| `tui_agent_launch` | `low_level_spawn` | 7 | 3769.2 ms | 338.8 ms | 1460.7 ms | 1696.9 ms |
| `agent_launch_spawn` | `linked_repo_resolution` | 19 | 7985.2 ms | 156.5 ms | 1280.4 ms | 2182.8 ms |
| `agent_launch_spawn` | `subprocess_spawn` | 19 | 1039.1 ms | 38.9 ms | 121.5 ms | 184.4 ms |

Launch is already routed through tracked background tasks in the TUI, so this is less directly tied to j/k paint than
refresh/render work. Still, `history_write` and linked-repo resolution are good follow-up targets for making launch
feel more immediate.

### Live hint refresh

`agents.live_hint_refresh` is already deferred, coalesced, navigation-gated, and off-thread. The logs still show
meaningful background churn:

| artifact | calls | total | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| current trace | 125 | 14.2 s | 332.6 ms | 1118.2 ms |
| June 16 isolated trace | 17 | 2.9 s | 352.8 ms | 454.7 ms |

The worst current trace rows had only 2-7 candidates. This suggests per-agent VCS probes can be expensive even after
scope reduction. This is secondary to Tier 1 load and rendering, but it should be tightened after the first two fixes.

## Recommendation: top three changes

### 1. Bound and quiet the agent refresh pipeline

Fix the Tier 1 query/result set first, then add guardrails so it cannot regress into broad refreshes again.

Recommended shape:

- Treat stopped agents without `done.json` as completed/recent in the artifact index, not active.
- Pass a conservative `active_limit` from Python for normal Tier 1 loads.
- Narrow repair and starting-poll paths so normal refresh does not scan or repair historical rows.
- Cache or short-circuit apply by index version, query signature, dismissed-set signature, and visible-row signature.
- When refresh data is unchanged, skip normalization/apply/detail work entirely.

Why this is number one: `agents.load_from_disk` dominates all logs by total time and creates the refresh pressure that
later shows up as paint and detail hitches. Current trace totals 328.7 s in this span, with repeated 2-5 s normal Tier
1 refreshes and a 136 s auto-refresh outlier.

Expected impact: fewer refresh hitches, faster startup settle, lower background CPU, and less work handed back to the
UI thread.

### 2. Make default Agents rendering incremental and skip unchanged detail work

Keep immediate j/k highlight and detail debouncing. The next step is to avoid rebuilding stable content.

Recommended shape:

- Support row patching in `GroupingMode.BY_STATUS` when the row stays in the same bucket.
- When a row changes buckets, rebuild only the affected old/new panels instead of the entire Agents display.
- Add selected-detail signatures keyed by identity plus prompt/reply/tool/file/diff artifact signatures.
- If selected identity and signatures are unchanged, update only cheap header/runtime fields.
- Continue using `LazySyntaxRenderCache`, but avoid invoking prompt-panel render/update paths when content is unchanged.
- Profile `AgentList` row render output after patch support lands; the June profiles show style/link metadata rendering
  under `AgentList.render_lines` as a real paint cost.

Why this is number two: j/k model mutation p95 is under 1 ms, while current paint p95 is 43.1 ms and Agents prev p95 is
74.9 ms. Detail updates p95 at 221.1 ms, prompt-panel updates p95 at 181.7 ms, and default grouped rows logged hundreds
of `unsupported_grouping` row-patch fallbacks.

Expected impact: better p95/p99 navigation paint latency, fewer 100 ms+ detail hitches, and cheaper status/live-hint
updates in the default view.

### 3. Remove real event-loop blockers and classify intentional suspension

Audit the remaining blocking paths that the stall watchdog is catching.

Recommended shape:

- Move `sync_dismissed_agent_artifact_index()` out of `_apply_loaded_agents_prepared_inner()`'s UI-thread continuation.
  Use a tracked background task or an off-thread maintenance queue, then marshal only final state back to the UI.
- Keep `save_dismissed_agents()` off the UI thread when it can write enough data to block.
- Centralize external editor/subprocess launches so intentional `app.suspend()` sessions do not appear as generic TUI
  stalls. Either pause the stall watchdog during explicit suspension or record a separate "suspended external editor"
  state.
- For noninteractive subprocesses launched from TUI actions, route through tracked background tasks or `asyncio.to_thread`
  instead of direct `subprocess.run()`.

Why this is number three: the stall log has only three rows, but each is a 5s+ freeze. The index-maintenance stall is a
direct violation of the TUI perf rule. The editor stalls may be intentional, but they distort stall telemetry and can
freeze background TUI work for tens of seconds.

Expected impact: removes the worst hard freezes and makes future stall logs higher-signal.

## Secondary follow-ups

- Optimize launch latency: `history_write` and `linked_repo_resolution` dominate launch timing. They are less important
  than refresh/render because launch already runs as a tracked task, but they affect perceived launch responsiveness.
- Tighten live hints: keep the current off-thread/coalesced shape, but add per-agent workspace/VCS signatures so rows
  with unchanged worktrees are not reprobed after ordinary refreshes.
- Reduce notification provider churn: trace events show many direct full notification snapshots. Add duration telemetry
  for provider snapshot work before deciding whether this is real cost or just noisy trace volume.

## Validation plan

After implementing the top two changes, rerun:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --tmux --profile ~/.sase/perf/research_YYYYMMDD/tui_profile.txt
```

Drive the same surfaces: Agents j/k bursts, status grouping, tab switches, manual refresh, full-history refresh,
starting-agent polling, and external-editor actions.

Targets:

- `agents.load_from_disk` normal Tier 1 p95 well below 1 s, with no multi-second auto-refresh outliers.
- Agents j/k p95 moving toward the 16 ms target.
- No `unsupported_grouping` fallback for same-bucket row patches in BY_STATUS.
- `widget.agent_detail.update_display` and `widget.prompt_panel.update_display` do not run when selected content
  signatures are unchanged.
- `tui_stalls.jsonl` contains no ordinary agent-apply stalls; intentional external-editor sessions are separately
  classified.
