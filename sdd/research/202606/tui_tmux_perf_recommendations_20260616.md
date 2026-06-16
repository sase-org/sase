# ACE TUI tmux performance research - 2026-06-16

## Request

Launch `sase ace` in tmux with `sase ace --tmux`, drive the pane with keypresses, use the profiling data from that run,
and recommend the most important changes to improve TUI performance.

## Method

I launched a fresh profiled TUI pane from the `sase_12` workspace:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --tmux --profile /home/bryan/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_profile.txt
```

The launcher returned `sase_tmux_session=sase`, `sase_tmux_window=sase_tmux_1`, and PID `378697`. Because this tmux
session already had duplicate `sase_tmux_1` windows, I drove the pane by tmux pane id after resolving the PID to `%41`.

I set tmux global environment variables immediately before launch so this run wrote isolated JSONL traces, then unset
them after the pane inherited them:

- `/home/bryan/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_trace.jsonl`
- `/home/bryan/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_jk.jsonl`
- `/home/bryan/.sase/perf/research_20260616/tui_tmux_20260616_0140Z_profile.txt`

Keypresses exercised:

- Agents-tab `j`/`k` at human cadence and a faster burst.
- Tab switches through AXE/ChangeSpecs/Agents.
- Normal ChangeSpec refresh (`y`).
- Normal Agents refresh (`y`).
- Full-history Agents refresh (`,` then `y`).
- Agents grouping/fold/panel movement (`o`, `O`, `h`, `l`, `J`, `K`).

Caveat: the `sase` entrypoint in this shell is the user-level uv tool install, whose package root is
`/home/bryan/projects/github/sase-org/sase` at commit `4af3a818a`. This SDD note is stored in workspace `sase_12` at
commit `94af72277`. The profiled code and current workspace are close enough for the cited paths, but the runtime source
was the uv tool checkout.

## Key-to-paint results

The run produced 220 `SASE_TUI_PERF` samples.

| tab | action | n | paint p50 | paint p95 | max | model p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| agents | next | 87 | 25.23 ms | 50.78 ms | 85.24 ms | 0.123 ms |
| agents | prev | 80 | 25.54 ms | 57.10 ms | 214.05 ms | 0.121 ms |
| axe | next | 25 | 19.25 ms | 26.27 ms | 27.43 ms | 0.056 ms |
| axe | prev | 25 | 20.50 ms | 30.54 ms | 30.63 ms | 0.023 ms |

The model mutation path remains cheap. Agents-tab `model_ms` is sub-millisecond; the lag is paint/render/load
interference, not cursor math.

## Trace results

The run produced 2,702 spans and 836 events.

| span | n | total | mean | max |
| --- | ---: | ---: | ---: | ---: |
| `agents.load_from_disk` | 11 | 28,151.7 ms | 2,559.2 ms | 8,823.7 ms |
| `agents.full_history_refresh` | 1 | 14,533.4 ms | 14,533.4 ms | 14,533.4 ms |
| `widget.agent_detail.update_display` | 26 | 3,307.7 ms | 127.2 ms | 166.4 ms |
| `widget.prompt_panel.update_display` | 26 | 3,068.0 ms | 118.0 ms | 163.4 ms |
| `agents.load_artifact_delta_from_disk` | 6 | 3,056.1 ms | 509.4 ms | 1,818.9 ms |
| `agents.live_hint_refresh` | 17 | 2,946.2 ms | 173.3 ms | 454.7 ms |
| `agents.apply_loaded_agents_prepared` | 17 | 1,634.6 ms | 96.2 ms | 1,197.3 ms |
| `agents.refresh_debounced` | 249 | 855.2 ms | 3.4 ms | 24.1 ms |
| `agents.worker_prep` | 11 | 695.1 ms | 63.2 ms | 134.0 ms |
| `agents.refresh_display` | 22 | 485.3 ms | 22.1 ms | 105.5 ms |

`agents.load_from_disk` was index-backed for normal Tier 1 refreshes, but still slow:

- Startup Tier 1: 2,485 ms, 416 agents from `artifact_index`.
- Auto-refresh Tier 1: 1,436-2,754 ms, 416-422 agents from `artifact_index`.
- Tab-switch Tier 1: 2,343 ms.
- Manual Tier 1: 1,530 ms.
- Manual full history Tier 2: 8,824 ms disk/load, 2,875 agents plus 39 dismissed from `source_scan`.

## Direct loader probes

Using the same uv-tool Python and `set_include_local_config(False)`, I split Tier 1 into phases:

| load | total | snapshot/index | Python source build | normalize |
| --- | ---: | ---: | ---: | ---: |
| Tier 1 | 2,099 ms | 1,654 ms | 160 ms | 285 ms |
| Tier 1 | 1,824 ms | 1,665 ms | 109 ms | 51 ms |
| Tier 1 | 1,355 ms | 1,176 ms | 126 ms | 52 ms |
| Tier 2 | 5,575 ms | 3,219 ms | 946 ms | 1,409 ms |

The Tier 1 index query returned 4,797 records to produce 346 normalized agents:

- 4,522 records were from the `sase` project.
- 4,667 records were under `ace-run`.
- 4,031 records had `agent_meta.stopped_at` but no `done.json`.
- Only 183 records had `done.json`.
- 1,940 prompt-step markers were carried in the snapshot.
- Records were old: 2,151 from 202603, 1,626 from 202605, 857 from 202606.

The current Rust active query treats every row without `done.json` as active. In
`../sase-core/crates/sase_core/src/agent_scan/index.rs`, `record_is_active()` and `active_where()` key off
`has_done_marker = 0` or non-terminal workflow status, while `RecordSummary.finished_at` only comes from `done.json`,
not `agent_meta.stopped_at`.

## Recommendations

### 1. Fix Tier 1 active/completed semantics in the artifact index

This is the highest-impact change.

Today, thousands of stopped agents without `done.json` are still Tier 1 active rows. That makes every normal startup,
auto-refresh, tab-switch refresh, and manual refresh pay a 1.2-1.7s Rust/SQLite/wire-conversion cost before Python even
builds agents.

Recommended change:

- Treat `agent_meta.stopped_at` as terminal/completed for index query purposes.
- Populate `finished_at` from `done.finished_at` or `agent_meta.stopped_at`.
- Exclude stopped rows without live `running.json`/`waiting.json`/non-terminal `workflow_state.json` from
  `active_where`.
- Include stopped rows in `completed_where`, bounded by `recent_completed_limit`.
- Narrow `repair_stale_rows_for_query()` so it does not refresh signatures for every historical `has_done_marker = 0`
  row.

Expected impact: Tier 1 snapshot size should drop from ~4,800 records to hundreds, directly reducing the current
1.4-2.8s normal refresh cost.

### 2. Add a Tier 1 active-limit guardrail

Rust already supports `active_limit`, but Python passes `active_limit=None` in
`src/sase/ace/tui/models/agent_loader.py`. After fixing stopped-row semantics, add a conservative active limit anyway
to cap future stale/inert row buildup.

Use a value high enough for real active work, then surface `truncated=True`/repair telemetry when the cap is hit. The
existing SASE memory guidance says to prefer bounded hot paths; an unbounded active set lets one index lifecycle bug
become a persistent TUI slowdown.

### 3. Precompute diff badge classification instead of parsing diffs during full-history normalization

Tier 2 cProfile spent about 4.29s in `apply_status_overrides`, with about 2.99s under `_classify_diff_badges`.
The hot path reads 586 diff files and calls `changed_files_from_diff`; that uses `shlex.split` on thousands of diff
headers.

Recommended change:

- Persist `diff_has_real_edits` or changed-path metadata when `diff_path` is produced or indexed.
- Load that value through the artifact index/wire record.
- Only parse a diff on demand when the cached/indexed classification is absent or stale.
- If parsing remains necessary, replace `shlex.split` for the common `diff --git a/foo b/foo` path with a fast parser and
  fall back to `shlex` only for quoted paths.

This mainly improves explicit full-history refresh and any future repair path that normalizes lots of historical rows.

### 4. Make default `BY_STATUS` grouping patch-friendly

The default Agents view is grouped by status. Current incremental paths reject that mode:

- `_try_patch_agent_row()` records `unsupported_grouping` and returns false for `GroupingMode.BY_STATUS`.
- `_try_refresh_agents_display_incremental()` rejects every non-standard grouping.

The trace showed 73 row-patch fallbacks and repeated full display rebuilds because of this. Since the code already has
panel-key information, `BY_STATUS` can be safe when the row's panel key is unchanged. When the key changes, rebuild the
affected old/new panels rather than all panels.

Expected impact: remove common 15-45ms display rebuilds and make deferred live-hint/status patches actually patch rows
in the default view.

### 5. Skip full detail rebuilds when the selected agent's content did not change

After refreshes, `widget.agent_detail.update_display` and `widget.prompt_panel.update_display` repeatedly cost
120-166ms. The final pane capture had a large diff selected (`Lines 1-34 of 1752`), so Rich/Textual rendering is doing
real work even when the selected identity/content is unchanged.

Recommended change:

- Cache detail-panel render inputs by selected identity plus artifact signatures.
- On auto-refresh where the selected row and file/diff signatures are unchanged, update only headers/runtime/countdowns.
- Keep the existing immediate j/k highlight path; do not debounce the cursor.

This will not fix multi-second loader cost, but it should reduce paint tails and post-refresh stutter.

### 6. Throttle live workspace hint refreshes further

`agents.live_hint_refresh` is off-thread, but it still ran 17 times and consumed 2.9s wall time. It is scheduled after
applies and recomputes 5-7 candidates.

Recommended change:

- Key live-hint cache by `(identity, workspace_dir, HEAD/index/worktree signature)`.
- Do not rescan unchanged candidates after ordinary auto-refresh.
- Consider scanning only visible rows first, then selected row, then the rest opportunistically.

This is lower priority than fixing Tier 1, but it reduces background CPU/VCS contention during active sessions.

## What not to chase first

- j/k model mutation is not the bottleneck; Agents `model_ms` p95 was about 0.12ms.
- AXE-tab navigation was acceptable in this run.
- `agents.refresh_debounced` count is mostly selection refresh work, not evidence that the disk refresh debounce is
  broken.

