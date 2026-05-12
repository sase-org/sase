---
create_time: 2026-05-12 19:23:45
status: done
prompt: sdd/prompts/202605/revive_modal_freeze.md
---
# Plan: Fix TUI Freeze When Typing in Revive Modal

## Problem

Pressing `R` to revive an agent opens a project selector and then a "Revive Agents" modal with a `Archive query...`
input box. The TUI freezes as soon as the user starts typing in that box.

## Root Cause

Introduced in sase-37.6 ("Phase 5: Query-Aware Revive Modal", commit `0ef1b84cd` / final `a3553ae9`). That phase wired a
real archive-backed query provider into `DismissedAgentSelectModal`:

- `src/sase/ace/tui/modals/revive_agent_modal.py:304-308` — `on_input_changed` fires on **every keystroke**. When an
  `archive_query_provider` is set it synchronously calls `self.refresh_archive_query(event.value)`.
- `refresh_archive_query` (same file, line 179-241) calls `provider.search(query, …)`.
- The provider is the `_ScopedArchiveQueryProvider` created in `src/sase/ace/tui/actions/agents/_revive.py:215-220`. Its
  `search` delegates to `dismissed_agents.search_dismissed_archive(...)`.
- `search_dismissed_archive` (`src/sase/ace/dismissed_agents.py:641-655`) runs two potentially-slow blocking operations
  on the event loop thread:
  1. `_run_dismissed_archive_maintenance()` — one-shot migrations (`_maybe_migrate_bundles`,
     `_maybe_shard_root_bundles`, `_maybe_fix_child_collisions`). Marker files guard re-runs, but the first call can
     rename hundreds/thousands of bundle JSONs.
  2. `if not archive_index_exists(...): rebuild_index(...)` — full archive index rebuild
     (`src/sase/ace/dismissed_bundle_index/_api.py:181-197`). This holds an `archive_maintenance_lock`, deletes both
     summary and FTS tables, then re-reads and re-indexes **every** bundle on disk.

The first keystroke triggers all of the above synchronously, blocking the Textual event loop. Subsequent keystrokes also
hit the SQLite FTS query synchronously, and each keystroke fires a fresh search — there is no debouncing — so even a
"warm" keystroke path stacks work behind the event loop.

The user notices it as a freeze on the very first character typed.

## Goals

1. Typing in the revive query input must never block the TUI event loop, even on the first keystroke and even with a
   cold archive index.
2. Rapid typing should coalesce to a small number of searches rather than one per character.
3. The visible state of the modal (entry list, hints, loading indicator) should reflect "I am searching" while a search
   is in flight, instead of going silent and frozen.

## Non-Goals

- Re-architecting the archive index, query planner, or bundle storage. The underlying search is fine — it just must not
  run on the UI thread.
- Changing the `R` keymap, the project selector flow, or the revive completion pipeline.
- Reworking same-session (non-archive) filtering — that branch of `on_input_changed` already works on in-memory state
  and is cheap.

## Design

Three coordinated changes, in order of importance:

### 1. Pre-warm the archive index before / during modal mount

Move the expensive cold-start work (`_run_dismissed_archive_maintenance` + `rebuild_index` if missing) out of the
keystroke path. Two options:

- **A. Warm before opening the modal.** In `_revive.py`, just before constructing/pushing `DismissedAgentSelectModal`,
  kick off a Textual worker that calls a new `ensure_dismissed_archive_ready()` helper in `dismissed_agents.py`. The
  modal still opens immediately (it already supports `loading_archive=True` via the existing "Loading dismissed
  archive…" placeholder), and we resolve the loading state when the worker finishes.

- **B. Warm in `on_mount`.** The modal itself starts a worker in its `on_mount`, flips `_loading_archive` on, and clears
  it when the worker finishes.

Recommended: **A**, because the project-selection modal already runs first, and warming can plausibly start in parallel
with project selection. If that turns out to add complexity, fall back to B — the visible UX (modal opens, "Loading…",
typing is allowed but searches stay queued until ready) is the same.

Either way, `search_dismissed_archive` retains its safety net (build index if absent), so the pre-warm is an
optimization, not a correctness requirement.

### 2. Debounce `on_input_changed` for the archive branch

The repo already has `src/sase/ace/tui/util/debounce.py` with `DetailPanelDebouncer` (delay = 150 ms, last-write-wins).
Reuse the same pattern (either by instantiating that class directly or by extracting a generic `Debouncer` if
`DetailPanelDebouncer`'s name no longer fits — prefer reuse without renaming to avoid scope creep).

In `revive_agent_modal.py`:

- Create a debouncer in `__init__` (or lazily in `on_mount`, where `self.app` is available).
- In `on_input_changed`, for the `archive_query_provider is not None` branch, capture `event.value`, call
  `self._update_hints_if_mounted()` (so the user sees "archive loading" immediately), and `debouncer.schedule(...)` a
  callback that triggers the actual search.
- Keep the same-session branch (no archive provider) unchanged — that path is cheap and benefits from instant feedback.
- `on_input_submitted` (Enter) must flush any pending debounce so pressing Enter immediately runs the search for the
  current value, then dismisses.

### 3. Run the search on a worker thread

Even after pre-warm, `search_archive` does a synchronous SQLite FTS query that can take tens of milliseconds on large
archives. Wrap the debounced callback in a Textual `@work(thread=True, exclusive=True)` worker so the event loop stays
responsive while a query executes. The worker calls `provider.search(...)` and posts the result back to the modal (e.g.
via `self.app.call_from_thread(self._apply_archive_page, query, page)`) where the existing rendering code
(`_rebuild_options`, hints, preview) runs on the main thread.

If the worker raises, store the message in `_query_error` and clear `_loading_archive` — same shape as the current
synchronous error path.

Exclusivity matters: while a search for `"foo"` is in flight, typing one more character should cancel/replace it, not
stack a second worker. Textual's `exclusive=True` plus the existing debounce gives us both.

## Files I Expect to Touch

- `src/sase/ace/tui/modals/revive_agent_modal.py` — wire debouncer, worker, loading state in `on_input_changed`; flush
  pending work in `on_input_submitted`.
- `src/sase/ace/tui/actions/agents/_revive.py` — kick off pre-warm worker around the existing
  `_ScopedArchiveQueryProvider` construction.
- `src/sase/ace/dismissed_agents.py` — small public helper `ensure_dismissed_archive_ready()` that wraps
  `_run_dismissed_archive_maintenance` + index existence check + `rebuild_index`, so the worker has a clean entry point
  and we don't push these private functions into the TUI layer.
- (Maybe) `src/sase/ace/tui/util/debounce.py` — only if reusing `DetailPanelDebouncer` requires a docstring tweak.
  Prefer no edit; if the name is misleading in the revive context, extract a `Debouncer` base and have
  `DetailPanelDebouncer` subclass it.

## Tests

- Unit test for `ensure_dismissed_archive_ready()` in `tests/ace/test_dismissed_agents.py` (or wherever existing archive
  tests live): call against a fixture bundle dir with no index → verify index file appears and is queryable.
- Modal test (Textual `App.run_test`) in the existing `tests/ace/tui/modals/test_revive_agent_modal.py` (create if
  missing):
  1. Type 3 characters in quick succession into `#dismissed-filter`; assert `provider.search` was called exactly once
     after debounce settles, with the final composed string.
  2. Verify `Input.Submitted` (Enter) flushes a pending debounce and the search runs synchronously enough to reflect in
     the result list before dismiss.
  3. With a deliberately slow stub provider, confirm the app remains responsive to a `Key("escape")` event while a
     search is in flight (no freeze).
- No PNG-snapshot test needed; this is behavioral, not visual.

## Risks / Open Questions

- **Worker + Textual lifecycle:** workers spawned in `on_mount` of a modal need to be cancelled cleanly when the modal
  is dismissed mid-search. Use `self.workers.cancel_group(self, "revive-archive")` or similar in `on_unmount`.
- **`call_from_thread` vs message posting:** both work. Posting a custom `ArchivePageReady` message keeps the modal pure
  and is easier to unit-test — prefer that.
- **Maintenance migrations are not idempotent-safe under concurrency.** They use marker files and ignore `OSError`, so
  running once from a worker before the modal opens is fine, but we should not call them from multiple workers
  simultaneously. Pre-warm should be `exclusive=True`.
- **Pre-warm timing window:** if the user types instantly after the modal appears (faster than pre-warm finishes), the
  first search is still queued behind the worker. This is acceptable as long as the queueing happens off the event loop
  (it does — workers + debounce). Hints already display "archive loading" via `_loading_archive`, which we should set
  during pre-warm.

## Out of Scope (Follow-ups, Not in This Change)

- Incremental/streaming search results.
- Caching recent queries inside `_ScopedArchiveQueryProvider`.
- A dedicated "no archive index yet — building…" progress bar (the existing `Loading dismissed archive…` placeholder is
  enough for now).
