# ACE TUI current slowdown tmux profiling - 2026-06-25

## Scope

I started a fresh TUI with `sase ace --tmux`, drove the tmux pane with normal
navigation/display interactions, and reviewed the generated `SASE_TUI_PERF`,
`SASE_TUI_TRACE`, pyinstrument, and stall-watchdog data.

The successful isolated run was:

```bash
tmux set-environment -g SASE_TUI_TRACE_PATH /home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_trace.jsonl
tmux set-environment -g SASE_TUI_PERF_PATH /home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_jk.jsonl
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --tmux --profile /home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_profile.txt --tab agents
```

`--tmux` injects `SASE_TUI_TRACE=1` and `SASE_TUI_PERF=1`, but not custom path
variables, so the path variables had to be installed into the tmux server
environment first. I unset both after the run.

The profiled TUI was pane `%21`, PID `3433979`. I drove:

- Agents tab j/k bursts before and after auto-refresh.
- Detail/prompt scrolling.
- Agents grouping/layout/tool-panel display toggles.
- AXE tab j/k navigation.
- Help modal open, scroll, close.
- A wait through one auto-refresh interval.

Artifacts:

| Source | Count / size |
| --- | ---: |
| `/home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_jk.jsonl` | 155 j/k samples |
| `/home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_trace.jsonl` | 2,010 trace rows |
| `/home/bryan/.sase/perf/research_20260625/ace_tmux_20260625_002_profile.txt` | 138.205 s profile, 33.188 s CPU |
| `/home/bryan/.sase/logs/tui_stalls.jsonl` | 42 total stall records, 5 on 2026-06-25 |

No stall-watchdog record was emitted for PID `3433979`. However, the global
stall log had same-morning records from another live TUI PID (`3340471`) that
match the current "seriously slowing down" report. Those stacks are directly
actionable and are included below.

## Findings

### 1. Today's hard freezes are detail-header VCS/editor subprocesses on the event loop

The 2026-06-25 stall records are not artifact-index maintenance. They are mostly
Agents detail rendering and editor waits:

| Time | PID | Tab | Row | Class |
| --- | ---: | --- | ---: | --- |
| 06:09:00 EDT | 3340471 | agents | 0 | prompt editor subprocess wait |
| 06:18:52 EDT | 3340471 | agents | 0 | agent detail live git diff |
| 06:19:03 EDT | 3340471 | agents | 0 | agent detail live git diff |
| 06:19:24 EDT | 3340471 | agents | 0 | agent detail live git diff |
| 06:25:22 EDT | 3340471 | agents | 4 | agent chat editor subprocess wait |

The repeated live-diff stall stack is:

```text
DetailMixin._fire_debounced_detail_update
  -> AgentDetail.update_display
  -> AgentPromptPanel.update_display
  -> build_detail_header_summary
  -> agent_delta_entries
  -> get_agent_diff
  -> provider.diff_with_untracked
  -> CommandRunner._run
  -> subprocess.run
  -> selectors.poll
```

Relevant source:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py:112`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py:148`
- `src/sase/ace/tui/widgets/file_panel/_diff.py:276`
- `src/sase/vcs_provider/plugins/_git_query_ops.py:269`
- `src/sase/vcs_provider/_command_runner.py:27`

`get_agent_diff()` has a 1-second TTL cache, but the cache is populated only
after the synchronous VCS subprocess returns. A miss can therefore block the
Textual event loop for the VCS timeout path. That violates the project TUI perf
rule: no subprocess, disk, or JSON work in action/message handlers.

The editor stalls are separate but have the same event-loop shape:

- `src/sase/ace/tui/actions/agent_workflow/_editor.py:58`
- `src/sase/ace/tui/actions/agents/_panel_detail.py:123`

Those should either be moved off-thread or explicitly treated as "TUI suspended
for external editor" so the watchdog and UX do not report them as generic
freezes.

### 2. Fresh tmux j/k is still over budget, but selection mutation is not the cost

Target from `memory/tui_perf.md`: j/k paint p95 under 16 ms.

Fresh run:

| Samples | Paint p50 | Paint p95 | Paint p99 | Max | Model p95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 155 | 25.6 ms | 44.2 ms | 170.1 ms | 208.7 ms | 0.184 ms |

By tab/action:

| Tab/action | n | Paint p50 | Paint p95 | Max | Model p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Agents next | 67 | 28.4 ms | 52.6 ms | 208.7 ms | 0.190 ms |
| Agents prev | 58 | 24.9 ms | 39.5 ms | 150.9 ms | 0.150 ms |
| AXE next | 18 | 24.2 ms | 54.5 ms | 54.5 ms | 0.137 ms |
| AXE prev | 12 | 24.0 ms | 44.2 ms | 44.2 ms | 0.030 ms |

154 of 155 samples exceeded 16 ms. Only 6 exceeded 50 ms. The model mutation
path is consistently sub-millisecond, so chasing cursor state or index mutation
will not fix the perceived lag. The lag is paint, render, and post-selection
detail work.

### 3. Debounced detail rendering is expensive even when it does not stall

Top trace spans from the isolated run:

| Span | Calls | Total | Mean | p95 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `agents.load_from_disk` | 8 | 12.305 s | 1538.1 ms | 1702.3 ms | 1702.3 ms |
| `widget.agent_detail.update_display` | 20 | 1.687 s | 84.3 ms | 163.9 ms | 246.1 ms |
| `agents.live_hint_refresh` | 10 | 1.666 s | 166.6 ms | 586.8 ms | 586.8 ms |
| `widget.prompt_panel.update_display` | 20 | 1.602 s | 80.1 ms | 161.6 ms | 243.9 ms |
| `agents.worker_prep` | 8 | 817.8 ms | 102.2 ms | 225.1 ms | 225.1 ms |
| `agents.refresh_debounced` | 137 | 591.2 ms | 4.3 ms | 6.2 ms | 35.2 ms |
| `agents.apply_loaded_agents_prepared` | 10 | 163.2 ms | 16.3 ms | 53.2 ms | 53.2 ms |

The pyinstrument profile showed the same shape:

- `AgentPromptPanel.render_lines`: 2.621 s.
- `AgentList.render_lines`: 2.024 s plus another 1.435 s occurrence.
- `AgentInfoPanel.render_lines`: 0.540 s.
- Debounced detail updates sampled in `build_detail_header_summary()`, with
  `agent_artifact_paths()` prominent in the isolated profile and
  `agent_delta_entries() -> get_agent_diff()` prominent in the live stall log.

`update_header_only()` is already correctly cheap and avoids artifact, prompt,
reply, and file reads during immediate j/k. The expensive risk is the debounced
full update path after navigation settles.

### 4. Agent refresh remains broad background work

Every `agents.load_from_disk` record in the isolated run was `tier1_broad_load`
through the artifact index:

| Source | Duration range |
| --- | ---: |
| startup | 1674.9 ms |
| auto-refresh | 1442.6-1702.3 ms |
| tab switch | 1331.3 ms |

This did not produce a watchdog stall in the isolated run because the expensive
load work is off-thread. It still matters: it consumes 12.3 s of wall time over
the session and can compete with rendering. The older June findings about
stopped-without-`done.json` active/completed semantics and Tier 1 broad loads
remain valid, but they are not the source of today's hard freezes.

## Plan

### Phase 1 - remove UI-thread detail-header subprocess and artifact I/O

Implement an Agents detail-header enrichment worker, following the existing
pattern in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py`.

The UI-thread path should:

- Build cheap header text synchronously.
- Read only already-cached enrichment data for DELTAS, ARTIFACTS, memory reads,
  skill uses, and opened workspaces.
- Render omitted/stale enrichment sections while a worker is running.
- Start or refresh a background worker keyed by selected agent identity,
  generation, attempt view mode, and pinned attempt number.
- Re-render only if the worker result still matches the current selection.

The worker should compute:

- `agent_delta_entries(agent)` for live active agents.
- `agent_artifact_paths(agent)` including follow-up prompt artifacts.
- Any context reads that currently touch disk in `build_detail_header_summary()`.

`build_detail_header_summary()` should stop calling `get_agent_diff()` and
`list_agent_artifacts()` synchronously on cache miss. A cache miss should not be
allowed to run `subprocess.run()` from the event loop.

Regression coverage:

- A unit test that monkeypatches VCS `diff_with_untracked` / `subprocess.run`
  and proves `AgentPromptPanel.update_display()` does not call it synchronously
  for an active agent.
- A worker-result freshness test that stale results do not repaint after
  selection changes.
- A focused tmux or Pilot perf validation proving no `tui_stalls.jsonl` stack
  contains `get_agent_diff`, `diff_with_untracked`, or `agent_artifact_paths`
  during Agents j/k bursts.

### Phase 2 - classify or move editor waits

The prompt/chat editor actions intentionally hand control to an external editor,
but they currently look identical to bugs in the stall log.

Recommended shape:

- If the editor should suspend the TUI, add an explicit activity/watchdog
  suspension scope around editor waits so stall records say "external editor"
  instead of "TUI freeze".
- If the editor is expected to be detached, launch it off-thread or with the
  existing background task path and return the event loop immediately.

This is lower priority than live diff because editor waits are user-initiated.

### Phase 3 - continue broad refresh reduction

After the hard freezes are gone, continue the existing refresh/index plan:

- Fix active/completed semantics for stopped agents without `done.json`.
- Add or enforce a Tier 1 active limit.
- Short-circuit unchanged refresh/apply work by index version, query signature,
  dismissed-set signature, and visible-row signature.
- Keep live hints off-thread and navigation-gated, but tighten their candidate
  and cache keys.

This targets the 1.3-1.7 s `agents.load_from_disk` background cost and the
586.8 ms `agents.live_hint_refresh` p95.

## Recommendation

Next best step: implement Phase 1 first. Move own-agent live diff and artifact
enumeration out of `build_detail_header_summary()` and into a generation-gated
background worker, rendering cached or placeholder header sections until the
worker returns.

This is the narrowest change that directly addresses today's hard freezes:
three same-morning watchdog stalls are `get_agent_diff() -> diff_with_untracked()
-> subprocess.run()` on the Textual event loop, while the isolated tmux run
shows the same detail-header path is also the largest post-selection render
cost. The broader artifact-index/Tier 1 refresh work is still important, but it
should come after the event-loop-blocking detail header is fixed.
