---
create_time: 2026-05-13 20:31:53
status: done
prompt: sdd/prompts/202605/tui_profile_slow_refresh.md
---
# Plan: Fix ACE TUI Slow Refresh From Dismissed-Agent Reloads

## Problem

The profiling report at `.sase/home/tmp/sase/ace_profile_20260513_202435.txt` shows ACE spending a visible chunk of
interactive time inside agent refresh work:

- `_run_agents_async_refresh` -> `_load_agents_async` -> `_merge_external_dismissals`
- `_merge_external_dismissals` repeatedly calls `load_dismissed_agents`
- `load_dismissed_agents` parses `~/.sase/dismissed_agents.json`

On this machine that dismissed-agent file is about 1.2 MB. The async refresh path calls `_merge_external_dismissals`
before its first `await`, so the JSON parse runs on the Textual UI thread. Repeating that parse on every refresh makes
the TUI feel slow even when no external dismissal changed.

The report also shows other costs, especially ChangeSpec query-corpus compilation and agent detail rendering, but the
dismissed-agent reload is the clearest regression-sized hot path and can be fixed without crossing the Rust migration
boundary.

## Rust Migration Boundary

This work should stay in this repo's Python/TUI layer:

- Do not migrate ACE reads to daemon-backed indexed projections.
- Do not edit `../sase-core`.
- Do not change daemon, projection, or local transport contracts.
- Do not modify `sdd/beads/issues.jsonl` unless the implementation discovers an actual conflict with `sase-3e`.

The `sase-3e` plan explicitly keeps production ACE read-path migration out of the current daemon runtime epic. A small
cache around an existing Python compatibility file is therefore compatible with the ongoing migration.

## Implementation

1. Add a tiny dismissed-agent file signature cache to ACE app state.
   - Track the last observed `~/.sase/dismissed_agents.json` signature, probably `(mtime_ns, size)`.
   - Track the cached on-disk dismissed identity set.
   - Initialize it from the existing startup load where `_dismissed_agents` is first populated.

2. Replace unconditional external-dismissal reloads with a signature-gated merge.
   - If the file signature is unchanged, skip JSON parsing.
   - If the file changed, load and union only new external identities into `_dismissed_agents`.
   - Preserve the existing union-only behavior so optimistic in-memory dismissals are not dropped before persistence.
   - On stat/read errors, keep the current fail-open behavior and do not clear in-memory state.

3. Keep async refresh nonblocking.
   - In `_load_agents_async`, run the signature-gated external dismissal merge in `asyncio.to_thread`.
   - Apply only the small returned delta on the UI thread before taking `dismissed_snapshot`.
   - Leave synchronous callers using the direct helper, since explicit sync refreshes already intentionally block.

4. Add focused tests.
   - Cache hit: repeated merge with unchanged signature should not call `load_dismissed_agents` again.
   - Cache miss: changed signature should load once and merge new external identities.
   - Union behavior: in-memory-only identities survive even when the on-disk set is smaller.
   - Async path: `_load_agents_async` should use the off-thread merge helper before snapshotting dismissed identities.

5. Verify.
   - Run the focused agent-loading/dismissed-state tests.
   - Because this repo requires it after code changes, run `just install` if needed, then `just check`.

## Expected Outcome

No-change agent refreshes should stop reparsing the 1.2 MB dismissed-agent file. The async refresh should also avoid
blocking the Textual event loop before its first await. External dismissals from other processes remain visible after
the file signature changes.
