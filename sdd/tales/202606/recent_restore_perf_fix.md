---
create_time: 2026-06-06 09:33:06
status: done
prompt: sdd/prompts/202606/recent_restore_perf_fix.md
---
# Plan: Fix TUI dismiss-path performance regression from recent agent restore

## Context

The recently-landed `recent_agent_restore` change (commit `1b1ce7921`, plus sibling `sase-core` `21f4875`) added
recording of recent dismissals so they can be revived from the Agent Restore panel. While reviewing it for performance
impact, I found it introduced **synchronous filesystem I/O on the UI thread during every dismiss / kill /
save-and-dismiss keypress**, plus a redundant disk read on the cold-start path. The TUI is latency-sensitive (cf.
`memory/long/tui_jk_baseline.md` and the deliberate "defer the heavy refilter so the toast can paint" optimization in
the dismiss path), so this is a real degradation worth fixing.

This plan fixes the degradation with a small, contained change. **No `sase-core` / Rust changes are needed.**

## Findings

### Finding 1 — primary degradation: per-agent `find_bundle` disk scan on the UI thread

All four user-facing dismiss/kill/save paths now build a `SavedAgentGroupWire` **synchronously on the UI thread**,
before the toast paints:

- `_dismiss_planned_agent` (single dismiss) — `_dismissing.py:255`
- `_do_dismiss_all` (batch dismiss) — `_dismissing.py:150`
- `_do_bulk_kill_agents` (bulk kill/dismiss) — `_killing.py:419`
- `_save_marked_agent_group` (save-and-dismiss) — `_marking.py:295`

The builder `build_saved_agent_group` (`_saved_group_records.py`) calls, for **every agent in the group**,
`_saved_group_ref_for_agent` → `_bundle_path_for_agent` → `dismissed_bundle_path_for_agent` → `find_bundle`
(`dismissed_agents_paths.py:40`). When the bundle is not found, `find_bundle` does a shard fast-path `stat`, a legacy
`stat`, then a full `readdir` of the bundles dir **plus a `stat` in every `YYYYMM` shard directory**.

Two facts make this pure wasted work on these paths:

1. The dismissed bundle is written **asynchronously afterward**, inside the persistence worker (`asyncio.to_thread`). At
   build time the bundle is not on disk, so `find_bundle` always falls through to the full shard scan and returns
   `None`.
2. `agent._dismissed_bundle_path` is set **only** when an agent is loaded from a bundle
   (`dismissed_agents_bundles.py:281`). The live agents these paths operate on never carry it, so
   `_bundle_path_for_agent` always reaches the disk probe.

**Cost:** `O(agents-in-action) × O(months-of-shard-dirs)` `stat`/`readdir` syscalls on the UI thread per keypress,
growing as bundle history accumulates. For `_do_dismiss_all` this runs _before_ the
`call_later(self._apply_dismissal_in_memory, …)` at `_dismissing.py:169` — i.e. it directly undercuts the existing
optimization that defers the heavy refilter to keep the UI tick light.

**Regression vs. before:** previously the only group builder (`_build_saved_agent_group` in the old `_marking.py`) ran
_inside the worker_ (`_persist_marked_agent_group_save` via `asyncio.to_thread`), so this disk I/O was off the UI
thread. The new code moved the build to the UI thread for optimistic caching and brought the disk probe with it.

**`bundle_path` is not needed for correctness.** `resolve_saved_group_agents` (`_revive_group_resolution.py`) loads
bundles by `raw_suffix` and matches refs by `raw_suffix` (+ `agent_type`/`cl_name`/`parent_timestamp`). `bundle_path` is
used only as a first-pass exact-match optimization (`pop_agent_for_group_ref`, lines 43–51); when absent, the robust
suffix matcher handles it — which is exactly how freshly-recorded recent dismissals must resolve anyway.

### Finding 2 — minor: redundant recent-store disk read at startup

`_state_init.py:419-429` calls `list_recent_dismissed_agent_groups(limit=10)` and then
`load_recent_dismissed_agent_group(group_id)` for each returned summary — reading every recent record file **twice** —
synchronously during `AceApp.__init__`, the cold-start path the codebase otherwise keeps lean (e.g. the deferred xprompt
snippet scan nearby).

This pre-load is redundant. The only consumer of `_recent_dismissed_agent_groups` is the revive-modal flow, and
`_revive_agent` (`_revive_flow.py:58-71`) **unconditionally re-reads the recent store from disk and merges it into the
cache every time the modal opens**. Initializing the cache to `[]` at startup therefore loses nothing: the first modal
open reproduces the same merged result (persisted disk records + any session-cached optimistic rows), while removing all
recent-store disk I/O from `__init__`.

## Proposed Fixes

### Fix 1 — stop probing disk for bundle paths during the optimistic build

- Add a `resolve_bundle_paths: bool = True` parameter to `build_saved_agent_group`, threaded through
  `_saved_group_ref_for_agent` to `_bundle_path_for_agent`. When `False`, `_bundle_path_for_agent` returns only the
  in-memory `_dismissed_bundle_path` attribute (preserved for the rare revived-then-re-dismissed agent) and **never**
  calls `dismissed_bundle_path_for_agent` — i.e. zero filesystem syscalls.
- Pass `resolve_bundle_paths=False` from the two UI-thread call sites:
  - `build_recent_dismissed_agent_group` (`_recent_dismissal_groups.py:47`) — covers single dismiss, batch dismiss, and
    bulk kill/dismiss.
  - `_save_marked_agent_group` (`_marking.py:295`) — save-and-dismiss.
- Net effect: the build does no disk I/O; `bundle_path` is `None` for fresh dismissals (unchanged from current
  _effective_ behavior, since the probe already returns `None`); revive continues to resolve by suffix.

Keeping the default `True` preserves the disk-resolving capability for any future off-UI-thread caller and keeps the
change minimal and reviewable (two call-site edits plus helper signatures).

_Considered and rejected:_ re-resolving `bundle_path` in the persistence worker (after bundles are written) to restore
the old marked-save fidelity. Unnecessary — `bundle_path` is purely an optimization for revive matching, and the
optimistic cached record built on the UI thread would lack it regardless. Adds complexity for no functional gain.

### Fix 2 — drop the redundant startup recent-store read

- Replace the `try/except` disk-loading block at `_state_init.py:419-429` with
  `self._recent_dismissed_agent_groups = []`, and remove the now-unused `list_recent_dismissed_agent_groups` /
  `load_recent_dismissed_agent_group` imports from that function. The revive-modal open path already populates the cache
  from disk.

_Out of scope (noted):_ `_revive_agent` performs the same list-then-load-each double read on modal open. That is a
deliberate user action (the `R` key), not a hot autorepeat key, and removing the redundancy cleanly would require a new
`sase-core`/binding "load full recent records in one pass" function (the binding's `list_*` returns summaries only).
Deferred to avoid a Rust-boundary change for a non-hot path.

## Files to change

- `src/sase/ace/tui/actions/agents/_saved_group_records.py` — add `resolve_bundle_paths` param to
  `build_saved_agent_group`, `_saved_group_ref_for_agent`, `_bundle_path_for_agent`.
- `src/sase/ace/tui/actions/agents/_recent_dismissal_groups.py` — pass `resolve_bundle_paths=False`.
- `src/sase/ace/tui/actions/agents/_marking.py` — pass `resolve_bundle_paths=False`.
- `src/sase/ace/tui/actions/_state_init.py` — initialize the cache to `[]`; drop the startup disk read and unused
  imports.

No `sase-core` / PyO3 changes.

## Test Plan

- **New unit coverage** in the saved-group-records / recent-dismissal area: assert that
  `build_saved_agent_group(..., resolve_bundle_paths=False)` performs **no** bundle disk lookup (monkeypatch
  `dismissed_bundle_path_for_agent` to record calls / raise and assert it is never invoked) and yields refs with
  `bundle_path=None`, while still honoring a pre-set in-memory `_dismissed_bundle_path`. Also assert the default
  (`True`) path still resolves via the helper, to lock the parameter contract.
- **Startup**: assert `_recent_dismissed_agent_groups == []` after `_init_app_state` and that the recent-store list/load
  facade functions are not called during init (patch + assert-not-called). Confirm the revive modal still surfaces
  persisted recent groups via the existing routing tests.
- **Regression**: existing dismiss/kill/mark in-memory + persistence tests and the revive routing/execution tests must
  still pass unchanged (they exercise optimistic caching and suffix-based revive, which is unaffected).
- **Visual**: snapshots unaffected — `bundle_path` is an internal ref field, never rendered in the Agent Restore modal.

## Verification

- `just install` (ephemeral workspace — deps may be stale).
- Targeted:
  `pytest tests/test_dismissed_agent_groups.py tests/test_agent_group_revival_routing.py tests/test_agent_group_revival_execution.py tests/test_agent_dismiss_in_memory.py tests/test_agent_dismiss_persistence.py tests/ace/tui/modals/test_saved_agent_group_revival_modal.py tests/ace/tui/test_agent_marking_save.py`
- `just check`.

## Rollout Notes

Pure performance fix with no user-visible behavior change: the Agent Restore panel, recent recording, and
revive-by-suffix all behave identically. The change removes UI-thread disk syscalls from the dismiss/kill/save hot paths
and from cold-start `__init__`, and is trivially reversible (flip the `resolve_bundle_paths` defaults / restore the
startup read).
