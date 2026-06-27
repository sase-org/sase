# TUI + xprompt-LSP simultaneous ~60s freeze — shared artifact-index lock — 2026-06-27

## Scope

The ACE TUI freezes for "a solid 60 seconds at a time," frequently, and **the
xprompt LSP stops working during the same window**. The user asked for a root
cause and a recommended fix.

The simultaneous LSP failure is the decisive new clue. Every prior freeze
investigation in `sdd/research/202606/` looked only at the **Textual event loop
inside one process** (live `git diff`, editor `suspend()`, broad agent loads).
None of them explains why a *separate* process — the Neovim xprompt LSP — dies
at the same instant. That points at a **resource shared across processes**, not
an in-process event-loop stall. This note finds that shared resource and
verifies the mechanism against the live logs and source.

TUI performance context was reviewed first:

```bash
sase memory read tui_perf.md --reason "Investigating recurring 60s TUI freeze that also blocks the xprompt LSP"
```

## Conclusion (root cause)

**One shared, bloated SQLite database is the common dependency, and it has grown
large enough that writing to it takes ~tens of seconds.**

`~/.sase/agent_artifact_index.sqlite` is now **150 MB** (≈19k rows; ~135 MB of
inline blobs per the 2026-06-25 profile). It is the single agent-artifact index
shared by **every** SASE process: the TUI, every background agent, `sase query`,
and the `sase` helper-bridge subprocess that the xprompt LSP spawns for each
completion. There is already a `agent_artifact_index.sqlite.corrupt-20260610`
(106 MB) quarantine file — the index corrupted once under concurrent writes,
which is itself a symptom of this contention.

The freeze is a **cross-process write/lock convoy on that bloated index**:

1. A heavy index write runs — a periodic projection rebuild, the hourly
   terminalization sweep, or a user-triggered **revive** — and on a 150 MB
   WAL database that single Rust transaction now takes many seconds.
2. While it runs, the **TUI event loop is blocked** for any code path that still
   calls the index synchronously on the loop thread (the revive path does — see
   Evidence §3), and the watchdog records a multi-second-to-minute stall.
3. **Every other process that touches the index blocks too.** WAL allows
   concurrent readers, but only **one writer**; the configured
   `busy_timeout` is only **5 seconds** (`sase-core …/agent_scan/index.rs:568`).
   The dozens of agent processes that write a marker mutation on every status
   change, plus the TUI, pile onto one writer lock and serialize / time out.
4. The host is CPU/disk-saturated during this burst (a 150 MB SQLite scan + WAL
   checkpoint + GIL-bound Python). The xprompt LSP services each completion by
   `spawn_blocking` → shelling out `sase mobile helper-bridge xprompt-catalog`
   (`sase-core …/sase_xprompt_lsp/src/catalog_cache.rs:134,326`). That
   subprocess is a full `sase` Python cold-start; under the burst it is starved
   and slow to return, so **completions appear frozen for the same ~60s window**.

So the TUI freeze and the LSP freeze are **two faces of the same event**: the
shared 150 MB index is slow to write, and the write blocks both the TUI's loop
thread and every other `sase` process at once. The "~60 seconds" is how long a
write/maintenance pass against the bloated index (plus a chain of 5 s
busy-timeout retries across contending writers) now takes — **not** a configured
timeout. Note: `FULL_SANITY_REFRESH_SECONDS = 60.0`
(`…/event_refresh/_constants.py:10`) is the *interval* at which the TUI forces a
full refresh; it is a coincidental 60, not the freeze duration.

## Evidence

### 1. The freeze is real, recurring, and ~60 s — and most long stalls are NOT this bug

`~/.sase/logs/tui_stalls.jsonl` has **58** watchdog records. Classifying each by
its captured **loop-thread** stack:

| Count | Class | Blocks the LSP too? |
| ---: | --- | --- |
| ~35 | editor / pager / viewer `suspend()` waits (user-initiated) | No |
| **11** | **synchronous Rust artifact-index ops on the loop thread** | **Yes** |
| 7 | artifact-image viewer key-read under suspend | No |
| 3 | detail-header live `git diff` subprocess | No |
| 2 | other subprocess | No |

The recovery durations (`tui.log`) cluster tightly around the reported number
for the relevant class — e.g. `64.5 s`, `65.1 s`, `59.5 s`, `59.0 s`, `58.6 s`,
`57.1 s`, `54.1 s`, `73.0 s`. The multi-hundred / `2369 s` outliers are
editor-`suspend()` waits (the user walked away inside `nvim`) and are a separate,
already-documented classification problem — **not** the symptom under
investigation. The **11 artifact-index** records are the ones that match "TUI
froze *and* the LSP died," and they appear as recently as **2026-06-27** (today)
and **2026-06-26**.

### 2. The shared resource: one 150 MB index, opened by every process

```text
150M  ~/.sase/agent_artifact_index.sqlite          (live)
106M  ~/.sase/agent_artifact_index.sqlite.corrupt-20260610T003030Z   (prior corruption)
```

- Opened in `sase-core/crates/sase_core/src/agent_scan/index.rs:563 open_index()`
  with `journal_mode = WAL` (line 572) and `busy_timeout = 5 s` (line 568).
- Every agent status change writes it from a **separate process** via
  `update_agent_artifact_index_for_marker_mutation(...)` — call sites include
  `agent/running.py:497`, `xprompt/workflow_executor.py:179,596`,
  `workflows/commit/commit_tracking.py:231`, `plan_approval_actions.py:265`,
  `axe/run_agent_helpers_artifacts.py` (×5), `axe/run_agent_wait.py` (×3), and
  more. With many concurrent agents, these are frequent, independent writers.
- The xprompt LSP catalog path itself does **not** read the index
  (`integrations/_mobile_helper_catalog.py:65 xprompt_catalog_response` →
  `build_structured_xprompts_catalog`, which reads xprompt *files*). The LSP is
  taken down by **host saturation + its own per-completion `sase` subprocess
  cold-start**, not by a direct lock on the catalog query. (This corrects an
  intermediate hypothesis that the LSP shares the SQLite lock directly — it does
  not; the coupling is resource contention, plus the convoy on any `sase`
  subprocess that *does* write the index.)

### 3. Why the TUI's loop thread still blocks — the revive path is not offloaded

Good news first: the maintenance and startup-sync paths are **already** correct.
`_index_maintenance.py:95` and `startup.py:_run_dismissed_index_startup_sync`
run the sync via `asyncio.to_thread`, and the PyO3 bindings **release the GIL**
around the SQLite work (`sase_core_py/src/lib.rs` — `py.allow_threads(...)` at
:737 upsert, :795 terminalize, plus query/scan/write). So those paths do free
the loop.

The remaining offender is the **revive** action, which calls the index
**synchronously on the event-loop thread**:

```text
src/sase/ace/tui/actions/agents/_revive_execution.py
 121:   sync_dismissed_agent_artifact_index(self._dismissed_agents, added=())
 132:   upsert_agent_artifact_index_artifacts(revived_artifact_dirs)
 315/338:  (batch revive — same two calls)
        -> _revive_index.py:41/52
        -> agent_artifact_index_lifecycle / agent_scan_facade
        -> sase_core_rs (Rust)  # FFI call parks the loop thread until it returns
```

This is exactly the stack the watchdog captured on 2026-06-27, -06-25, and
-06-23 (`_revive_index.py:52 upsert_agent_artifact_index_artifacts` in the
**loop-thread** stack). Because the binding releases the GIL but the *calling*
thread is the event loop, the loop is parked inside the FFI call for the whole
write — which, on a 150 MB index under writer contention, is the ~60 s freeze.

### 4. The writes hold the lock too long, and the timeout is too short

- `terminalize_stale_active_agent_artifact_index_rows`
  (`index.rs:199`) scans up to **10,000** rows
  (`_STALE_ACTIVE_TERMINALIZE_MAX_ROWS = 10_000`) and its `repair` pass wraps the
  entire row set in a **single** `conn.transaction()` (`index.rs:233`→`305`),
  holding the one writer lock for the whole sweep instead of chunking.
- `busy_timeout` is **5 s** here, vs **30 s** for the sibling archive and
  dismissed-bundle DBs (`agent_archive/mod.rs:288`, `dismissed_bundles` schema).
  A 5 s ceiling on a DB whose writes now take tens of seconds means contending
  writers reliably hit `SQLITE_BUSY` — the likely origin of the 2026-06-10
  corruption.

## What this is and is not

- **Is:** a shared-resource (single bloated SQLite index) write/lock-convoy that
  freezes the TUI loop (via the un-offloaded revive path and heavy periodic
  writes) and starves every other `sase` process — including the LSP's
  per-completion subprocess — during the same window.
- **Is not:** the editor-`suspend()` waits (those dominate the stall log but are
  user-initiated and do not touch the LSP), nor the detail-header live `git diff`
  (already recommended for offload on 2026-06-25), nor a 60 s configured timeout.

This note is **additive** to the prior two consolidations: 2026-06-25 already
flagged index bloat (its Phase 3) and 2026-06-26 already flagged
watchdog/suspend classification. Neither identified the **cross-process** lock
dimension that explains the LSP. That dimension is the new finding here.

## Recommended solution

Lead with the multiplier (index size), then remove the loop-thread offender and
the cross-process convoy. In priority order:

1. **Compact and cap the index (highest leverage — shrinks every freeze).**
   One-time rebuild/`VACUUM` of `agent_artifact_index.sqlite` now (the heal path
   in `_run_dismissed_index_startup_sync` already exists), then add a **retention
   policy**: prune terminal/old rows and stop storing large blobs inline in the
   hot `agent_artifacts` table. A small index turns the ~60 s write back into
   milliseconds, which alone resolves the user-visible symptom for both the TUI
   and the LSP.

2. **Move the revive-path index writes off the event loop.** Route
   `_revive_execution.py:121/132/315/338` through the existing
   `asyncio.to_thread` / `_submit_tracked_task` pattern already used by
   `_index_maintenance.py`. The GIL is released by the binding, so off-loading
   genuinely frees the loop. This removes the only remaining synchronous
   index-write on the loop thread.

3. **Fix the cross-process write contention.** Raise `index.rs:568`
   `busy_timeout` to 30 s (matching the archive/dismissed DBs) **and** chunk the
   terminalization sweep so the writer lock is released between batches instead
   of one transaction over 10k rows (`index.rs:233`→`305`). Consider funneling
   the many agent-process marker-mutation writers through a single-writer
   discipline (a short-lived file lock or a dedicated writer) so they cannot
   stampede the index. This is what prevents a future repeat of the 2026-06-10
   corruption.

4. **Make the xprompt LSP resilient to a slow host.** Serve the completion
   catalog **stale-while-revalidate** with a short TTL and bound the
   `helper-bridge` subprocess with a timeout, so one slow `sase` cold-start
   during an index burst never blanks completions for ~60 s
   (`sase_xprompt_lsp/src/catalog_cache.rs:134`).

**If only one thing ships first: do (1).** The index size is the multiplier on
every other symptom; shrinking it converts the ~60 s convoy back into
sub-second writes and immediately restores both the TUI and the LSP, while (2)
and (3) prevent the bloat and contention from recurring.

### Follow-ups carried over from prior research (still valid, lower priority)

- Make the stall watchdog `suspend()`-aware so editor/viewer handoffs stop
  polluting the log as generic freezes (2026-06-26 recommendation). With that in
  place, the 11 artifact-index records become unambiguous and easy to alert on.
- Offload the detail-header live `git diff` (2026-06-25 Phase 1).
