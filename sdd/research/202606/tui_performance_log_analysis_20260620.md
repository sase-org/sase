# ACE TUI performance — log-driven analysis (2026-06-20)

## Scope

This note mines the **on-disk perf logs that the running TUI has already produced** (no new profiling run was
performed) to find where the `sase ace` TUI spends time and stalls, then recommends the top three changes.

It builds on the prior consolidated study
[`tui_tmux_performance_consolidated_20260616.md`](./tui_tmux_performance_consolidated_20260616.md). Where that note
analyzed an isolated tmux harness run, this one reads the *organically accumulated* logs from real sessions through
2026-06-20. The two newest, highest-severity findings here (on-event-loop artifact-index maintenance freezes, and
agent-launch latency) are **not** covered by the 2026-06-16 note; the navigation/loader findings **reconfirm** it with
fresher numbers and show the loader cost has not improved.

## Data sources

All paths under `~/.sase/`. Sizes are meaningful — large state files are themselves part of the problem.

| Source | What it captures | Volume |
| --- | --- | ---: |
| `logs/tui_stalls.jsonl` | Watchdog snapshots when the event loop blocks ≥5 s, with main-thread stack | 3 events |
| `logs/tui.log` | TUI warnings/errors incl. stall detect/recover lines | 185 lines |
| `logs/tui_launch_timing.jsonl` | Per-launch stage timing (`tui_agent_launch`, `agent_launch_spawn`) | 27 launches |
| `perf/tui_jk.jsonl` | Per-keystroke `model_ms`/`paint_ms` (needs `SASE_TUI_PERF=1`) | 613 keystrokes |
| `perf/tui_trace.jsonl` | Hot-path span durations (`SASE_TUI_TRACE=1`) | 18,120 spans |
| `agent_name_registry.json` | Agent name registry (read on launch) | **30 MB** |
| `prompt_history.json` | Prompt history (read-modify-written on every launch) | **33 MB** |
| `dismissed_agents.json` | Dismissed-agent set (re-parsed per refresh) | **2.6 MB** |

Source line references below were verified against the repo at the current `master`. Treat exact line numbers as
approximate — function names are the durable anchors.

## Headline numbers

- **Event-loop freezes are real and current.** The stall watchdog fired three times on 2026-06-20, recovering after
  **5.9 s, 54.1 s, and 43.1 s**. The trace shows `agents.apply_loaded_agents_prepared` (which runs on the UI thread)
  peaking at **23.3 s**.
- **Navigation misses its frame budget on every tab.** `paint_ms` p50 is **25–33 ms** and p95 **35–54 ms**; the target
  is p95 < 16 ms. **96 % (590/613) of recorded keystrokes exceeded 16 ms** — essentially all of it in paint, not model
  logic.
- **`agents.load_from_disk` is still the biggest single time sink:** 112 calls, **328 s cumulative**, mean **2.9 s**,
  worst **136 s**. The loader is off-thread, so it does not freeze the UI directly, but it feeds the on-thread apply and
  starves paint.
- **Agent launch has ~1.3 s of avoidable latency** before the subprocess starts: `history_write` mean **847 ms** (max
  1.54 s) and `linked_repo_resolution` mean **420 ms** (max 2.18 s).

## Findings

### F1 (NEW, highest severity) — Artifact-index maintenance runs on the Textual event loop

All three watchdog stalls and the 23 s apply span trace to the **same on-UI-thread write path**. The relevant stall
stack (`logs/tui_stalls.jsonl`, 2026-06-20):

```
_run_agent_artifact_delta_refresh        (_loading_refresh.py:275)   ← awaited on the event loop
 └ _load_agent_artifact_delta_async      (_loading_disk.py:550)
   └ _apply_loaded_agents_prepared        (_loading_apply.py:256)     ← UI thread
     └ _apply_loaded_agents_prepared_inner(_loading_apply.py:320)
       └ sync_dismissed_agent_artifact_index           (agent_artifact_index_lifecycle.py:134)
         └ _run_active_tier_maintenance                (agent_artifact_index_lifecycle.py:261)
           └ terminalize_stale_active_agent_artifact_index_rows (agent_scan_facade.py:176)
             └ rust_terminalize(...)                    ← Rust FFI: scans up to 10k rows + marker FS checks
```

Why it is bad:

- `_apply_loaded_agents_prepared` is **on the event loop** (it is `await`ed inside message dispatch), not in the
  worker that did `load_from_disk`. The `tui_trace` span confirms it: max **23,295 ms**, p95 176 ms, n=133.
- Inside it, when dismissed-set changes are persisted, it calls `sync_dismissed_agent_artifact_index(...)` →
  `_run_active_tier_maintenance(...)` → `terminalize_stale_active_agent_artifact_index_rows(...)`. That terminalize
  call runs **unconditionally on every apply that persists a dismissal**, scanning up to
  `_STALE_ACTIVE_TERMINALIZE_MAX_ROWS = 10,000` active rows with a 24 h staleness window and doing per-row marker
  filesystem checks — all on the loop, no time-gating, no skip-if-recently-run.
- This directly violates `memory/tui_perf.md` rule #1 (never block the event loop) and rule #2 (route slow
  user-triggered work through `_submit_tracked_task()`).

This is the only finding here that produces *hard multi-second freezes* (as opposed to dropped frames). It is the
clearest, highest-leverage fix.

> Note: the row set this scan churns through is the same bloated active set the 2026-06-16 note diagnosed (≈4,000
> stopped-without-`done.json` rows misclassified as active). Fixing the index *semantics* (that note's R1) shrinks the
> work; getting the maintenance *off the loop and gated* removes the freeze regardless. They are complementary.

### F2 (reconfirmed) — Agents-tab navigation paint is over budget; it's the detail/prompt rebuild

`perf/tui_jk.jsonl` splits each keystroke into `model_ms` (selection mutation) and `paint_ms` (keypress → screen
refresh). The cursor logic is not the problem; paint is.

| tab | n | paint p50 | paint p95 | paint max | model p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| changespecs | 403 | 25.0 ms | 35.0 ms | 500.2 ms | 1.0 ms |
| agents | 182 | 31.0 ms | 54.4 ms | **1033.5 ms** | 0.2 ms |
| axe | 28 | 32.8 ms | 54.3 ms | 115.5 ms | 0.03 ms |

The expensive work behind paint, from `perf/tui_trace.jsonl`:

| span | mean | p95 | max | thread |
| --- | ---: | ---: | ---: | --- |
| `widget.agent_detail.update_display` | 94.9 ms | 221.1 ms | 386.7 ms | UI |
| `widget.prompt_panel.update_display` | 84.2 ms | 181.7 ms | 368.6 ms | UI |
| `agents.live_hint_refresh` | 113.5 ms | 332.6 ms | 1118.2 ms | worker (off-thread) |
| `widget.agent_list.patch_agent_row` | 0.41 ms | 1.1 ms | 276.6 ms | UI (already fast) |

The immediate-highlight path and the 150 ms `DetailPanelDebouncer` are working as designed — the single-row patch is
0.4 ms. The cost is that when the debounce fires, `agent_detail.update_display` / `prompt_panel.update_display` re-render
the panel body (Rich markdown + syntax highlighting) on the UI thread even when the selected identity and content
signature have not changed. There is a `LazySyntaxRenderCache` (24 entries, keyed by agent identity) but it misses on
every newly-highlighted agent during a navigation sweep. This matches the 2026-06-16 note's R5 and remains unfixed.

Minor regression worth flagging: `model_ms` p50 rose from ~0.1 ms (research baseline snapshot) to ~0.5 ms in the
current snapshot — still far under budget, but a 5× drift in the cheap path.

### F3 (reconfirmed, slightly worse) — `agents.load_from_disk` volume

| metric | this run (to 2026-06-20) | 2026-06-16 isolated run |
| --- | ---: | ---: |
| calls | 112 | 11 |
| cumulative | 328 s | 28.2 s |
| mean | 2.9 s | 2.56 s |
| max | **136 s** | 8.82 s |

Spans carry `used_artifact_index: true`, `data_cost: "tier1_broad_load"`, `source` ∈ {`startup`, `auto_refresh`}. So
the index *is* being used, but the Tier 1 query still returns far too many rows (the 2026-06-16 root cause), and the
loader re-parses `dismissed_agents.json` (2.6 MB) **twice per refresh** with no mtime cache. The 136 s outlier is
almost certainly a cold/contended `auto_refresh` overlapping other work. The loader is off-thread, so this shows up as
staleness and paint interference rather than a frozen UI.

### F4 (NEW) — Agent-launch latency: 33 MB prompt-history rewrite + uncached linked-repo resolution

`logs/tui_launch_timing.jsonl` stage breakdown:

`tui_agent_launch` (n=8, total p50 1.17 s):

| stage | mean | % of total | max |
| --- | ---: | ---: | ---: |
| `history_write` | **846.8 ms** | 52.0 % | 1539.9 ms |
| `low_level_spawn` | 538.5 ms | 33.1 % | 1696.9 ms |
| `workflow_dispatch` | 126.6 ms | 7.8 % | 139.7 ms |
| `multi_agent_xprompt_expand` | 121.2 ms | 7.4 % | 183.6 ms |

`agent_launch_spawn` (n=19, total p50 0.21 s):

| stage | mean | % of total | max |
| --- | ---: | ---: | ---: |
| `linked_repo_resolution` | **420.3 ms** | 87.7 % | 2182.8 ms |
| `subprocess_spawn` | 54.7 ms | 11.4 % | 184.4 ms |

- **`history_write`** (`_launch_body.py`, `add_or_update_prompt` → `history/prompt_store.py`) is a **read-modify-write
  of the 33 MB `prompt_history.json`** under an `fcntl.flock` plus `fsync`: it loads the whole file, scans for the
  matching entry to bump `last_used`, and atomically rewrites it. 33 MB × parse+serialize+fsync explains ~850 ms. It is
  off-thread, so it does not freeze the UI, but it gates how fast a launched agent appears.
- **`linked_repo_resolution`** (`agent/launch_spawn.py` → `resolve_linked_repos_for_project`) has **no mtime/signature
  cache**: it re-parses merged global+project YAML and stats workspace dirs on every spawn. It is ~0 ms when the
  workspace is deferred and 0.5–2.2 s when cold. The name-registry already uses an mtime+size signature cache
  (`agent/names/_registry.py`); linked-repo resolution does not.

### F5 (minor) — Editor subprocesses block the loop and trip the watchdog

Two of the three stalls were not bugs in the usual sense — they were synchronous `subprocess.run([editor, ...])` calls
on the event loop:

- `_notification_modals.py:89` `on_dismiss` → opens `$EDITOR` on a plan file (recovered after 54 s).
- `agent_workflow/_editor.py:58` `run_editor` → opens `$EDITOR` for the prompt (recovered after 43 s).

These are user-initiated edits, so the long duration is the user typing. But they still block the loop and pollute the
stall signal. They should run under Textual's `suspend()` / be excluded from watchdog accounting so genuine freezes
(F1) stand out. Low priority.

## Top three recommended changes

### 1. Take artifact-index maintenance off the event loop and gate it (fixes F1)

**Problem:** `sync_dismissed_agent_artifact_index` → `terminalize_stale_active_agent_artifact_index_rows` runs
synchronously on the UI thread inside `_apply_loaded_agents_prepared_inner`, every time an apply persists a dismissal —
a 10k-row + filesystem scan. Observed apply span up to 23 s; watchdog recoveries up to 54 s. This is the only source of
hard freezes in the logs.

**Fix shape:**
- Persist the dismissed-set change optimistically on the UI thread, then route the *index sync + active-tier
  maintenance* through `_submit_tracked_task()` (the established pattern in `task_actions.py` / `_cleanup_tasks.py`) so
  it runs off-thread, is visible in the task indicator, and is counted by quit-confirmation.
- Time-gate `_run_active_tier_maintenance` so terminalize runs at most once per session or per N minutes, not on every
  apply. The 24 h staleness window does not need a per-refresh scan.
- (Complementary, from the 2026-06-16 note's R1) make `agent_meta.stopped_at`-without-`done.json` rows terminal in the
  index so the scan touches hundreds of rows, not thousands.

**Expected impact:** eliminates the 5–54 s freezes; removes the 23 s on-thread apply tail.
**Effort:** medium — crosses into `sase-core` for the gating knob, but the offload is a local TUI change reusing an
existing helper.

### 2. Stop rebuilding unchanged detail/prompt content and render markdown off-thread (fixes F2)

**Problem:** 96 % of keystrokes exceed the 16 ms budget; `agent_detail.update_display` (95 ms) and
`prompt_panel.update_display` (84 ms) re-render Rich markdown + syntax on the UI thread per settled navigation, even
when content has not changed.

**Fix shape:**
- Key the expensive detail/prompt body render by `(selected_identity, prompt/response/diff/tool signatures)`; when the
  identity and signatures are unchanged across a refresh, update only headers/runtime state and skip the body render.
- Move Rich markdown rendering to a worker (`asyncio.to_thread`) and marshal the rendered renderable back with
  `call_after_refresh()`, so the loop only does the cheap paint.
- Pre-warm/expand the `LazySyntaxRenderCache` for the rows adjacent to the cursor so a j/k sweep hits cache instead of
  re-rendering each newly-highlighted agent.
- Make `GroupingMode.BY_STATUS` (the default view) patch-friendly so refreshes patch one row instead of falling back to
  a full rebuild (2026-06-16 R4).

**Expected impact:** moves agents-tab paint p95 toward the 16 ms target and removes the 100 ms–1 s paint spikes.
**Effort:** medium — mostly local TUI widget changes; the signature plumbing is the bulk of the work.

### 3. Cut agent-launch latency: append-only prompt history + cached linked-repo resolution (fixes F4)

**Problem:** ~1.3 s of avoidable launch latency. `history_write` rewrites a 33 MB JSON file under lock+fsync on every
launch (847 ms); `linked_repo_resolution` re-parses config and stats dirs with no cache (420 ms, up to 2.2 s).

**Fix shape:**
- Convert `prompt_history.json` writes to **append-only** (or a bounded/rotated store, e.g. SQLite or a capped JSONL),
  and/or **defer the write until after the subprocess is spawned** so the agent appears first. A 33 MB history that is
  fully rewritten per launch should not exist; cap or compact it.
- Add an mtime+size signature cache to `resolve_linked_repos_for_project`, keyed by `(project, workspace, config
  signature)` — mirror the existing pattern in `agent/names/_registry.py`.

**Expected impact:** ~1.3 s off perceived launch latency; removes the worst 2.2 s cold linked-repo spikes.
**Effort:** low–medium — both are localized; the prompt-history format change is the larger piece.

## Relationship to the 2026-06-16 note

| 2026-06-16 ranked rec | status in 2026-06-20 logs |
| --- | --- |
| R1 index active/completed semantics | Still the dominant data-volume cause; now also implicated in the F1 freeze |
| R2 Tier 1 active-limit guardrail | Not yet in place; loader max regressed to 136 s |
| R3 skip-unchanged refresh | Not yet in place; auto_refresh still drives 112 broad loads |
| R4 `BY_STATUS` patch-friendly | Folded into recommendation #2 |
| R5 reduce detail/render work | Reconfirmed as recommendation #2 |
| R6 / R7 diff badges, live hints | Lower priority; `live_hint_refresh` still 113 ms mean |
| *(none)* on-event-loop index maintenance | **NEW — recommendation #1** |
| *(none)* launch latency | **NEW — recommendation #3** |

## Validation plan

Reproduce with the existing instrumentation, then re-mine these same files:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ~/.sase/perf/research_YYYYMMDD/tui_profile.txt
# drive: agents j/k bursts, dismiss agents (triggers the F1 path), launch agents, tab switches, full-history refresh
```

Target outcomes:
- `logs/tui_stalls.jsonl` records **no** stalls from `sync_dismissed_agent_artifact_index` / `terminalize` (rec #1).
- `agents.apply_loaded_agents_prepared` p95 and max drop to tens of ms (rec #1).
- Agents-tab `paint_ms` p95 < 16 ms with no 100 ms+ spikes; `agent_detail.update_display` skipped when content
  unchanged (rec #2).
- `tui_launch_timing.jsonl` `history_write` < 50 ms and `linked_repo_resolution` near-zero on warm cache (rec #3).

## Appendix — reproduction of the numbers

- Stall stacks: `logs/tui_stalls.jsonl` (3 events, 2026-06-20); recover lines in `logs/tui.log`.
- j/k tables: aggregated from `perf/tui_jk.jsonl` (`model_ms` + `paint_ms` per record, grouped by `tab`).
- Span tables: aggregated from `perf/tui_trace.jsonl` (`span`/`duration_ms`).
- Launch stages: `logs/tui_launch_timing.jsonl` (`stages[].elapsed_ms` grouped by `operation`).
- State-file sizes: `ls -la ~/.sase/{agent_name_registry,prompt_history,dismissed_agents}.json`.
