# TUI + xprompt-LSP recurring ~60s freeze — shared artifact-index convoy — 2026-06-27

## Question

The ACE TUI freezes "a solid 60 seconds at a time," frequently, and the xprompt
LSP stops working during the same windows. What is the root cause, and how do we
fix it?

## Conclusion (root cause)

The freezes hitting **both** the TUI and the LSP "for a solid 60 seconds at a
time" are **two faces of one event: a write/lock convoy on a single bloated
SQLite index**, `~/.sase/agent_artifact_index.sqlite`.

That database is now **157 MB** (≈19k rows, mostly inline blobs), and there is
already a `agent_artifact_index.sqlite.corrupt-20260610T003030Z` (110 MB)
quarantine file — it corrupted once under concurrent writes. It is the single
artifact index shared by **every** SASE process: the TUI, every background
agent, `sase query`, and the `sase` helper-bridge subprocess the xprompt LSP
spawns. At this size a single write transaction takes tens of seconds, and:

1. **TUI freezes** — the **revive** action still writes the index *synchronously
   on the Textual event-loop thread* (`_revive_execution.py:121/132/315/338`).
   The FFI call parks the loop until the write returns. The watchdog captured
   exactly this stack as recently as **today** (2026-06-27), -06-25, and -06-23.
2. **LSP freezes** — the heavy write saturates host CPU/disk, and the dozens of
   agent processes that write a marker mutation on every status change convoy on
   the index's single WAL writer lock under a too-short **5 s** `busy_timeout`.
   A `sase` helper-bridge cold-start during that burst is starved; if the LSP's
   **explicit** catalog refresh runs in that window it chains two 30 s timeouts
   (xprompt, then snippet) → up to **~60 s** with no fresh catalog.

The "~60 s" is how long a bloated-index write/maintenance pass takes (plus
chained 5 s busy-timeout retries across contending writers), **not** a configured
freeze timer. (`FULL_SANITY_REFRESH_SECONDS = 60.0` in
`event_refresh/_constants.py:10` is the TUI's full-refresh *interval* — a
coincidental 60, not the freeze duration.)

The simultaneous LSP failure is the decisive discriminator. A *separate* process
dying at the same instant means a **shared resource**, not an in-process stall —
and it also rules out the static Neovim config gate below as the cause of the
*60-second* symptom (a config bypass would break completion all the time, not for
"60 seconds at a time").

## Evidence

### 1. The freeze is real, recurring, ~60 s — and most long stalls are NOT this bug

`~/.sase/logs/tui_stalls.jsonl` holds **58** watchdog records. Classified by
captured **loop-thread** stack:

| Count | Class | Blocks the LSP too? |
| ---: | --- | --- |
| ~35 | editor / pager / viewer `suspend()` waits (user-initiated) | No |
| **11** | **synchronous Rust artifact-index ops on the loop thread** | **Yes** |
| ~7 | artifact-image viewer key-read under suspend | No |
| ~5 | detail-header live `git diff` / other subprocess | No |

Recovery durations in `tui.log` cluster tightly around the reported number for
the relevant class — **54.1, 57.1, 58.6, 59.0, 59.5, 64.5, 65.1, 73.0 s**. The
83–2369 s outliers are editor-`suspend()` waits (the user walked away inside
`nvim`); they dominate the log but are user-initiated, do not touch the LSP, and
are a separate classification problem (see Follow-ups). The **11 artifact-index**
records are the ones that match "TUI froze *and* the LSP died."

### 2. The shared resource: one 157 MB index, opened by every process

```text
157M  ~/.sase/agent_artifact_index.sqlite                              (live)
110M  ~/.sase/agent_artifact_index.sqlite.corrupt-20260610T003030Z     (prior corruption)
```

- Opened in `agent_scan/index.rs:563 open_index()` with `journal_mode = WAL`
  (line 572) and `busy_timeout = 5 s` (line 568).
- Bloat is fed by scale: `~/.sase/projects/sase/artifacts/ace-run` holds **15,204**
  run directories. (Separately, `~/.sase/run/sase-host/projections/projection.sqlite`
  is 1.6 GB — a different per-host DB, not the shared index, but it confirms the
  general artifact-scale pressure.)
- Every agent status change writes the index from a **separate process** via
  `update_agent_artifact_index_for_marker_mutation(...)` — call sites include
  `agent/running.py:497`, `xprompt/workflow_executor.py:179,596`,
  `workflows/commit/commit_tracking.py:231`, `plan_approval_actions.py:265`,
  `axe/run_agent_helpers_artifacts.py` (×5), `axe/run_agent_wait.py` (×3). With
  many concurrent agents these are frequent, independent writers.

### 3. Why the TUI loop thread still blocks — the revive path is not offloaded

The maintenance and startup-sync paths are **already correct**: apply-time
maintenance is scheduled off-loop (`_loading_apply.py:311
_schedule_artifact_index_maintenance`), `_index_maintenance.py:95` runs the sync
via `asyncio.to_thread`, and the PyO3 bindings **release the GIL**
(`py.allow_threads` around upsert/terminalize/query in `sase_core_py/src/lib.rs`).
So "the GIL is held" / "just make it async" are the wrong diagnoses — those paths
already free the loop.

The remaining offender is **revive**, which calls the index synchronously on the
event-loop thread:

```text
src/sase/ace/tui/actions/agents/_revive_execution.py
 121 / 315:  sync_dismissed_agent_artifact_index(self._dismissed_agents, added=())
 132 / 338:  upsert_agent_artifact_index_artifacts(revived_artifact_dirs)
            -> _revive_index.py -> agent_scan_facade -> sase_core_rs (Rust FFI)
```

Because the *calling* thread is the event loop, the loop is parked inside the FFI
call for the whole write — which, on a 157 MB index under writer contention, is
the ~60 s freeze. This is the stack the watchdog captured today and on -06-25/-23.

### 4. The writes hold the lock too long, and the timeout is too short

- `terminalize_stale_active_agent_artifact_index_rows` (`index.rs:199`) scans up
  to **10,000** rows (`_STALE_ACTIVE_TERMINALIZE_MAX_ROWS`) and wraps the entire
  set in a **single** `conn.transaction()` (`index.rs:233`→`305`), holding the one
  writer lock for the whole sweep instead of chunking.
- `busy_timeout` is **5 s** here (`index.rs:568`) vs **30 s** for the sibling
  archive DB (`agent_archive/mod.rs:288`). A 5 s ceiling on a DB whose writes now
  take tens of seconds means contending writers reliably hit `SQLITE_BUSY` — the
  likely origin of the 2026-06-10 corruption.

### 5. The LSP: per-completion is already resilient; the *explicit* refresh is the 60 s gap

The xprompt LSP catalog path does **not** read the index — it reads xprompt
*files* via a `sase` helper-bridge subprocess. So the LSP is taken down by **host
saturation + a slow subprocess cold-start**, not a direct SQLite lock. Crucially,
the per-completion path is **already hardened** (correcting a prior recommendation
to add this):

- Fresh cache (TTL `CACHE_TTL = 30 s`, `catalog_cache.rs:21`) is served
  immediately (`server.rs:427`).
- A stale/missing cache triggers `refresh_for_completion` bounded at
  `COMPLETION_REFRESH_TIMEOUT = 5 s` (`catalog_cache.rs:19`); on timeout it falls
  back to the stale cache (`server.rs:445-450`). Stale-while-revalidate already
  exists.

The real gap is **`refresh_catalog_explicit`** (`server.rs:566`), which refreshes
xprompts and then snippets **sequentially**, each bounded by
`EXPLICIT_REFRESH_TIMEOUT = 30 s` (`catalog_cache.rs:20`). Under a saturation
burst both helper calls can hit their 30 s ceiling → **~60 s** with no refreshed
catalog. This path runs on `initialized()` (`server.rs:718`) and on save/watch
(`server.rs:844`), so an LSP (re)start or explicit refresh landing inside an
index-write burst produces a self-contained "solid 60 s" LSP outage (and blank
completions entirely while the cache is still cold). This is why the helper
bridge measured fast (~0.7 s) **in isolation** yet stalls under load — the 30s+30s
chain only bites when the host is saturated.

### 6. Separate, lower-priority: local Neovim config bypasses the LSP entirely

Independent of the freeze, `~/.config/nvim/lua/plugins/sase_nvim.lua` sets
`completion_backend = "auto"` with `native_completion = false`. In `sase-nvim`,
`require("sase.lsp").complete()` returns `false` when `native_completion = false`,
so `<C-t>` falls through to the legacy completion picker even when the LSP is
attached and healthy. If LSP-backed completion has **never** worked via `<C-t>`,
this config gate — not the freeze — is the cause. It does **not** explain the
"60 seconds at a time" symptom.

## What this is and is not

- **Is:** a shared-resource (one 157 MB SQLite index) write/lock convoy that
  freezes the TUI loop (via the un-offloaded revive path + heavy periodic writes)
  and starves every other `sase` process — including the LSP's helper subprocess
  and, through it, the sequential 30s+30s explicit refresh — in the same window.
- **Is not:** the editor-`suspend()` waits (they dominate the stall log but are
  user-initiated and don't touch the LSP), a 60 s configured timeout, or the
  Neovim `native_completion` gate (a separate, always-on completion bypass).

This note supersedes `tui_freeze_xprompt_lsp_20260627.md` (codex) and
`tui_lsp_shared_index_freeze_consolidated_20260627.md` (opus). It is additive to
the earlier consolidations: 2026-06-25 flagged index bloat and the detail-header
`git diff`; 2026-06-26 flagged watchdog/suspend classification. The new findings
here are the **cross-process index convoy** that explains the simultaneous LSP
death and the precise **sequential explicit-refresh** mechanism.

## Recommended solution

Lead with the multiplier (index size), then remove the loop-thread offender and
the cross-process convoy. In priority order:

1. **Compact and cap the index (highest leverage — shrinks every freeze).**
   One-time rebuild/`VACUUM` of `agent_artifact_index.sqlite` now (the heal path
   in `_run_dismissed_index_startup_sync` already exists), then add a **retention
   policy**: prune terminal/old rows and stop storing large blobs inline in the
   hot `agent_artifacts` table. A small index turns the ~60 s write back into
   milliseconds, resolving the symptom for both the TUI and the LSP at once.

2. **Move the revive-path index writes off the event loop.** Route
   `_revive_execution.py:121/132/315/338` through the existing `asyncio.to_thread`
   / tracked-task pattern already used by `_index_maintenance.py`. The binding
   releases the GIL, so offloading genuinely frees the loop. This removes the last
   synchronous index write on the loop thread.

3. **Fix cross-process write contention.** Raise `index.rs:568` `busy_timeout` to
   30 s (matching the archive DB) **and** chunk the terminalization sweep so the
   writer lock releases between batches instead of one transaction over 10k rows
   (`index.rs:233`→`305`). Consider funneling the many agent-process marker-mutation
   writers through a single-writer discipline (short-lived file lock or dedicated
   writer) to prevent a repeat of the 2026-06-10 corruption.

4. **Harden the LSP's explicit refresh (small, targeted — per-completion is
   already resilient).** In `refresh_catalog_explicit` (`server.rs:566`), run the
   xprompt and snippet refreshes **concurrently** (e.g. `tokio::join!`) instead of
   sequentially, and/or lower `EXPLICIT_REFRESH_TIMEOUT` (`catalog_cache.rs:20`)
   so a saturation burst can't chain into a ~60 s catalog stall. Do **not**
   re-add a TTL cache or per-completion timeout — those already exist
   (`catalog_cache.rs:19,21`, `server.rs:427/445`).

**If only one thing ships first: do (1).** Index size is the multiplier on every
other symptom; shrinking it converts the ~60 s convoy back into sub-second writes
and immediately restores both the TUI and the LSP, while (2)–(4) prevent the
bloat and contention from recurring.

### Follow-ups (carried over, lower priority)

- Make the stall watchdog `suspend()`-aware so editor/viewer handoffs stop
  polluting the log as generic freezes (2026-06-26). With that, the 11
  artifact-index records become unambiguous and easy to alert on.
- Offload the detail-header live `git diff` (2026-06-25 Phase 1).
- Reduce steady-state refresh jank: a live `py-spy` sample showed time split
  across Textual/Rich repaint and artifact-index reads, and `tui_trace.jsonl`
  shows repeated `unknown_watcher_path` broad loads (1.1–1.8 s) and
  `unsupported_grouping` full display rebuilds that compound the perceived freeze.
- Verify the Neovim completion path: remove `native_completion = false` (or set
  it `true`) and confirm `<C-t>` uses LSP-backed completion; longer term, make
  `native_completion = false` disable only *automatic* completion, not explicit
  manual LSP requests.
