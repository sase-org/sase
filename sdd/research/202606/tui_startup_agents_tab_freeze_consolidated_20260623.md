# TUI startup agents-tab freeze - consolidated research 2026-06-23

Status: final consolidation

## Inputs

This consolidates the two independent research transcripts:

- `~/.sase/chats/202606/sase-ace_run-260623_140803.md`
- `~/.sase/chats/202606/sase-ace_run-260623_140807.md`

The transcripts identified these intermediate notes, which were read and then
superseded by this file:

- `sdd/research/202606/tui_startup_agents_tab_freeze_20260623.md`
- `sdd/research/202606/tui_startup_freeze_terminalize_rootcause_20260623.md`

I also verified the conclusion against `memory/tui_perf.md`, the current source,
`~/.sase/logs/tui_stalls.jsonl`, `~/.sase/logs/tui.log`, and the live
`~/.sase/agent_artifact_index.sqlite` database. The runtime stack in the log
points at `/home/bryan/projects/github/sase-org/sase` at commit `d6b9ebe`; this
workspace is now at `7e320feb` after the research commits, but the relevant TUI
and lifecycle source files compare identical.

## Summary

The startup hang was not slow row navigation. It was a Textual event-loop block.
The agents tab had reached the UI, but the main loop was synchronously running
artifact-index dismissed/active-tier maintenance during the first agents refresh
apply. While that call was active, j/k keypresses could not be processed, so the
agents list appeared frozen.

The relevant main-thread stack from the latest startup-adjacent stall is:

```text
_event_refresh.py:_on_auto_refresh
  -> agents/_loading_disk.py:_load_agents_async
  -> agents/_loading_apply.py:_apply_loaded_agents_prepared
  -> agents/_loading_apply.py:_apply_loaded_agents_prepared_inner
  -> sync_dismissed_agent_artifact_index(...)
  -> sync_dismissed_agent_artifact_index_report(...)
  -> _run_active_tier_maintenance(...)
  -> terminalize_stale_active_agent_artifact_index_rows(...)
  -> rust_terminalize(...)
```

This violates the core TUI performance rule: no synchronous disk, JSON, database,
or Rust-index work on the Textual event loop.

## Evidence

`~/.sase/logs/tui_stalls.jsonl` has 32 stall records. Seven are artifact-index
maintenance stalls on the agents tab. The rest are unrelated external
subprocess/viewer/editor waits or other non-startup causes, so the larger global
watchdog outliers should not be treated as direct evidence for this startup
freeze.

The artifact-index stalls map to these recovery durations in `tui.log`:

| Time | PID | Tab | Row | Recovery |
| --- | ---: | --- | ---: | ---: |
| 2026-06-20 15:58:51 | 3419467 | agents | 0 | 5.897s |
| 2026-06-20 17:34:05 | 3846503 | agents | 14 | 6.404s |
| 2026-06-20 18:59:33 | 405618 | agents | 6 | 101.645s |
| 2026-06-21 21:54:28 | 3913034 | agents | 5 | 6.738s |
| 2026-06-23 11:50:22 | 624967 | agents | 5 | 15.006s |
| 2026-06-23 11:51:31 | 624967 | agents | 5 | 65.053s |
| 2026-06-23 14:07:01 | 1352855 | agents | 0 | no recovery line |

The 2026-06-23 14:07:01 record is the most important one for the user report:
it is on the agents tab, at `current_idx=0`, with `activity_state=idle_restored`.
Its process was gone by consolidation time and no recovery line was present, but
the same stack recovered after 65.053s earlier the same day. That is the best
verified match for "almost a minute before I was able to navigate."

The broader `tui.log` history has 31 recovered event-loop stalls, 12 over 30s,
and 6 over 60s, with a max of 328.079s. Those figures are useful as a general
health signal, but they include unrelated waits and should not be over-attributed
to this artifact-index path.

## Code path

`src/sase/ace/tui/actions/agents/_loading_disk.py` does the expensive load and
prep work off-thread, then calls the apply continuation directly on the event
loop:

```text
await asyncio.to_thread(load_agents_from_disk...)
await asyncio.to_thread(prepare_loaded_agents_worker_boundary...)
await asyncio.to_thread(attach_finalize_plan_to_boundary...)
self._apply_loaded_agents_prepared(...)
```

That UI-thread apply step is expected to mutate widgets and in-memory state.
The problem is inside `src/sase/ace/tui/actions/agents/_loading_apply.py`: when
`persist_dismissed_changes` is true, the apply step saves dismissed state and
then calls `sync_dismissed_agent_artifact_index(...)` inline at lines 316-323.

`persist_dismissed_changes` becomes true for orphan cleanup, recovered bundle
identities, or auto-dismissed identities. The first refresh after startup is a
plausible trigger because that is when recovered/orphaned dismissed-state deltas
are discovered on a cold cache.

The lifecycle function is not bounded to projection work. In
`src/sase/core/agent_artifact_index_lifecycle.py`, `sync_dismissed_agent_artifact_index_report`
always calls `_run_active_tier_maintenance(...)` after `_sync_projection(...)`:

```python
with agent_artifact_index_operation_lock():
    report = _sync_projection(index, dismissed, added=added, force=force)
    return _run_active_tier_maintenance(index, report)
```

That unconditional maintenance call reaches
`src/sase/core/agent_scan_facade.py:176`, which acquires the same global
artifact-index operation lock and calls the Rust binding
`terminalize_stale_active_agent_artifact_index_rows`.

There is already a partial startup fix in
`src/sase/ace/tui/actions/startup.py`: `_run_dismissed_index_startup_sync()` runs
`sync_dismissed_agent_artifact_index_report(...)` in `asyncio.to_thread(...)`
after first paint. That prevents this work from blocking `AceApp.__init__` or
first paint. It does not fix the normal agents refresh apply path, which still
calls the same lifecycle function synchronously on the event loop.

## Cost model

The live index at verification time:

| Source | Value |
| --- | ---: |
| `agent_artifact_index.sqlite` | 141,778,944 bytes, about 136 MiB |
| `agent_artifacts` rows | 18,694 |
| projected `dismissed_agents` rows | 43,326 |
| `dismissed_agents.json` | 2,588,965 bytes |
| `agent_name_registry.json` | 30,188,714 bytes |
| `prompt_history.json` | 33,169,590 bytes |
| files under `~/.sase/projects` | 187,485 |
| artifact dirs with `agent_meta.json` | 18,644 |

Current index status reports:

```text
Agent artifact index ready for normal refresh: 545 visible rows, 43326 dismissed identities
```

Current `agent_artifacts.status` distribution:

| Status | Rows |
| --- | ---: |
| `done` | 15,530 |
| `completed` | 2,631 |
| `running` | 349 |
| `waiting` | 121 |
| `failed` | 60 |
| `starting` | 1 |

The Rust terminalizer in
`/home/bryan/projects/github/sase-org/sase-core/crates/sase_core/src/agent_scan/index.rs`
does two expensive things on every invocation:

1. `repair_abandoned_agent_artifact_index_rows(...)` runs an unindexed
   `record_json LIKE '%"outcome":"abandoned"%'` query and deserializes matching
   JSON rows. The current database has 15,523 bare abandoned matches; the exact
   repair query returns 6,995 rows and 17,541,415 bytes of `record_json`.
   A read-only warm replay of that query took 172-187 ms before Rust
   deserialization and before cold-cache effects.
2. `select_terminalization_candidates(...)` currently returns 255 no-marker
   candidates. Each candidate can trigger marker signature checks,
   `fs::read_dir`, per-entry `stat`, optional artifact rescans/upserts, and a
   project-file read to check workspace claims.

This explains the startup shape. Immediately after launch, the 136 MiB SQLite
file and thousands of artifact directories are likely cold in the OS page cache.
The same path that is hundreds of milliseconds warm can become many seconds, and
when it runs on the event-loop thread it blocks input handling completely.

I did not rerun the mutating terminalizer during consolidation. The prior agents
timed no-op calls after cleanup at roughly 220-787 ms with 255 skipped rows,
which is consistent with the read-only database and filesystem cost model above.

## Ruled out

Import-time startup cost can delay first paint, but the 14:07 stall happens
inside Textual's running event loop after `_on_auto_refresh`. It does not match
an import-time or `AceApp.__init__` stall.

The j/k model update path is not the cause of a minute-long freeze. Existing
performance data shows agents-tab paint is over the 16 ms target during normal
navigation, but the selection model work is sub-ms to low-ms. That is a real
secondary responsiveness problem, not this hard startup block.

External editor/viewer/subprocess stalls dominate the raw watchdog count, but
they are not the agents-tab startup freeze. The directly relevant records are
the seven artifact-index stacks above.

## Relationship to prior work

This was already identified as the top issue in
`sdd/research/202606/tui_performance_log_research_consolidated_20260620.md`:
move `sync_dismissed_agent_artifact_index()` and active-tier terminalization out
of the UI-thread apply continuation, and gate terminalization so it cannot run
on every apply. The 2026-06-23 stall proves that recommendation had not been
fully implemented.

The older `sdd/research/202606/tui_tmux_performance_consolidated_20260616.md`
also remains relevant: stopped-without-`done.json` semantics keep stale active
rows in the index, which feeds the no-marker candidate set that terminalization
must keep revisiting.

## Recommended solution

Implement the fix in layers, but land Layer 1 first because it directly removes
the user-visible freeze.

Layer 1: remove the event-loop block.

- Split dismissed projection sync from active-tier terminalization in
  `agent_artifact_index_lifecycle.py`. `sync_dismissed_agent_artifact_index_report()`
  should not unconditionally call `_run_active_tier_maintenance(...)`.
- Replace the direct `sync_dismissed_agent_artifact_index(...)` call in
  `agents/_loading_apply.py` with a coalesced background maintenance request.
  The UI-thread apply should update in-memory dismissed state, persist the small
  dismissed file if needed, finish widget/list updates, and return.
- Run projection sync and active-tier maintenance off the event loop through the
  existing tracked/background task path (`_submit_tracked_task()` or
  `_submit_background_task()`), with one in-flight artifact-index maintenance
  task at a time and last-request-wins dismissed snapshots.
- Throttle active-tier terminalization so startup/session maintenance runs at
  most once per session or once per configured interval, and skip scheduling
  while the navigation gate says the user is actively moving through rows.

Layer 2: shrink the terminalizer.

- Bound `repair_abandoned_agent_artifact_index_rows(...)` with a persisted
  repair watermark or move it to full rebuild/schema migration only.
- Replace the unindexed `record_json LIKE` abandoned predicate with an indexed
  denormalized column such as `terminal_outcome`.
- Process no-marker candidate revalidation incrementally or with a time budget
  outside the global lock; do not revalidate all 255+ filesystem candidates in
  one event-loop-visible operation.

Layer 3: reduce the data that keeps feeding the slow path.

- Fix stopped-without-`done.json` semantics so old runs become terminal promptly
  instead of remaining in active/no-marker sets.
- Add retention or compaction for the artifact index, prompt history, and agent
  name registry. Those files are large enough that every cold startup scan,
  rewrite, or lock hold is now user-visible.
- Add regression tests that make `_apply_loaded_agents_prepared_inner(...)`
  fail if it synchronously invokes artifact-index terminalization, and validate
  cold startup with `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ...`.

Recommended first change: decouple `_run_active_tier_maintenance(...)` from
dismissed projection sync and schedule terminalization as a throttled tracked
background task. That is the narrowest fix that stops the minute-long startup
navigation freeze while preserving the maintenance work.
