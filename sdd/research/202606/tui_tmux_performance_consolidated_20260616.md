# ACE TUI tmux performance research - consolidated 2026-06-16

## Scope

This consolidates the two independent profiling notes created from the same request:

- `sdd/research/202606/tui_performance_profiling_20260615.md`
- `sdd/research/202606/tui_tmux_perf_recommendations_20260616.md`

Both agents launched the TUI with `sase ace --tmux`, drove the tmux pane with keypresses, and analyzed
`SASE_TUI_PERF`, `SASE_TUI_TRACE`, and pyinstrument data. This consolidation did not rerun the TUI. It read both
transcripts, read both intermediate notes, then verified the major claims against the current `sase_11` source and the
sibling `sase-core_12` artifact-index code.

## Profiling inputs

| run | data collected | important caveat |
| --- | ---: | --- |
| 2026-06-15 run | 233 s profile, 149 j/k samples, 5,516 trace spans | Used default perf logs and extracted deltas. It found severe repeated loader CPU and render churn. |
| 2026-06-16 run | 220 j/k samples, 2,702 spans plus 836 events, isolated trace/profile files | Runtime entrypoint was the user-level `sase` install at commit `4af3a818a`; source is close enough for the cited paths. |

The isolated 2026-06-16 artifacts still exist under:

- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_jk.jsonl`
- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_trace.jsonl`
- `~/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_profile.txt`

## Consolidated findings

### 1. Agents-tab j/k is still above the target

The target from `memory/long/tui_perf.md` is p95 under 16 ms. Both runs missed it on the Agents tab.

| run | tab/action | n | paint p50 | paint p95 | max | model p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-06-15 | agents next | 84 | 33.3 ms | 54.4 ms | 142.4 ms | ~0.16 ms |
| 2026-06-15 | agents prev | 35 | 32.6 ms | 75.9 ms | 1033.5 ms | ~0.16 ms |
| 2026-06-16 | agents next | 87 | 25.2 ms | 50.8 ms | 85.2 ms | 0.12 ms |
| 2026-06-16 | agents prev | 80 | 25.5 ms | 57.1 ms | 214.1 ms | 0.12 ms |

The cursor/model mutation is not the problem. The lag is after model update: scheduling, paint, detail updates, and
background refresh interference.

### 2. Tier 1 refresh is index-backed but still too broad

Both runs found `agents.load_from_disk` dominating wall time.

| run | calls | total | mean | max |
| --- | ---: | ---: | ---: | ---: |
| 2026-06-15 | 31 | 66.3 s | 2.14 s | 3.40 s |
| 2026-06-16 | 11 | 28.2 s | 2.56 s | 8.82 s |

The important correction to the first note: current Tier 1 loading is not simply "no Rust in the loader path." The TUI
does call the Rust/SQLite artifact index through `query_agent_artifact_index()` for normal Tier 1 loads. The reason it
is still slow is that the query returns far too many records.

The direct probe from the isolated run is the strongest signal:

- Tier 1 returned 4,797 indexed records to produce 346 normalized agents.
- 4,031 records had `agent_meta.stopped_at` but no `done.json`.
- 4,667 records were under `ace-run`; many were old historical records.
- The snapshot carried 1,940 prompt-step markers.
- Normal Tier 1 refreshes cost 1.4-2.8 s before user-visible apply work.

Source verification:

- Python passes `active_limit=None` for Tier 1 in `src/sase/ace/tui/models/agent_loader.py`.
- Rust has an `active_limit` knob, but `record_is_active()` and `active_where()` classify active rows from
  `has_done_marker = 0` or non-terminal workflow status.
- `AgentMetaWire` parses `stopped_at`, and Python uses it as `Agent.stop_time`, but `RecordSummary.finished_at` comes
  only from `done.finished_at`.
- `repair_stale_rows_for_query()` can select all `has_done_marker = 0` historical rows before the Tier 1 result is
  returned.

This makes stopped agents without `done.json` look active to the hot query. That is the highest-impact root cause found
by the two runs.

### 3. Repeated refresh work still interferes with paint

The expensive load is off the Textual event loop, but the TUI still feels blocked because the worker does substantial
Python normalization, status override, and object construction after the Rust query returns. The isolated direct probe
split normal Tier 1 roughly as:

| phase | typical cost |
| --- | ---: |
| Rust/SQLite snapshot plus wire conversion | 1.2-1.7 s |
| Python source build | 0.1-0.2 s |
| Python normalize/status pass | 0.05-0.29 s |

For Tier 2/full-history, Python normalization was much larger: the probe saw 5.6 s total, including 3.2 s snapshot,
0.9 s source build, and 1.4 s normalize.

The old "move all bulk loading to Rust" recommendation is still directionally useful for shared backend logic, but it
is not the first fix. Reducing the indexed result set should come first; then move or cache whatever remains hot.

### 4. Detail and render work create paint tails

Both runs showed expensive detail-panel updates after navigation settles:

- `widget.agent_detail.update_display`: 127-161 ms mean.
- `widget.prompt_panel.update_display`: 118-141 ms mean.
- The 2026-06-15 pyinstrument profile attributed about 25 s to Textual layout/compositing during the session, with
  `AgentToolsPanel.render_lines` prominent in rendered output.

Current source already has important safeguards: j/k highlight is immediate, detail updates are debounced, prompt
rendering has lazy syntax caches, and the tools panel has a cache plus a reread throttle. The remaining issue is that
refreshes and selection settles still rebuild too much detail content when the selected identity and content signatures
did not change.

### 5. Default grouping blocks patch paths

The default Agents view used in the runs is grouped by status. Current incremental display code rejects that path:

- `_try_patch_agent_row()` returns `unsupported_grouping` for `GroupingMode.BY_STATUS`.
- `_try_refresh_agents_display_incremental()` rejects every non-standard grouping.

That means live-hint/status changes that could patch one row often fall back to a broader panel or display rebuild in
the mode users normally see.

### 6. Full-history diff badges are expensive when many rows are normalized

The 2026-06-16 full-history probe found about 4.3 s in `apply_status_overrides`, with about 3.0 s under diff-badge
classification. Current code has an mtime/size cache in `diff_has_real_edits()`, but a cold or broad full-history
normalization can still read hundreds of diff files and parse `diff --git` headers through `shlex.split`.

This is lower priority than fixing Tier 1, but it is a concrete Tier 2 cost.

### 7. Live workspace hints are better but still background churn

Live file-change hints are correctly deferred, coalesced, run off-thread, and gated behind navigation. They still took
2.9-6.2 s aggregate in the profiled sessions. They should stay lower priority than the Tier 1 query fix, but their
candidate set and cache keys can be tightened.

## Ranked recommendations

### R1. Fix artifact-index active/completed semantics for stopped agents

Treat `agent_meta.stopped_at` as terminal/completed for index query purposes.

Recommended shape:

- Populate `finished_at` from `done.finished_at` or `agent_meta.stopped_at`.
- Exclude rows with `stopped_at` and no live `running.json`, `waiting.json`, or non-terminal `workflow_state.json` from
  `active_where()`.
- Include stopped rows in `completed_where()`, bounded by `recent_completed_limit`.
- Narrow `repair_stale_rows_for_query()` so normal Tier 1 refresh does not signature-refresh every historical
  `has_done_marker = 0` row.
- Add core tests for "agent_meta.stopped_at without done.json" so it is completed/recent, not active.

Expected impact: normal Tier 1 snapshots should drop from roughly 4,800 records to hundreds, removing the largest
1.4-2.8 s startup/auto-refresh/manual-refresh cost.

### R2. Add a Tier 1 active-limit guardrail

After R1, use the existing Rust `active_limit` from Python instead of passing `None`. Pick a conservative limit high
enough for real active work, and trace when the cap is hit.

This is a guardrail, not the main fix. It prevents one index lifecycle bug from making every TUI refresh unbounded
again.

### R3. Skip unchanged refresh work and narrow `starting_poll`

Once the index result set is sane, repeated auto-refreshes should be cheap when nothing changed.

Recommended shape:

- Cache or short-circuit Tier 1 query/apply by index version, query signature, and dismissed-set signature.
- If the selected row and visible collection signatures are unchanged, skip full agent normalization/apply and avoid
  detail rebuilds.
- Replace `starting_poll` broad loads with a status-only or artifact-delta check for the starting agent.

Expected impact: removes repeated refresh interference behind j/k and makes the common idle session mostly quiet.

### R4. Make `BY_STATUS` grouping patch-friendly

Support row patches in `GroupingMode.BY_STATUS` when the row's panel key is unchanged. When status changes move a row
between buckets, rebuild only the affected old/new panels instead of the entire display.

This should reduce common 15-45 ms rebuild tails and make deferred live-hint/status patches cheap in the default view.

### R5. Reduce unnecessary detail/render work

Keep the immediate highlight path and the `DetailPanelDebouncer`; they are the right shape. Add stronger content
signature checks around the expensive detail work:

- Key detail-panel body renders by selected identity plus prompt/response/diff/tool artifact signatures.
- On refresh where the selected identity and artifact signatures are unchanged, update only headers/runtime state.
- Keep tools-panel cache invalidation precise and avoid re-rendering identical tool timelines.
- Throttle `_on_countdown_tick()` so it patches only rows whose rendered elapsed-time string changed, and avoid landing
  non-urgent repaint work during active navigation.

Expected impact: improves paint tails after the major loader fix and reduces idle compositing churn.

### R6. Precompute persisted diff-badge classification

Persist `diff_has_real_edits` or changed-path metadata when a diff artifact is produced or indexed, and carry it through
the artifact-index wire record. Only parse `diff_path` on demand when the persisted value is missing or stale.

If parsing remains necessary, handle the common unquoted `diff --git a/foo b/foo` case without `shlex.split`, falling
back to `shlex` only for quoted paths.

Expected impact: mostly improves explicit full-history refresh and any repair path that normalizes many historical
rows.

### R7. Tighten live-hint refresh scope

Keep live hints deferred/off-thread/nav-gated. Add cache keys based on `(identity, workspace_dir, HEAD/index/worktree
signature)` and rescan visible rows first. Do not rescan unchanged candidates after ordinary auto-refresh.

Expected impact: modest background CPU/VCS reduction during active sessions.

## What not to chase first

- j/k cursor/model mutation: p95 is about 0.02-0.16 ms.
- AXE navigation: it was materially better than Agents navigation in the isolated run.
- A broad "rewrite rendering" effort: rendering contributes tails, but the first-order problem is that refreshes feed
  too much data and too many rebuilds into the renderer.
- Merely moving code off the event loop: the project already does much of that. The remaining problem is unbounded work,
  Python normalization/render CPU, and GIL/contention effects from worker activity.

## Validation plan

After R1/R2, rerun the same tmux harness:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --tmux --profile ~/.sase/perf/research_YYYYMMDD/tui_profile.txt
```

Drive the same surfaces: Agents j/k bursts, tab switches, manual refresh, full-history refresh, grouping/fold/panel
movement, and starting-agent polling if available.

Target outcomes:

- Tier 1 query returns hundreds of records, not thousands.
- Normal `agents.load_from_disk` drops well below the current 1.4-2.8 s range.
- Agents j/k p95 moves toward the 16 ms target, with no 100 ms+ paint spikes during ordinary navigation.
- `BY_STATUS` traces show row or affected-panel patches instead of full rebuild fallback.
- Full-history refresh no longer spends seconds parsing persisted diffs when index metadata is available.

The most important acceptance test is a core index test where an artifact with `agent_meta.stopped_at` and no
`done.json` is excluded from active results and appears in recent completed results with a usable `finished_at`.
