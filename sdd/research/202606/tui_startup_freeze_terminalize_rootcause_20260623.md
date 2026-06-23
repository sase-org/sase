# TUI Startup Freeze — Root Cause: Synchronous Artifact-Index Terminalization

Status: Final root-cause research
Date: 2026-06-23
Author: investigation triggered by user report ("almost a minute before I could
navigate agent rows after starting the TUI")

## TL;DR

Starting the TUI froze the Textual event loop for tens of seconds to a minute
because the agents-tab apply path runs **artifact-index "active-tier
maintenance" synchronously on the UI thread**. That maintenance
(`terminalize_stale_active_agent_artifact_index_rows` → Rust) does two O(N)
passes over a now-huge dataset on every call:

1. a full-table `record_json LIKE '%"outcome":"abandoned"%'` scan that pulls and
   deserializes ~7k–15.5k rows (~17.5 MB of JSON) from a **141.7 MB** SQLite
   index, and
2. a per-candidate filesystem re-validation of every no-marker artifact dir
   (`read_dir` + `stat` + project-file read), which is slow on the **cold page
   cache** that exists right after startup.

This is the exact stack flagged as the **#1 unfixed problem** in
`sdd/research/202606/tui_performance_log_research_consolidated_20260620.md`. It
is still firing: a fresh watchdog stall was recorded at **14:07:01 today**
(matching the user's report), and the `tui.log` recovery line history shows
freezes of **57 s, 65 s, 83 s, 86 s, 145 s, and 328 s**. The freeze is getting
worse over time because the abandoned-row scan grows monotonically as more
agents terminalize.

**Recommended fix:** take the active-tier terminalization off the apply hot path
entirely — decouple it from the per-apply dismissed-projection sync, run it as a
gated/throttled tracked background task (never on the event-loop thread), and
shrink the two Rust O(N) passes (repair watermark + indexed predicate). Details
in "Recommended Solution".

## What The User Saw

> "When I just started up the TUI, it took almost a minute before I was able to
> navigate through different agent rows on the agents tab."

This is a classic **event-loop stall**: navigation keys (j/k) cannot be
processed because the loop thread is blocked inside a synchronous call. Nothing
about rendering or model inference is involved — input handling is simply
starved until the blocking call returns.

## Evidence (live instrumentation, captured today)

### 1. The fresh startup stall has the exact terminalize stack

`~/.sase/logs/tui_stalls.jsonl`, most recent entry — PID 1352855 at
**2026-06-23 14:07:01** (≈2 minutes before this investigation began). The
watchdog's captured `main_thread_stack` is unambiguous:

```text
textual timer _tick
  -> actions/_event_refresh.py:535  _on_auto_refresh   ->  await load_agents_async(...)
  -> actions/agents/_loading_disk.py:403   _apply_loaded_agents_prepared(...)
  -> actions/agents/_loading_apply.py:256/320   sync_dismissed_agent_artifact_index(...)
  -> core/agent_artifact_index_lifecycle.py:149/190  sync_dismissed_..._report
  -> core/agent_artifact_index_lifecycle.py:351  _run_active_tier_maintenance
  -> core/agent_scan_facade.py:176  terminalize_stale_active_agent_artifact_index_rows
  -> rust_terminalize(...)
```

The stack is captured from the **main (event-loop) thread**, which proves the
work is running on the loop, not a worker.

### 2. The watchdog under-reports; the true freeze durations are minutes

The stall watchdog logs `stall_seconds` at the moment it crosses its 5 s
threshold (so every record reads ~5 s), but it logs the *real* block length on
recovery. From `~/.sase/logs/tui.log`:

| Metric | Value |
| --- | ---: |
| Recovery events recorded | 31 |
| Freezes > 30 s | 12 |
| Freezes > 60 s | 6 |
| Longest freeze | **328.079 s** |

Recent examples: `recovered after 57.071s`, `65.053s`, `83.528s`, `86.606s`,
`145.540s`, `328.079s`. The 14:07:01 startup stall is the **last line in the
log** with no recovery line yet — consistent with it being the user's
currently-open session (recovery flushes on the watchdog's next cycle).

The freeze is also trending worse:

| Day | Freezes | Max | Median |
| --- | ---: | ---: | ---: |
| 2026-06-20 | 8 | 102 s | 43 s |
| 2026-06-21 | 8 | 146 s | 18 s |
| 2026-06-22 | 1 | 87 s | 87 s |
| 2026-06-23 | 14 | **328 s** | 15 s |

### 3. The dataset the maintenance pass walks is large and growing

| Source | Size / count |
| --- | ---: |
| `agent_artifact_index.sqlite` | **141.7 MB** |
| Index rows (`agent_artifacts`) | **18,692** |
| Artifact dirs on disk (`agent_meta.json` markers) | 18,643 |
| Total directories under `~/.sase/projects` | 23,626 |
| `agent_name_registry.json` | 30.2 MB |
| `prompt_history.json` | 33.2 MB |
| `dismissed_agents.json` | 2.6 MB |

Within the index, the two passes' working sets:

| Pass input | Rows | Bytes scanned/pulled |
| --- | ---: | ---: |
| Repair LIKE scan (`outcome":"abandoned"` + sub-conditions) | **6,995 matched** (15,523 match the bare LIKE) | 17.5 MB `record_json` deserialized |
| No-marker terminalization candidates | **255** | each → `read_dir` + per-entry `stat` + project-file read |

A pure read-only replay of the repair `WHERE` clause in Python's `sqlite3` took
**156 ms warm**. The production path is materially worse: it runs in Rust with
`serde_json` deserialization of every matched 5.3 KB blob, holds a write
transaction, and — critically at startup — reads the 141 MB file from a **cold
page cache**, turning the scan into real disk I/O. Add the 255 candidate dirs ×
multiple cold filesystem syscalls each, and the multi-second-to-minute freeze
follows directly.

## The Code Path

### Where it runs on the UI thread

`src/sase/ace/tui/actions/agents/_loading_disk.py` correctly offloads the disk
load and prep to worker threads (`asyncio.to_thread`, lines ~367/383). But the
**apply continuation runs back on the event loop**:

- `_loading_disk.py:403` calls `self._apply_loaded_agents_prepared(...)` directly
  (not inside `to_thread`).
- `_loading_apply.py:268` `_apply_loaded_agents_prepared_inner(...)`, when
  `persist_dismissed_changes` is true, calls
  `sync_dismissed_agent_artifact_index(...)` at lines 316–323.

`persist_dismissed_changes` is set when there are recovered-bundle, auto-dismiss,
or orphan-removal deltas (`_loading_disk.py:408–411`). The **first full load
after startup** routinely has such deltas, so the first apply pays the cost — on
a cold cache. Dismiss/kill/revive during a session re-trigger it too.

### Why the expensive pass always runs

`src/sase/core/agent_artifact_index_lifecycle.py:179–190`:

```python
with agent_artifact_index_operation_lock():
    ...
    report = _sync_projection(index, dismissed, added=added, force=force)
    return _run_active_tier_maintenance(index, report)   # <-- UNCONDITIONAL
```

Even when `_sync_projection` hits its fast path (dismissed signature unchanged →
`changed=False`), `_run_active_tier_maintenance` still runs. The `added=` "fast
projection" route added in the 2026-06-20 work does **not** help here, because
terminalization is invoked regardless of whether the projection changed.

`_run_active_tier_maintenance` (lines 345–372) unconditionally calls
`terminalize_stale_active_agent_artifact_index_rows(...)` with a 24 h staleness
window and `max_rows=10_000`. The facade
(`src/sase/core/agent_scan_facade.py:162–183`) takes the global
`agent_artifact_index_operation_lock()` and calls into Rust, so the whole thing
also serializes against every other index operation.

### What the Rust call actually does (per invocation)

`../sase-core/crates/sase_core/src/agent_scan/index.rs:199`
`terminalize_stale_active_agent_artifact_index_rows`:

1. `open_index` — opens the 141.7 MB SQLite database.
2. `repair_abandoned_agent_artifact_index_rows` (line 207, body at 230) — a
   **full-table scan** with `record_json LIKE '%"outcome":"abandoned"%'` plus two
   more `record_json LIKE` sub-predicates. `record_json` is an unindexed ~5.3 KB
   TEXT column, so SQLite cannot use an index; it reads every row and
   deserializes each abandoned match (`serde_json::from_str`). This set is
   **15,523 rows** today and **grows every time an agent terminalizes** — the
   pass that *creates* abandoned rows also *re-scans all prior* abandoned rows on
   the next call. This is the primary super-linear driver behind the worsening
   328 s outlier.
3. `select_terminalization_candidates` (line 1017) — selects rows with no
   done/running/waiting/workflow/pending marker (**255 today**). This is the set
   inflated by the known "stopped-without-`done.json` looks active" semantics bug
   from the 2026-06-16 study.
4. For each candidate, `terminalize_stale_candidate` (line 1056) does
   **filesystem re-validation**:
   - `MarkerSignatures::from_artifact_dir` — stats marker files in the dir;
   - on drift, `scan_agent_artifact_dir` + `upsert_record` (re-read + SQLite write);
   - `artifact_dir_latest_modified` (line 1117) — `fs::read_dir` + `stat` on
     every directory entry;
   - `record_has_live_workspace_claim` (line 1140) — `fs::read_to_string` of the
     project file.

   On the cold cache present at startup, each of those is a real disk seek.

So every invocation is `O(abandoned rows)` JSON deserialization **plus**
`O(no-marker candidates × filesystem ops)`, under a global lock, on the event
loop thread.

## Why It Is Specifically A Startup Problem

- **Cold page cache.** Right after launch, neither the 141 MB SQLite file nor
  the thousands of artifact dirs are in the OS page cache. The same two passes
  that cost ~150 ms warm cost seconds-to-minutes when every page read is a disk
  I/O. Subsequent in-session runs are faster because the first run warmed the
  cache — which is exactly why the *first* navigation attempt is the one that
  hangs for "almost a minute."
- **The first apply almost always persists a dismissed delta**, so the
  `sync_dismissed_agent_artifact_index` → terminalize path is taken on that first
  cold load rather than being skipped.

## Relationship To Prior Research

This is not a new regression — it is a **known, still-unfixed** issue:

- `tui_performance_log_research_consolidated_20260620.md` ranked exactly this
  pipeline #1 ("Fix the agent-index refresh pipeline: move
  `sync_dismissed_agent_artifact_index()` and active-tier terminalization out of
  the UI-thread apply continuation … gate terminalization so it cannot run on
  every apply"). The recommendation was not yet implemented; today's stall has
  the identical stack.
- `tui_tmux_performance_consolidated_20260616.md` identified the upstream data
  bug: Tier 1 returns too many rows because stopped-without-`done.json` records
  look active. That bug is what keeps the candidate set (and the abandoned-row
  set, once terminalized) populated.
- `memory/tui_perf.md` rule #1 ("Never block the event loop") and rule #2 ("Run
  slow user-initiated operations as tracked background tasks") are both violated
  by the current apply continuation.

## Recommended Solution

Three layers, in priority order. Layer 1 alone removes the user-visible freeze;
layers 2–3 stop it from regressing as data grows.

### Layer 1 — Get terminalization off the apply hot path (fixes the freeze)

1. **Decouple maintenance from the per-apply sync.** In
   `agent_artifact_index_lifecycle.py`, stop calling
   `_run_active_tier_maintenance` from inside
   `sync_dismissed_agent_artifact_index_report`. The dismissed-projection sync
   (small, bounded) and active-tier terminalization (large, unbounded) are
   different concerns and must not be coupled.
2. **Run it off the event-loop thread as a tracked background task.** Per
   `memory/tui_perf.md` rule #2, route active-tier maintenance through
   `_submit_tracked_task()` / `_submit_background_task()`
   (`src/sase/ace/tui/actions/task_actions.py`) rather than calling it inline in
   `_apply_loaded_agents_prepared_inner`. The apply continuation should mutate
   in-memory dismissed state and persist the small `dismissed_agents.json`
   optimistically, then schedule the index work to run later off-thread. Even the
   dismissed-projection SQLite write should move off the loop given the index is
   141 MB.
3. **Gate/throttle so it runs at most once per session (or once per N minutes),
   not on every apply.** A session-scoped "active-tier maintenance already ran"
   flag, or a `meta`-stored last-run timestamp checked before scheduling, removes
   the repeated mid-session freezes (the 57 s/65 s/83 s in-session recoveries).

### Layer 2 — Shrink the Rust O(N) passes (stops the super-linear growth)

4. **Bound `repair_abandoned_agent_artifact_index_rows`.** It currently re-scans
   and re-deserializes all ~15.5 k abandoned rows on every call, and that set
   only grows. Gate it behind a persisted repair watermark / schema-version (only
   inspect rows changed since the last repair), or run repair only during a full
   `rebuild_agent_artifact_index`, not on every terminalize.
5. **Make the abandoned/terminal predicate index-friendly.** Replace the
   unindexed `record_json LIKE '%"outcome":"abandoned"%'` with a denormalized
   boolean/enum column (e.g. `terminal_outcome`) that can be indexed, so the scan
   is `O(matches)` not `O(all rows × blob length)`.
6. **Cap and lazily schedule candidate revalidation.** Process the 255-row
   candidate filesystem re-validation incrementally / time-budgeted off the lock,
   instead of all-at-once inside one locked Rust call.

### Layer 3 — Data hygiene (removes the underlying driver)

7. **Fix the stopped-without-`done.json` semantics** (carried over from
   2026-06-16) so agents reach a terminal state promptly and stop re-entering the
   candidate and abandoned sets.
8. **Add retention/compaction** for the artifact index (141 MB / 18.7 k rows),
   `agent_name_registry.json` (30 MB), and `prompt_history.json` (33 MB). These
   files grow without bound and inflate every scan, lock hold, and startup. The
   2026-06-20 study independently flagged the 32 MB prompt-history rewrite on
   launch.

### Validation

Use the existing instrumentation (`memory/tui_perf.md`):

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ~/.sase/perf/research_YYYYMMDD/tui_profile.txt
```

Cold-start the TUI (drop caches or reboot to reproduce the cold-cache path),
land on the Agents tab, and immediately drive j/k. Success criteria:

- No `tui_stalls.jsonl` stack containing `sync_dismissed_agent_artifact_index`,
  `_run_active_tier_maintenance`, or
  `terminalize_stale_active_agent_artifact_index_rows`.
- No `tui.log` "recovered after" lines over a few seconds during startup or
  steady-state navigation.
- First-navigation-after-startup key-to-paint within the normal j/k budget
  (target p95 < 16 ms; certainly no multi-second hang).
- Active-tier maintenance still runs (terminalizes stale rows) but only as an
  off-thread, throttled background task that never appears on the main-thread
  stack.

## Bottom Line

The minute-long startup hang is a synchronous event-loop block, not slow
rendering. The agents apply continuation calls artifact-index active-tier
terminalization inline on the UI thread; that Rust call does a full-table
abandoned-row scan plus per-candidate cold-cache filesystem reads over a 141 MB
index / 18.7 k rows, and it runs on every apply with a dismissed delta. It was
already identified as the top issue on 2026-06-20 and remains unfixed. Move it
off the hot path (decouple, background-task, throttle), then shrink the two Rust
O(N) passes and add data retention so it cannot regress.
