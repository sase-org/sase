# ACE TUI slowdown consolidated research - 2026-06-25

## Inputs verified

I read both prior agent transcripts:

- `~/.sase/chats/202606/sase-ace_run-260625_062240.md`
- `~/.sase/chats/202606/sase-ace_run-260625_062243.md`

Those transcripts produced two intermediate reports, both read before this
consolidation:

- `sdd/research/202606/tui_current_slowdown_tmux_profile_20260625.md`
- `sdd/research/202606/tui_slowdown_artifact_index_broad_load.md`

The strongest evidence came from:

- `~/.sase/perf/research_20260625/ace_tmux_20260625_002_jk.jsonl`
- `~/.sase/perf/research_20260625/ace_tmux_20260625_002_trace.jsonl`
- `~/.sase/perf/research_20260625/ace_tmux_20260625_002_profile.txt`
- `~/.sase/perf/research_20260625_ace_tmux/tui_jk.run.jsonl`
- `~/.sase/perf/research_20260625_ace_tmux/tui_trace.run.jsonl`
- `~/.sase/perf/research_20260625_ace_tmux/profile_load_output.txt`
- `~/.sase/logs/tui_stalls.jsonl`

Both agents followed the requested shape: launch `sase ace --tmux`, drive the
tmux pane with read-only normal interactions, collect TUI perf/trace/profile
data, and write research under `sdd/research/202606/`.

## Consolidated finding

There are two real slowdown classes, and they should not be collapsed into one
root cause:

1. **Hard freezes:** 5-second watchdog stalls from synchronous subprocess work
   on the Textual event loop, especially live `git diff` in the Agents detail
   header.
2. **Recurring jank:** p95 key-to-paint misses and 160-212 ms spikes caused by
   frequent broad Agents refreshes, usually after watcher paths fall back to
   `unknown_watcher_path`.

The two reports conflict only in their priority call. The stall log proves that
the only non-editor watchdog freezes on 2026-06-25 were detail-header live-diff
calls. The tmux-driven traces prove that normal navigation also misses the
16 ms paint budget because broad refreshes are too frequent and too expensive.

## Evidence

### 1. Watchdog freezes are detail-header subprocess calls

On 2026-06-25, `~/.sase/logs/tui_stalls.jsonl` contains five watchdog stalls:

| Time | PID | Class |
| --- | ---: | --- |
| 06:09:00 EDT | 3340471 | prompt editor wait |
| 06:18:52 EDT | 3340471 | Agents detail live `git diff` |
| 06:19:03 EDT | 3340471 | Agents detail live `git diff` |
| 06:19:24 EDT | 3340471 | Agents detail live `git diff` |
| 06:25:22 EDT | 3340471 | agent-chat editor wait |

The repeated non-editor stack is:

```text
DetailMixin._fire_debounced_detail_update
  -> AgentDetail.update_display
  -> AgentPromptPanel.update_display
  -> build_detail_header_summary
  -> agent_delta_entries
  -> get_agent_diff
  -> provider.diff_with_untracked
  -> subprocess.run
```

The current code still has this synchronous chain:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
  calls `agent_delta_entries(agent)` and `agent_artifact_paths(agent)` from
  `build_detail_header_summary()`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py` calls
  `get_agent_diff(agent)`.
- `src/sase/ace/tui/widgets/file_panel/_diff.py` calls
  `provider.diff_with_untracked(workspace_dir, timeout=10)` on cache miss.
- `src/sase/vcs_provider/plugins/_git_query_ops.py` shells out to `git diff`,
  `git ls-files`, and per-file `git diff --no-index`.

The 1-second diff cache helps only after a synchronous miss completes. It does
not protect the event loop from the miss itself.

The editor waits are real stall records too, but they are user-initiated waits
for an external editor. They should be classified or suspended separately from
accidental TUI freezes.

### 2. Key-to-paint misses are dominated by paint/render/refresh, not selection mutation

Run A, isolated custom paths:

| Samples | Paint p50 | Paint p95 | Paint max | Model p95 | >16 ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 155 | 25.6 ms | 43.5 ms | 208.7 ms | 0.173 ms | 154 |

Run B, global perf files after backup:

| Samples | Paint p50 | Paint p95 | Paint max | Model p95 | >16 ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 257 | 13.9 ms | 34.6 ms | 818.8 ms | 0.112 ms | 74 |

The project target is p95 under 16 ms. Selection/model mutation is consistently
sub-millisecond, so cursor/index state is not the main cost. The immediate
navigation path is also mostly cheap in trace (`agents.refresh_debounced` p95
3.5-6.2 ms; `widget.prompt_panel.update_header_only` p95 below 1 ms in Run B).
The misses come from paint pressure and refresh/detail work landing near
navigation.

### 3. Broad Agents loads are too frequent and too expensive

Both tmux runs show large `agents.load_from_disk` spans:

| Run | Count | Total | p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| A | 8 | 12.3 s | 1692.7 ms | 1702.3 ms |
| B | 17 | 23.3 s | 1754.8 ms | 1794.6 ms |

The broad load runs off-thread, so it did not emit a 5-second watchdog stall in
the isolated tmux runs. It still creates visible jank through GIL-held Python
work and UI-thread continuation work such as `worker_prep`,
`live_hint_refresh`, apply/final display refresh, and competing paints.

The broad-load frequency bug is clear in refresh trace records:

- Run A: 6 `unknown_watcher_path` broad-load fallbacks.
- Run B: 14 `unknown_watcher_path` broad-load fallbacks.
- Only 2 artifact-delta loads were observed in each run.

The current classifier in
`src/sase/ace/tui/actions/event_refresh/_artifact_delta.py` treats any
agent-affecting path that cannot be mapped to an exact artifact dir as
`unknown_watcher_path`; `_agent_artifact_delta_dirs_for_paths()` then escalates
the whole batch to a full broad load. `_auto_refresh.py` correctly prefers
delta refreshes when exact dirty artifact dirs are queued, but the classifier
often prevents that path from being used.

The cost side is also material. Direct profiling of
`load_tiered_agents(full_history=False)` showed roughly:

- 1.2 s in `sase_core_rs.query_agent_artifact_index`.
- 0.6 s in Python post-processing.
- 7,987 `posix.stat` calls and thousands of `Path` operations.

The local artifact index was about 148 MB, with `agent_artifacts` accounting for
roughly 135 MB over about 19k rows. That makes every remaining broad load
expensive even after frequency is fixed.

### 4. Detail rendering has a second-order cost

The isolated traces also show `widget.agent_detail.update_display` and
`widget.prompt_panel.update_display` p95 values around 95-168 ms, with maxima
from 246-314 ms. Some of that is cold-cache cost, but the same full detail path
contains the live-diff call that produced the watchdog stalls. Optimizing the
detail header is therefore both a correctness fix and a navigation smoothness
fix.

## Plan

### Phase 1 - move detail-header enrichments off the event loop

Add a generation-gated Agents detail-header enrichment worker, following the
existing pattern in
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py`.

The synchronous render path should build only cheap header content and read
already-cached enrichment state. A cache miss for own-agent deltas, artifact
paths, memory reads, skill uses, or opened-workspace markers should render a
placeholder or omitted section and start a worker keyed by selected agent
identity, generation, attempt view mode, and pinned attempt number.

The worker should compute the expensive header sections off-thread, including
`agent_delta_entries(agent)` and `agent_artifact_paths(agent)`, then re-render
only if the result still matches the current selection. This mirrors the linked
delta and bead display workers that already exist.

Regression checks:

- Prove `AgentPromptPanel.update_display()` does not synchronously call
  `diff_with_untracked` / `subprocess.run` for an active agent.
- Prove stale worker results do not repaint after selection changes.
- Re-run a tmux navigation burst and confirm no new stall stack contains
  `get_agent_diff`, `diff_with_untracked`, or `agent_artifact_paths`.

### Phase 2 - fix watcher path classification

Teach `_agent_artifact_delta_dir_for_path()` to walk upward to the enclosing
artifact directory for path shapes that currently return unmapped, and treat
genuinely irrelevant paths as `affects_agents=False` instead of broad-load
fallbacks. Use real `unknown_watcher_path` examples from trace/debug logging as
fixtures.

Verification should show `unknown_watcher_path` near zero, artifact-delta loads
dominating watcher refreshes, broad loads mostly limited to startup/tab switch
and the 60-second sanity floor, and key-to-paint p95 moving toward the 16 ms
target.

### Phase 3 - reduce remaining broad-load cost

After broad-load frequency is fixed, make the remaining broad loads cheaper:

- Prune or bound the hot artifact-index working set; avoid storing large blobs
  inline for hot-list queries where possible.
- Move stat-heavy projection/enrichment into the Rust core or make Python reuse
  indexed metadata instead of re-statting thousands of paths.
- Short-circuit apply/final refresh work when loaded data did not materially
  change.

### Phase 4 - classify editor waits

Prompt and chat editor waits are user-initiated, but today they look like
generic freezes in the watchdog log. Either wrap them in an explicit
"external editor suspended" scope or detach/off-thread them if the TUI is
expected to remain responsive.

## Recommendation

Implement Phase 1 first: move Agents detail-header live diff and artifact/context
enrichment out of synchronous `build_detail_header_summary()` and into a
generation-gated background worker. This is the narrowest fix for the only
non-editor 5-second freezes observed on 2026-06-25, it directly enforces the
project rule against subprocess/disk work on the Textual event loop, and it can
reuse the existing linked-delta worker pattern. Treat the watcher-classifier fix
as the immediate second step, because it is the dominant source of recurring
normal-navigation jank once the hard freeze path is removed.
